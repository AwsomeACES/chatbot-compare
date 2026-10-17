import asyncio
import uuid

from fastapi.testclient import TestClient

from app import blackbox_app
from app.blackbox import studio_engine


def test_simple_settings_and_screen():
    client = TestClient(blackbox_app.app)
    response = client.get("/api/studio/settings")
    assert response.status_code == 200
    assert len(response.json()["cases"]) == len(studio_engine.settings_file()["cases"])
    assert "How well does your bot help people?" in client.get("/").text


def test_live_change_records_models_without_keys():
    from test_simple_studio import config

    ident = str(uuid.uuid4())
    cfg = config()
    run = {"id": ident, "audit": [], "config": {}, "cases": []}
    studio_engine.LIVE_CONFIGS[ident] = cfg
    studio_engine.LIVE_RUNS[ident] = run
    from unittest.mock import patch

    try:
        with patch("app.blackbox.runner.save"):
            response = TestClient(blackbox_app.app).put(
                "/api/studio/runs/" + ident + "/judges",
                headers={"X-Studio-Request": "1"},
                json={
                    "judges": [{"model": "new", "token": "synthetic-secret", "local": True}],
                    "consent": True,
                },
            )
        assert response.status_code == 200
        assert cfg.judges[0].model == "new"
        assert "token" not in run["config"]["judges"][0]
        assert run["audit"][0]["event"] == "judges_changed"
    finally:
        studio_engine.LIVE_CONFIGS.pop(ident, None)
        studio_engine.LIVE_RUNS.pop(ident, None)


def test_fallback_registers_new_host_during_runtime():
    from test_simple_studio import config

    from app.blackbox.scheduling import Runtime, judge_call, key

    async def check():
        cfg = config()
        runtime = Runtime(cfg, asyncio.Event())
        second = cfg.model_copy(deep=True)
        second.judge_url = "http://localhost:11434/v1/chat/completions"
        try:
            with runtime.context():
                async with judge_call(second):
                    assert key(second.judge_url) in runtime.shared.judges
        finally:
            await runtime.close()

    asyncio.run(check())


def test_human_override_needs_real_answer_and_preserves_verdict(monkeypatch):
    from test_simple_studio import config

    from app import database as db
    from app.blackbox.runner import make_run

    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    run = make_run(config())
    case = run["cases"][0]
    db.save("blackbox", run)
    client = TestClient(blackbox_app.app)
    url = "/api/studio/runs/" + run["id"] + "/override"
    payload = {
        "case_id": case["id"],
        "bot": 0,
        "score": 95,
        "note": "Verified reference supports answer.",
    }
    assert client.post(url, json=payload, headers={"X-Studio-Request": "1"}).status_code == 422
    case["results"][0].update(
        status="failed",
        score=40,
        transcript=[{"input": "Q", "output": "Real answer", "seconds": 1}],
    )
    db.save("blackbox", run)
    assert client.post(url, json=payload, headers={"X-Studio-Request": "1"}).status_code == 200
    saved = db.get("blackbox", run["id"])
    result = saved["cases"][0]["results"][0]
    assert result["original_verdict"]["score"] == 40 and result["score"] == 95
    assert saved["audit"][-1]["event"] == "human_override"


def test_docker_gateway_access_is_explicit_and_metadata_stays_blocked(monkeypatch):
    import socket

    from app.blackbox.connectors import validate_destination

    address = "172.17.0.1"
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(2, 1, 6, "", (address, 11434))])
    monkeypatch.delenv("STUDIO_DOCKER_HOST_ACCESS", raising=False)
    import pytest

    with pytest.raises(ValueError):
        asyncio.run(validate_destination("http://host.docker.internal:11434/v1/models"))
    monkeypatch.setenv("STUDIO_DOCKER_HOST_ACCESS", "1")
    asyncio.run(validate_destination("http://host.docker.internal:11434/v1/models"))
    with pytest.raises(ValueError):
        asyncio.run(validate_destination("http://172.17.0.1/v1/models"))
    address = "169.254.169.254"
    with pytest.raises(ValueError):
        asyncio.run(validate_destination("http://host.docker.internal/v1/models"))
