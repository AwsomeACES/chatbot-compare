"""Timing contract uses simulated I/O, not live provider latency or credentials."""

import asyncio
import json
import statistics
import time
import uuid
from unittest.mock import AsyncMock, patch

from app.blackbox import judge, judge_batch, metering, runner, scheduling, studio_engine
from app.blackbox.governance_routes import progress
from app.blackbox.schema import Settings, Target


def config(**kwargs):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        judges=[{"model": "fixture", "local": True}],
        consent=True,
        judge_consent=True,
        **kwargs,
    )


def test_verdict_cache_avoids_rejudging_but_tracks_prompt_and_model():
    async def run():
        cfg = config()
        payload = {"transcript": [{"output": "exact answer"}]}
        fake = AsyncMock(
            return_value={"score": 90, "reason": "correct", "evidence": ["exact answer"]}
        )
        with (
            patch.object(judge, "_ask_uncached", fake),
            metering.scope(str(uuid.uuid4()), "single", cfg),
        ):
            await judge.ask(cfg, payload)
            await judge.ask(cfg, payload)
            assert fake.await_count == 1
            await judge.ask(cfg, {"transcript": [{"output": "different"}]})
            assert fake.await_count == 2
            cfg.judge_model = "other"
            await judge.ask(cfg, payload)
            assert fake.await_count == 3

    asyncio.run(run())


def test_batch_items_have_exact_independent_ids_and_temperature_zero():
    async def run():
        cfg = config(judge_batch_size=4, judge_batch_wait_ms=1)
        bodies = []

        async def completion(url, body, *args):
            bodies.append(body)
            items = json.loads(body["messages"][1]["content"])["items"]
            return {
                "model": "fixture-revision",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "id": i["id"],
                                            "score": 80,
                                            "reason": "evidence",
                                            "evidence_ids": [0],
                                        }
                                        for i in items
                                    ]
                                }
                            )
                        },
                    }
                ],
            }

        body = {
            "messages": [
                {"role": "system", "content": "criteria"},
                {"role": "user", "content": "{}"},
            ],
            "temperature": 0,
        }

        async def request(c, send, *args):
            return await send()

        with (
            patch.object(metering, "completion", completion),
            patch.object(judge, "judge_request", request),
        ):
            results = await asyncio.gather(*(judge_batch.completion(cfg, body) for _ in range(4)))
        assert len(bodies) == 1 and len(results) == 4
        assert bodies[0]["temperature"] == 0
        assert {json.loads(r["choices"][0]["message"]["content"])["id"] for r in results} == {
            0,
            1,
            2,
            3,
        }

    asyncio.run(run())


def test_provider_specific_concurrency_limit():
    async def run():
        cfg = config(provider_limits={"localhost:8000": 1})
        runtime = scheduling.Runtime(cfg, asyncio.Event())
        active = peak = 0

        async def call():
            nonlocal active, peak
            async with runtime.target(cfg.targets[0].url):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        try:
            await asyncio.gather(*(call() for _ in range(6)))
            assert peak == 1
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repeats_make_fresh_calls_then_resume_uses_durable_cache(monkeypatch):
    calls = []

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            calls.append(case["id"])
            return {
                "transcript": [
                    {"input": t, "output": "safe answer", "seconds": 0.01} for t in case["turns"]
                ],
                "error": None,
            }

    async def panel(*args):
        return {"score": 90, "reason": "evidence", "evidence": ["safe answer"]}

    monkeypatch.setattr(studio_engine, "panel", panel)
    monkeypatch.setattr(runner, "summarize", lambda r: {})
    cfg = config(
        repeat_counts={c["category"]: 2 for c in studio_engine.settings_file()["cases"]},
        case_concurrency=8,
        target_concurrency=4,
    )
    run = runner.make_run(cfg)
    asyncio.run(runner.execute(run, cfg, Bot))
    assert run["status"] == "completed"
    assert len(calls) == 34 and len(set(calls)) == 34
    case = run["cases"][0]
    case["results"][0].update(score=None, status="not_tested", reason="Rejudge requested")
    case["completed"] = False
    asyncio.run(runner.execute(run, cfg, Bot))
    assert len(calls) == 34
    assert case["results"][0]["score"] == 90
    assert progress(run)["bots"][0]["categories"]


def test_standard_suite_runtime_regression_budget(monkeypatch):
    """Paired sequential control on same host; >20% beyond parallel baseline fails.

    A fixed I/O workload is dominant, avoiding clock-specific millisecond limits.
    Threshold is configurable in app/studio/benchmark.json, never self-updated.
    """
    from app.config import ROOT

    limits = json.loads((ROOT / "app/studio/benchmark.json").read_text())
    protocol = studio_engine.settings_file()
    cfg = config(
        repeat_counts={c["category"]: 1 for c in protocol["cases"]},
        case_concurrency=4,
        target_concurrency=4,
    )

    async def panel(*args):
        await asyncio.sleep(0.01)
        return {"score": 90, "reason": "evidence", "evidence": ["answer"]}

    class Bot:
        def __init__(self, *args):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            await asyncio.sleep(limits["simulated_bot_seconds"])
            return {
                "transcript": [
                    {"input": t, "output": "answer", "seconds": 0.1} for t in case["turns"]
                ],
                "error": None,
            }

    monkeypatch.setattr(studio_engine, "panel", panel)
    monkeypatch.setattr(runner, "summarize", lambda r: {})
    monkeypatch.setattr(runner, "save", lambda *a: None)
    # Warm-up imports, SQLite schema and the interpreter before timing steady-state work.
    import gc

    asyncio.run(runner.execute(runner.make_run(cfg), cfg, Bot))
    timings = []
    for _ in range(5):
        gc.collect()
        run = runner.make_run(cfg)
        before = time.monotonic()
        asyncio.run(runner.execute(run, cfg, Bot))
        timings.append(time.monotonic() - before)
        assert run["status"] == "completed"
        assert all(c["completed"] for c in run["cases"])
    assert statistics.median(timings) <= limits["baseline_seconds"] * 1.2
