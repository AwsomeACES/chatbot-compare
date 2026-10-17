import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.blackbox import easy_setup as easy
from app.blackbox.schema import Settings, Target
from app.blackbox_app import app


def settings(**kwargs):
    return Settings(targets=[Target(url="http://127.0.0.1:3000")], categories=["bias"], **kwargs)


@pytest.fixture
def discovered(monkeypatch):
    seen = []

    class Connector:
        def __init__(self, target, timeout):
            self.kind = target.kind

        async def detect(self):
            seen.append("detect")
            self.kind = "rest"

        async def close(self):
            pass

    async def request(client, method, url, **kw):
        seen.append(url)
        if url.endswith("/health"):
            return {"service": "reliance-digital-ai"}
        if url.endswith("/products"):
            return [{"id": "P001", "price": 100, "warranty_months": 24}]
        return {"data": [{"id": "fixture-model"}]}

    monkeypatch.setattr(easy, "Connector", Connector)
    monkeypatch.setattr(easy, "request_json", request)
    monkeypatch.setattr(
        easy,
        "judge_defaults",
        lambda: {
            "model": "fixture-judge",
            "url": "http://localhost:1234/v1/chat/completions",
            "key": "synthetic-secret",
        },
    )
    return seen


def test_no_network_without_target_consent(discovered):
    with pytest.raises(ValueError, match="Allow test messages"):
        asyncio.run(easy.prepare(settings()))
    assert discovered == []


def test_judge_and_performance_consent_before_network(discovered):
    with pytest.raises(ValueError, match="Enable the configured AI judge"):
        asyncio.run(easy.prepare(settings(consent=True)))
    cfg = Settings(
        targets=[Target(url="http://localhost:8000")], categories=["performance"], consent=True
    )
    with pytest.raises(ValueError, match="speed-check"):
        asyncio.run(easy.prepare(cfg))
    assert discovered == []


def test_reliance_autofills_fields_and_discloses_reference_source(discovered):
    cfg = settings(consent=True, judge_consent=True)
    result, notes = asyncio.run(easy.prepare(cfg))
    target = result.targets[0]
    assert target.url == "http://127.0.0.1:8000/chat/stream"
    assert target.history_field == "history" and target.response_field == "reply"
    assert target.request_defaults == {"provider": "gemini"}
    assert result.references[0]["reference"]["id"] == "P001"
    assert any("not independently verified" in n for n in notes)
    assert result.judge_token.get_secret_value() == "synthetic-secret"
    assert "synthetic-secret" not in json.dumps(easy.public_defaults())


def test_compare_does_not_invent_shared_references(discovered):
    cfg = settings(consent=True, judge_consent=True)
    cfg.targets.append(Target(url="http://127.0.0.1:3000", name="Other"))
    cfg.categories = ["hallucination"]
    result, notes = asyncio.run(easy.prepare(cfg))
    assert result.references == []
    assert any("reference-free" in n for n in notes)


def test_zip_never_executes_or_connects(discovered):
    cfg = Settings(targets=[Target(kind="zip")], consent=True)
    with pytest.raises(ValueError, match="no isolated runner"):
        asyncio.run(easy.prepare(cfg))
    assert discovered == []


def test_easy_api_reports_actionable_failure(discovered):
    with TestClient(app) as client:
        response = client.post(
            "/api/blackbox/easy-run",
            headers={"X-Studio-Request": "1"},
            json=settings().model_dump(mode="json"),
        )
        assert response.status_code == 422
        assert "Allow test messages" in response.json()["detail"]
        defaults = client.get("/api/blackbox/defaults").json()
        assert defaults["configured"] is True
        assert "synthetic-secret" not in json.dumps(defaults)
