import asyncio
import json
import random

import pytest
from fastapi.testclient import TestClient

from app.blackbox import judge, runner
from app.blackbox.catalog import build_cases
from app.blackbox.runner import ACTIVE, aggregate, execute, make_run
from app.blackbox.schema import Settings, Target
from app.blackbox_app import app

H = {"X-Studio-Request": "1"}


def config(**kw):
    return Settings(targets=[Target(url="http://127.0.0.1:8765/chat")], **kw)


def test_full_catalog_quality_and_coverage():
    r = make_run(config())
    assert len(r["cases"]) == 166
    assert len({c["id"] for c in r["cases"]}) == len(r["cases"])
    assert r["summary"][0]["score"] is None
    assert all(c["not_tested"] == c["total"] for c in r["summary"][0]["categories"])
    r["cases"][0]["results"][0].update(status="passed", score=100)
    aggregate(r)
    assert r["summary"][0]["categories"][0]["score"] == 100
    assert r["summary"][0]["score"] == 100
    assert not r["summary"][0]["rankable"]


def test_retired_categories_rejected():
    with pytest.raises(ValueError):
        config(categories=["static"])
    with pytest.raises(ValueError):
        config(categories=["security"])


class Fixture:
    def __init__(self, target, timeout):
        self.target = target

    async def detect(self):
        pass

    async def close(self):
        pass

    async def conversation(self, case):
        return {
            "transcript": [
                {"input": p, "output": "Fixture reply: " + p, "seconds": 0.25}
                for p in case["turns"]
            ],
            "error": None,
            "usage": [],
        }


async def instant_sleep(*a):
    pass


def test_single_performance_real_measurements(monkeypatch):
    monkeypatch.setattr(runner.asyncio, "sleep", instant_sleep)
    cfg = config(categories=["performance"], consent=True, performance_consent=True)
    r = asyncio.run(execute(make_run(cfg), cfg, Fixture))
    assert r["status"] == "completed"
    assert r["summary"][0]["score"] == 100
    assert all(c["results"][0]["engine"] == "measured-latency" for c in r["cases"])
    assert r["summary"][0]["requests"] == 10
    assert r["summary"][0]["cost"] is None


def test_missing_reference_records_all_cases(monkeypatch):
    cfg = config(categories=["hallucination"], consent=True)
    r = asyncio.run(execute(make_run(cfg), cfg, Fixture))
    assert len(r["cases"]) == 10
    assert all(not c["prerequisite"] for c in r["cases"])
    assert all(
        c["results"][0]["status"] == "not_tested" and "consent" in c["results"][0]["reason"]
        for c in r["cases"]
    )
    assert r["summary"][0]["score"] is None


def test_compare_identical_cases_and_measured_ties(monkeypatch):
    monkeypatch.setattr(runner.asyncio, "sleep", instant_sleep)
    cfg = Settings(
        targets=[
            Target(name="A", url="http://127.0.0.1:8765"),
            Target(name="B", url="http://127.0.0.1:8766"),
        ],
        categories=["performance"],
        consent=True,
        performance_consent=True,
    )
    r = asyncio.run(execute(make_run(cfg), cfg, Fixture))
    assert r["comparison"]["winner"] is None
    assert r["comparison"]["verdict"] == "too_close_to_call"
    assert r["comparison"]["categories"][0]["ties"] == 10
    assert all(
        c["results"][0]["transcript"][0]["input"] == c["results"][1]["transcript"][0]["input"]
        for c in r["cases"]
    )


def test_compare_missing_is_not_tie():
    cfg = Settings(
        targets=[Target(url="http://127.0.0.1:8765"), Target(url="http://127.0.0.1:8766")],
        categories=["hallucination"],
    )
    r = make_run(cfg)
    assert r["comparison"]["winner"] is None
    assert r["comparison"]["categories"][0]["ties"] == 0
    assert r["comparison"]["categories"][0]["not_judged"] == 10


def test_cancelled_records_remaining():
    cfg = config(categories=["performance"], consent=True, performance_consent=True)
    r = make_run(cfg)

    async def go():
        event = asyncio.Event()
        event.set()
        ACTIVE[r["id"]] = event
        return await execute(r, cfg, Fixture)

    r = asyncio.run(go())
    assert r["status"] == "stopped"
    assert all("Run ended" in c["results"][0]["reason"] for c in r["cases"])


def test_pairwise_swap_maps_winner(monkeypatch):
    seen = []

    async def mock(config, payload, pair):
        seen.append(payload)
        return {
            "winner": "A" if payload["A"][0]["output"] == "good" else "B",
            "reason": "grounded",
            "evidence": ["good"],
        }

    monkeypatch.setattr(judge, "ask", mock)
    c = build_cases(config(categories=["bias"]))[0]
    a = {"transcript": [{"output": "good"}]}
    b = {"transcript": [{"output": "poor"}]}
    r = asyncio.run(judge.pairwise(config(), c, a, b, random.Random(42)))
    assert r["winner"] == 0 and r["status"] == "judged"
    assert seen[0]["A"] == seen[1]["B"]


def test_pairwise_position_bias_is_disclosed(monkeypatch):
    async def mock(*a, **kw):
        return {"winner": "A", "reason": "first position", "evidence": ["text"]}

    monkeypatch.setattr(judge, "ask", mock)
    c = build_cases(config(categories=["bias"]))[0]
    r = asyncio.run(
        judge.pairwise(config(), c, {"transcript": []}, {"transcript": []}, random.Random(4))
    )
    assert r["status"] == "order_sensitive" and r["winner"] is None


def test_api_and_zip_validation():
    import io
    import zipfile

    with TestClient(app) as client:
        assert client.get("/api/health").json()["source_execution"] is False
        assert client.post("/api/blackbox/runs", json={}).status_code == 403
        bad = client.post(
            "/api/blackbox/upload", headers=H, files={"file": ("bad.zip", b"not zip")}
        )
        assert bad.status_code == 422
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../escape.py", "print(1)")
        assert (
            client.post(
                "/api/blackbox/upload", headers=H, files={"file": ("bad.zip", archive.getvalue())}
            ).status_code
            == 422
        )
        assert client.post("/api/projects/abc/analyze", headers=H).status_code == 410


def test_pdf_and_json_downloads():
    from app import database as db

    r = make_run(config(categories=["bias"]))
    r["status"] = "completed"
    db.save("blackbox", r)
    with TestClient(app) as client:
        assert (
            client.get(f"/api/blackbox/runs/{r['id']}/download").json()["summary"][0]["score"]
            is None
        )
        pdf = client.get(f"/api/blackbox/runs/{r['id']}/download?format=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


@pytest.fixture
def http_fixture():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/widget":
                body = b"""<!doctype html><textarea></textarea><div id="messages"></div><script>document.querySelector('textarea').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();let p=document.createElement('p');p.className='assistant-message';p.textContent='Fixture answer: '+e.target.value;document.querySelector('#messages').appendChild(p);e.target.value='';}});</script>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(405)
                self.end_headers()

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/broken":
                self.send_response(500)
                self.end_headers()
                return
            if self.path.endswith("/chat/completions"):
                answer = "Fixture answer: " + payload["messages"][-1]["content"]
                data = {"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
            else:
                data = {
                    "reply": "Fixture answer: " + payload["message"],
                    "conversation_id": payload.get("conversation_id"),
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_real_rest_and_openai_transports(http_fixture):
    from app.blackbox.connectors import Connector

    async def go():
        for target in [
            Target(url=http_fixture + "/chat"),
            Target(url=http_fixture + "/v1/chat/completions", model="fixture"),
        ]:
            client = Connector(target, 3)
            try:
                await client.detect()
                result = await client.conversation(
                    {"turns": ["hello", "follow up"], "parallel": False}
                )
                assert not result["error"]
                assert len(result["transcript"]) == 2
                assert result["transcript"][1]["output"] == "Fixture answer: follow up"
            finally:
                await client.close()

    asyncio.run(go())


def test_real_http_error_not_pass(http_fixture):
    from app.blackbox.connectors import Connector

    async def go():
        client = Connector(Target(url=http_fixture + "/broken", kind="rest"), 3)
        try:
            result = await client.conversation({"turns": ["hello"], "parallel": False})
            assert result["error"] == "Target returned HTTP 500."
            assert result["transcript"][0]["output"] is None
        finally:
            await client.close()

    asyncio.run(go())


def test_real_browser_chat_widget(http_fixture):
    from app.blackbox.connectors import Connector

    async def go():
        client = Connector(Target(url=http_fixture + "/widget"), 5)
        try:
            await client.detect()
            assert client.kind == "web"
            result = await client.conversation({"turns": ["hello"], "parallel": False})
            assert result["error"] is None
            assert result["transcript"][0]["output"] == "Fixture answer: hello"
        finally:
            await client.close()

    asyncio.run(go())


def test_judge_rejects_invented_evidence(monkeypatch):
    async def response(*a, **kw):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"score": 100, "reason": "fine", "evidence": ["invented quote"]}
                        )
                    },
                }
            ]
        }

    monkeypatch.setattr(judge.metering, "completion", response)
    cfg = config(judge_model="fixture", judge_consent=True)
    with pytest.raises(ValueError, match="did not match"):
        asyncio.run(judge.ask(cfg, {"transcript": [{"output": "actual reply"}]}))


def test_api_secret_is_not_persisted():
    from app import database as db
    from app.blackbox.runner import save

    cfg = Settings(
        targets=[Target(url="http://127.0.0.1:8765", token="synthetic-test-token")],
        categories=["bias"],
        judge_token="synthetic-judge-token",
    )
    r = make_run(cfg)
    r["cases"][0]["results"][0]["transcript"] = [
        {"input": "hello", "output": "synthetic-test-token"}
    ]
    save(r, cfg)
    encoded = json.dumps(db.get("blackbox", r["id"]))
    assert "synthetic-test-token" not in encoded and "synthetic-judge-token" not in encoded
    assert "[REDACTED]" in encoded


def test_reliance_sse_contract():
    from app.blackbox.connectors import parse_chat_stream

    good = (
        'event: meta\ndata: {"provider":"gemini"}\n\nevent: token\ndata: '
        '{"text":"hello"}\n\nevent: done\ndata: '
        '{"ok":true}\n\n'
    )
    assert parse_chat_stream(good)["reply"] == "hello"
    assert parse_chat_stream(good)["stream_metadata"]["provider"] == "gemini"
    with pytest.raises(ValueError, match="stream error"):
        parse_chat_stream(
            'event: error\ndata: {"message":"temporarily unavailable"}\n\nevent: done\ndata: {"ok":false}\n\n'
        )
    with pytest.raises(ValueError, match="completion"):
        parse_chat_stream('event: token\ndata: {"text":"partial"}\n\n')


def test_resume_keeps_successful_case_without_reexecution(monkeypatch):
    monkeypatch.setattr(runner.asyncio, "sleep", instant_sleep)
    cfg = config(categories=["performance"], consent=True, performance_consent=True)
    r = make_run(cfg)
    r["cases"][0].update(completed=True)
    r["cases"][0]["results"][0].update(status="passed", score=90, reason="Original measured result")
    calls = []

    class CountingFixture(Fixture):
        async def conversation(self, case):
            calls.append(case["id"])
            return await super().conversation(case)

    r = asyncio.run(execute(r, cfg, CountingFixture))
    assert len(calls) == 9
    assert "performance-001" not in calls
    assert r["cases"][0]["results"][0]["score"] == 90
    assert r["progress"] == 100


def test_reliability_counts_previous_failed_attempts():
    cfg = config(categories=["performance"])
    r = make_run(cfg)
    c = r["cases"][0]
    c["results"][0].update(
        status="passed",
        score=100,
        transcript=[{"input": "hello", "output": "answer", "seconds": 1}],
    )
    c["previous_attempts"] = [
        {
            "results": [
                {
                    "transcript": [
                        {
                            "input": "hello",
                            "output": None,
                            "seconds": 2,
                            "error": "Request timed out.",
                        }
                    ]
                }
            ]
        }
    ]
    aggregate(r)
    assert r["summary"][0]["requests"] == 2
    assert r["summary"][0]["errors"] == 1
    assert r["summary"][0]["timeouts"] == 1
    assert r["summary"][0]["error_rate"] == 50
    assert r["summary"][0]["categories"][0]["score"] == 100
