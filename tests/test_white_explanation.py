"""White AI explanation service: mocked providers only, verdicts never change."""

import copy
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.assurance import explain, service
from app.assurance.models import Evidence, Finding, missing
from app.blackbox import governance, metering
from app.blackbox.quota import ProviderQuotaUnavailable

HEADERS = {"X-Studio-Request": "1"}
LOCAL = {"model": "local-fixture", "local": True}
CLOUD = {"model": "cloud-fixture", "url": "https://judge.example.org/v1/chat/completions"}


def saved_run() -> dict:
    flagged = Finding(
        mode="white",
        category="code_security",
        test_id="hardcoded_secrets",
        verdict="fail",
        severity="Critical",
        evidence=[Evidence(kind="code", file="providers.py", line=5, excerpt="api_model = 'x-1'")],
        explanation="6 scanner findings in this rule set.",
        checked="hardcoded secrets",
        consequence="c",
        fix="f",
        tool="gitleaks",
    )
    gap = missing("white", 0, "pii", "retention", "No matching control evidence found.")
    run = {
        "id": str(uuid.uuid4()),
        "config": {"targets": [{"name": "Fixture bot", "url": "http://localhost:9/chat"}]},
        "protocol_snapshot": {},
        "modes": ["white"],
        "status": "completed",
        "findings": [flagged.model_dump(), gap.model_dump()],
        "audit": [],
        "input_hashes": [],
    }
    governance.append(run, "start")
    service.checkpoint(run)
    return run


def reply(checks: list[dict], summary: str = "Two checks explained.") -> dict:
    content = json.dumps({"summary": summary, "checks": checks})
    return {
        "model": "provider-reported-model",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


GOOD = [
    {
        "test_id": "hardcoded_secrets",
        "assessment": "likely_false_positive",
        "explanation": "The match assigns a model name.",
        "fix": "Review the line.",
        "quotes": ["api_model = 'x-1'"],
    },
    {
        "test_id": "retention",
        "assessment": "not_verified",
        "explanation": "No expiry evidence <b>was</b> supplied.",
        "fix": "Add a TTL and test it.",
        "quotes": ["No matching control evidence found."],
    },
]


def post(client, run, body):
    return client.post(f"/api/assurance/runs/{run['id']}/explain", json=body, headers=HEADERS)


def test_accepted_explanation_is_grounded_metered_and_leaves_findings(monkeypatch):
    run = saved_run()
    before = copy.deepcopy(db.get("assurance", run["id"])["findings"])
    completion = AsyncMock(return_value=reply(GOOD))
    monkeypatch.setattr(metering, "completion", completion)
    result = post(TestClient(blackbox_app.app), run, {"judges": [LOCAL]}).json()
    assert result["status"] == "accepted" and result["model"] == "local-fixture"
    assert result["provider_model"] == "provider-reported-model"
    assert {c["test_id"] for c in result["checks"]} == {"hardcoded_secrets", "retention"}
    saved = db.get("assurance", run["id"])
    assert saved["findings"] == before
    assert saved["ai_explanations"][-1]["status"] == "accepted"
    assert any(e["event"] == "ai_explanation" for e in saved["audit"])
    assert service.integrity(saved)["valid"] is True
    usage = [e for e in metering.events(run["id"]) if e["role"] == "judge"]
    assert len(usage) == 1 and usage[0]["input_tokens"] == 100
    exported = service.export(saved)
    rows = {r["test_id"]: r for r in exported["evidence_status"]["checks"]}
    assert rows["hardcoded_secrets"]["verdict"] == "fail"
    assert "Automated AI explanation" in rows["hardcoded_secrets"]["supplemental_review"]["source"]
    sent = json.loads(completion.await_args.args[1]["messages"][1]["content"])
    assert {c["test_id"] for c in sent["checks"]} == {"hardcoded_secrets", "retention"}


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"summary": "x", "checks": GOOD[:1]}),
        json.dumps({"summary": "x", "checks": [*GOOD, {**GOOD[0], "test_id": "invented"}]}),
        json.dumps(
            {"summary": "x", "checks": [{**GOOD[0], "quotes": ["an invented quote"]}, GOOD[1]]}
        ),
        json.dumps({"summary": "x", "checks": [{**GOOD[0], "assessment": "pass"}, GOOD[1]]}),
    ],
)
def test_invalid_output_is_rejected_and_retained(bad):
    with pytest.raises(ValueError):
        explain.validate(bad, explain.payload(saved_run()))


def test_parse_failure_falls_back_to_next_permitted_judge(monkeypatch):
    run = saved_run()
    broken = {"choices": [{"finish_reason": "stop", "message": {"content": "{oops"}}]}
    monkeypatch.setattr(metering, "completion", AsyncMock(side_effect=[broken, reply(GOOD)]))
    body = {"judges": [LOCAL, {**LOCAL, "model": "local-two", "fallback": True}]}
    result = post(TestClient(blackbox_app.app), run, body).json()
    assert [a["status"] for a in result["attempts"]] == ["rejected", "accepted"]
    assert result["attempts"][0]["raw_excerpt"] == "{oops"
    assert result["model"] == "local-two"


def test_cloud_judge_needs_consent_and_quota_is_recorded(monkeypatch):
    run = saved_run()
    completion = AsyncMock(return_value=reply(GOOD))
    monkeypatch.setattr(metering, "completion", completion)
    monkeypatch.setattr(explain, "local_fallbacks", AsyncMock(return_value=[]))
    client = TestClient(blackbox_app.app)
    result = post(client, run, {"judges": [CLOUD]}).json()
    assert result["status"] == "failed" and "No permitted judge" in result["reason"]
    assert completion.await_count == 0
    monkeypatch.setattr(
        metering, "completion", AsyncMock(side_effect=ProviderQuotaUnavailable("quota"))
    )
    result = post(client, run, {"judges": [CLOUD], "cloud_consent": True}).json()
    assert result["status"] == "failed"
    assert result["attempts"][0]["reason"] == "Provider quota or billing unavailable."
    saved = db.get("assurance", run["id"])
    assert [e["status"] for e in saved["ai_explanations"]] == ["failed", "failed"]
    assert any(e.get("cloud_consent") for e in saved["audit"] if e["event"] == "ai_explanation")
