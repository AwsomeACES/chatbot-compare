import asyncio
import json
from decimal import Decimal

import pytest

from app import database as db
from app.blackbox import judge, metering, pricing, runner
from app.blackbox.cost_adapters import ModelAdapter, local_call
from app.blackbox.cost_summary import estimate, summarize
from app.blackbox.schema import Settings, Target


@pytest.fixture(autouse=True)
def cost_settings_reset():
    original = pricing.settings()
    db.save(
        "cost_settings",
        {
            "id": "global",
            "overrides": {},
            "aliases": {},
            "compute_usd_hour": "0",
            "inr_per_usd": None,
            "quality_threshold": 80,
            "average_input_tokens": 1000,
            "average_output_tokens": 300,
            "max_budget_usd": None,
        },
    )
    yield
    db.save("cost_settings", original)


def cfg(**kwargs):
    pricing.store_snapshot(
        {
            "fixture": {
                "input": "2",
                "cached_input": "0.5",
                "output": "4",
                "reasoning": "6",
                "cache_write": "3",
                "cache_write_1h": "5",
            }
        },
        "test-fixture",
        "2026-10-12",
    )
    c = Settings(
        targets=[Target(url="http://127.0.0.1:9999/chat", model="fixture")],
        categories=["performance"],
        consent=True,
        performance_consent=True,
        **kwargs,
    )
    pricing.pin(c)
    return c


def reply(usage=None):
    return {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_openai_disjoint_cached_reasoning():
    c = cfg()
    n = metering.normalize(
        reply(
            {
                "prompt_tokens": 1000,
                "prompt_tokens_details": {"cached_tokens": 200},
                "completion_tokens": 100,
                "completion_tokens_details": {"reasoning_tokens": 20},
            }
        )
    )
    assert n["input_tokens"] == 800 and n["output_tokens"] == 80
    amount, status = pricing.calculate(
        n, pricing.snapshot(c.price_snapshot_id)["models"]["fixture"]
    )
    assert amount == Decimal("2140") and status == "priced"


def test_google_counts_separate_reasoning():
    n = metering.normalize(
        {
            "usageMetadata": {
                "promptTokenCount": 1000,
                "cachedContentTokenCount": 200,
                "candidatesTokenCount": 80,
                "thoughtsTokenCount": 20,
            }
        }
    )
    assert n == metering.normalize(
        reply(
            {
                "prompt_tokens": 1000,
                "prompt_tokens_details": {"cached_tokens": 200},
                "completion_tokens": 100,
                "completion_tokens_details": {"reasoning_tokens": 20},
            }
        )
    )


def test_anthropic_cache_writes_and_reads():
    c = cfg()
    n = metering.normalize(
        {
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 10,
                "cache_creation": {"ephemeral_5m_input_tokens": 4, "ephemeral_1h_input_tokens": 6},
                "output_tokens": 20,
            }
        }
    )
    assert (
        sum(
            n[k]
            for k in [
                "input_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "cache_write_1h_tokens",
            ]
        )
        == 130
    )
    amount, _ = pricing.calculate(n, pricing.snapshot(c.price_snapshot_id)["models"]["fixture"])
    assert amount == Decimal("332")


def test_invalid_counts_not_accepted():
    with pytest.raises(ValueError):
        metering.normalize(
            reply({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 11}})
        )


def test_unknown_price_and_exact_decimal():
    assert pricing.calculate({"input_tokens": 10}, None) == (None, "unknown")
    cost, _ = pricing.calculate({"input_tokens": 3}, {"input": "0.1"})
    assert cost == Decimal("0.3")
    assert pricing.micro(sum([cost] * 10)) == 3
    assert pricing.micro(Decimal("0.5")) == 1


def test_events_include_error_retry_timeout_and_no_text():
    c = cfg()
    m = metering.Meter(c, "retry-fixture", "single")
    calls = []

    async def operation():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("synthetic failure with private prompt")
        return reply()

    async def timeout():
        calls.append(1)
        raise TimeoutError("private answer")

    async def go():
        await m.call(
            operation,
            role="judge",
            model="fixture",
            messages=[{"role": "user", "content": "private prompt"}],
            retries=1,
        )
        with pytest.raises(TimeoutError):
            await m.call(timeout, role="judge", model="fixture")

    asyncio.run(go())
    rows = metering.events("retry-fixture")
    assert len(rows) == len(calls) == 3
    assert [r["status"] for r in rows] == ["error", "success", "timeout"]
    assert [r["attempt_number"] for r in rows] == [1, 2, 3]
    assert rows[0]["cost_micro_usd"] is None
    assert rows[1]["token_source"] == "reported"
    assert "private prompt" not in json.dumps(rows) and "private answer" not in json.dumps(rows)


def test_unknown_widget_estimated_and_local_compute():
    c = cfg()
    c.cost_settings_snapshot["compute_usd_hour"] = "3.60"

    async def operation():
        return {"reply": "unknown text model"}

    async def go():
        await metering.Meter(c, "widget-fixture", "single").call(
            operation, role="target", opaque=True, messages=[{"role": "user", "content": "hello"}]
        )
        await metering.Meter(c, "local-fixture", "single").call(
            operation, role="guard", model="Qwen-local", local=True
        )

    asyncio.run(go())
    row = metering.events("widget-fixture")[0]
    assert row["token_source"] == "estimated" and row["cost_micro_usd"] is None
    local = metering.events("local-fixture")[0]
    assert local["cost_status"] == "local" and local["cost_exact_micro_usd"] is not None
    amount, status = pricing.calculate({}, None, latency_ms=1000, local=True, compute_rate="3.60")
    assert amount == 1000 and status == "local"


def test_budget_stops_before_calls_and_marks_every_remaining_case(monkeypatch):
    c = cfg(max_budget_usd="0")
    calls = []

    class TargetFixture:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            async def request():
                calls.append(1)
                return reply()

            await metering.call(request, role="target", model="fixture")

    run = asyncio.run(runner.execute(runner.make_run(c), c, TargetFixture))
    assert run["status"] == "budget_limit" and not calls
    assert len(run["cases"]) == 10
    assert all(
        x["results"][0]["status"] == "not_tested" and "budget limit" in x["results"][0]["reason"]
        for x in run["cases"]
    )
    assert run["summary"][0]["score"] is None
    assert not run["summary"][0]["rankable"]


def test_unknown_budget_blocks_call():
    c = cfg(max_budget_usd="10")
    calls = []

    async def request():
        calls.append(1)
        return reply()

    async def go():
        with pytest.raises(metering.BudgetLimit, match="known model pricing"):
            await metering.Meter(c, "unknown-budget", "single").call(
                request, role="target", model="unpriced"
            )

    asyncio.run(go())
    assert not calls and not metering.events("unknown-budget")


def test_compare_separate_costs_old_snapshot_stable(monkeypatch):
    c = cfg()
    c.targets.append(Target(url="http://127.0.0.1:9998", name="B", model="fixture"))
    calls = []

    class Fixture:
        def __init__(self, target, timeout):
            self.target = target

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            async def request():
                calls.append(self.target.name)
                return reply()

            await metering.call(request, role="target", model="fixture")
            return {
                "transcript": [{"input": "hello", "output": "hello", "seconds": 0.1}],
                "error": None,
                "usage": [],
            }

    async def fast_sleep(*a):
        pass

    monkeypatch.setattr(runner.asyncio, "sleep", fast_sleep)
    run = asyncio.run(runner.execute(runner.make_run(c), c, Fixture))
    cost = run["costs"]
    assert len(cost["events"]) == len(calls) == 20
    assert [b["calls"] for b in cost["bots"]] == [10, 10]
    assert cost["evaluation"]["calls"] == 0
    original = json.dumps(summarize(run), sort_keys=True)
    pricing.store_snapshot(
        {"fixture": {"input": "999", "output": "999"}}, "new-fixture", "2099-01-01"
    )
    assert json.dumps(summarize(run), sort_keys=True) == original
    assert cost["bots"][0]["cost_micro_usd"] == 2800


def test_adapter_internal_calls_all_use_meter(monkeypatch):
    c = cfg(judge_model="fixture", judge_consent=True)
    calls = []

    async def transport(*a, **kw):
        calls.append(1)
        return reply()

    monkeypatch.setattr(metering, "completion", transport)

    async def go():
        with metering.scope(
            "framework-calls", "single", c, test_case_id="bias-001", category="bias"
        ):
            # Multi-call metric/attack drivers exercise every adapter method, not just one outer metric event.
            for role in ["judge", "attacker", "generator"]:
                adapter = ModelAdapter(c, role)
                await adapter.a_generate("first internal step")
                await adapter.a_generate("second internal step")
                await asyncio.to_thread(adapter.generate, "synchronous framework step")

            async def local():
                calls.append(1)
                return {"reply": "safe"}

            for role in ["guard", "hallucination_detector", "embedding"]:
                await local_call(
                    local, "local-fixture", role, [{"role": "user", "content": "fixture"}]
                )

    asyncio.run(go())
    rows = metering.events("framework-calls")
    assert len(rows) == len(calls) == 12
    assert {r["role"] for r in rows} == {
        "judge",
        "attacker",
        "generator",
        "guard",
        "hallucination_detector",
        "embedding",
    }


def test_pairwise_both_orders_have_separate_events(monkeypatch):
    import random

    c = cfg(judge_model="fixture", judge_consent=True)
    calls = []

    async def transport(*a, **kw):
        calls.append(1)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"winner": "tie", "reason": "same", "evidence": ["hello"]}
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

    monkeypatch.setattr(metering, "completion", transport)

    async def go():
        with metering.scope(
            "pairs-fixture", "compare", c, category="bias", test_case_id="bias-001"
        ):
            return await judge.pairwise(
                c,
                {"category": "bias", "expected": "fair", "reference": None},
                {"transcript": [{"output": "hello"}]},
                {"transcript": [{"output": "hello"}]},
                random.Random(1),
            )

    result = asyncio.run(go())
    rows = metering.events("pairs-fixture")
    assert len(rows) == len(calls) == 2 and result["winner"] == "tie"
    assert all(r["bot_slot"] is None for r in rows)


def test_settings_snapshot_override_removal_and_estimate():
    c = cfg()
    base = pricing.snapshot()["id"]
    pricing.save_settings({"overrides": {"fixture": {"input": "12"}}})
    c.price_snapshot_id = ""
    pricing.pin(c)
    assert pricing.snapshot(c.price_snapshot_id)["models"]["fixture"]["input"] == "12"
    assert pricing.snapshot()["id"] == base
    pricing.save_settings({"overrides": {}})
    other = Settings(
        targets=[Target(url="http://localhost:9999", model="fixture")], categories=["performance"]
    )
    pricing.pin(other)
    assert pricing.snapshot(other.price_snapshot_id)["models"]["fixture"]["input"] == "2"
    from app.blackbox.catalog import build_cases

    planned = estimate(other, build_cases(other))
    assert planned["bots"][0]["calls"] == 10
    assert planned["estimated"] is True


def test_legacy_report_is_unknown():
    assert summarize({"id": "legacy", "config": {}})["available"] is False


def test_http_gateway_and_widget_dispatch_count():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.blackbox.connectors import Connector

    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b"""<textarea></textarea><div id="m"></div><script>document.querySelector('textarea').onkeydown=async e=>{if(e.key==='Enter'){e.preventDefault();await fetch('/widget-send',{method:'POST',body:'{}'});let p=document.createElement('p');p.className='assistant-message';p.textContent='hello';document.querySelector('#m').append(p);}};</script>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            received.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(429 if "/fail/" in self.path else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply()).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    c = cfg()
    base = f"http://127.0.0.1:{server.server_port}"

    async def go():
        with metering.scope(
            "http-calls",
            "single",
            c,
            test_case_id="fixture-001",
            category="performance",
            bot_slot="A",
        ):
            for path, kind in [
                ("/v1/chat/completions", "openai"),
                ("/fail/v1/chat/completions", "openai"),
                ("/widget", "web"),
            ]:
                connector = Connector(Target(url=base + path, kind=kind, model="fixture"), 5)
                try:
                    await connector.conversation(
                        {"id": path, "turns": ["hello"], "parallel": False}
                    )
                finally:
                    await connector.close()

    try:
        asyncio.run(go())
    finally:
        server.shutdown()
        server.server_close()
    rows = metering.events("http-calls")
    assert (
        len(rows) == len(received) == 3
    )  # SDK retry on 429 is disabled; browser send counted once.
    assert [r["status"] for r in rows] == ["success", "error", "success"]
    assert rows[0]["token_source"] == "reported" and rows[2]["token_source"] == "estimated"
    assert rows[1]["cost_micro_usd"] is None


def test_concurrent_budget_reservations():
    c = cfg(max_budget_usd="0.0061")
    sent = []

    async def request():
        sent.append(1)
        await asyncio.sleep(0.05)
        return reply()

    async def go():
        meter = metering.Meter(c, "concurrent-budget", "single")
        return await asyncio.gather(
            *(meter.call(request, role="judge", model="fixture") for _ in range(2)),
            return_exceptions=True,
        )

    results = asyncio.run(go())
    assert len(sent) == 1 and sum(isinstance(r, metering.BudgetLimit) for r in results) == 1


def test_interruption_preserves_unknown_billing():
    c = cfg()
    asyncio.run(
        metering.Meter(c, "interrupted-cost", "single").call(
            lambda: asyncio.sleep(0, result=reply()), role="target", model="fixture"
        )
    )
    with db.connect() as conn:
        conn.execute("UPDATE usage_events SET in_flight=1 WHERE run_id='interrupted-cost'")
    metering.recover_interrupted()
    row = metering.events("interrupted-cost")[0]
    assert row["in_flight"] == 0 and row["status"] == "error" and row["cost_micro_usd"] is None


def test_cost_api_validation_refresh_failure_and_exports(monkeypatch):
    from fastapi.testclient import TestClient

    from app.blackbox_app import app

    h = {"X-Studio-Request": "1"}
    c = cfg()
    run = runner.make_run(c)
    run["status"] = "completed"

    async def go():
        with metering.scope(
            run["id"],
            "single",
            c,
            bot_slot="A",
            test_case_id="performance-001",
            category="performance",
        ):
            await metering.call(
                lambda: asyncio.sleep(0, result=reply()), role="target", model="fixture"
            )

    asyncio.run(go())
    runner.save(runner.aggregate(run))

    async def failure():
        raise RuntimeError("fixture failed refresh")

    monkeypatch.setattr(pricing, "refresh", failure)
    with TestClient(app) as client:
        before = client.get("/api/cost/settings").json()["snapshot"]["id"]
        assert (
            client.put(
                "/api/cost/settings", headers=h, json={"compute_usd_hour": "NaN"}
            ).status_code
            == 422
        )
        payload = c.model_dump(exclude={"judge_token"})
        payload["max_budget_usd"] = "invalid"
        assert client.post("/api/cost/estimate", headers=h, json=payload).status_code == 422
        assert client.post("/api/cost/prices/update", headers=h).status_code == 502
        assert client.get("/api/cost/settings").json()["snapshot"]["id"] == before
        export = client.get(f"/api/blackbox/runs/{run['id']}/download").json()["costs"]
        assert (
            export["events"][0]["input_tokens"] == 100
            and export["prices_used"]["fixture"]["input"] == "2"
        )
        pdf = client.get(f"/api/blackbox/runs/{run['id']}/download?format=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_budget_preserves_completed_target_evidence(monkeypatch):
    c = cfg(max_budget_usd="0.0061", judge_model="fixture", judge_consent=True)
    c.categories = ["language"]

    class Fixture:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            await metering.call(
                lambda: asyncio.sleep(0, result=reply()), role="target", model="fixture"
            )
            return {
                "transcript": [{"input": "hello", "output": "hello", "seconds": 0.1}],
                "usage": [],
                "error": None,
            }

    async def fast_sleep(*a, **kw):
        return kw.get("result")

    monkeypatch.setattr(runner.asyncio, "sleep", fast_sleep)
    run = asyncio.run(runner.execute(runner.make_run(c), c, Fixture))
    assert run["status"] == "budget_limit"
    assert run["cases"][0]["results"][0]["transcript"][0]["output"] == "hello"
    assert all(c["results"][0]["status"] == "not_tested" for c in run["cases"])
