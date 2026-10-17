"""Partial API conversations retain successful turns and session identity."""

import asyncio
import uuid

import httpx
from test_bias_governance import config

from app.blackbox import connectors, metering
from app.blackbox.execution_cache import observation_key, read
from app.blackbox.schema import Target


def test_partial_rest_retry_reuses_prefix_and_same_session(monkeypatch):
    calls = []
    failed = False

    async def request(client, method, url, **kwargs):
        nonlocal failed
        body = kwargs["json"]
        calls.append(body)
        if body["message"] == "Second turn" and not failed:
            failed = True
            raise httpx.ReadTimeout("fixture timeout")
        return {
            "answer": "Answer to " + body["message"],
            "conversation_id": "fixture-session",
            "usage": {},
        }

    async def unmetered(operation, **kwargs):
        return await operation()

    monkeypatch.setattr(connectors, "request_json", request)
    monkeypatch.setattr(metering, "call", unmetered)
    cfg = config()
    cfg.targets = [Target(url="http://localhost:8000/chat", kind="rest", history_field="history")]
    case = {
        "id": "memory-repeat-1",
        "repeat": 1,
        "category": "memory",
        "parallel": False,
        "turns": ["First turn", "Second turn"],
    }
    ident = str(uuid.uuid4())

    async def run():
        connector = connectors.Connector(cfg.targets[0], 10)
        with metering.scope(ident, "single", cfg, bot_slot="A"):
            first = await connector.http_conversation(case, object())
            assert first["error"]
            cached = read(ident, "bot", observation_key(cfg, 0, case))
            assert len(cached["transcript"]) == 1 and cached["session_id"] == "fixture-session"
            second = await connector.http_conversation(
                {**case, "resume_observation": cached}, object()
            )
            assert second["error"] is None and len(second["transcript"]) == 2

    asyncio.run(run())
    assert [c["message"] for c in calls] == ["First turn", "Second turn", "Second turn"]
    assert calls[-1]["conversation_id"] == "fixture-session"
    assert calls[-1]["history"] == [
        {"role": "user", "content": "First turn"},
        {"role": "assistant", "content": "Answer to First turn"},
    ]
