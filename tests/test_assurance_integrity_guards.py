"""Saved evidence cannot be laundered through normal review or retention APIs."""

import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.assurance import service
from app.assurance.combine import combine
from app.assurance.models import Evidence, Finding
from app.blackbox import studio_engine
from app.blackbox.schema import JudgeSelection, Settings, Target

HEADERS = {"X-Studio-Request": "1"}


def finding(**changes) -> Finding:
    fields = {
        "mode": "black",
        "category": "guardrails",
        "test_id": "fixture",
        "verdict": "pass",
        "severity": "Pass",
        "confidence": "Medium",
        "score": 90,
        "evidence": [Evidence(kind="transcript", excerpt="Safe synthetic answer.")],
        "explanation": "Recorded answer supports the result.",
        "checked": "Synthetic check",
        "consequence": "Unsupported conclusions mislead reviewers.",
        "fix": "Inspect the recorded answer.",
    }
    return Finding(**(fields | changes))


def saved_run(**changes) -> dict:
    run = {
        "id": str(uuid.uuid4()),
        "config": {"targets": []},
        "protocol_snapshot": {},
        "modes": ["black"],
        "status": "completed",
        "findings": [finding().model_dump()],
        "planned_checks": [],
        "audit": [],
        "input_hashes": [],
        "uploads_deleted": True,
    } | changes
    service.checkpoint(run)
    return run


def tamper(run: dict, part: str = "findings") -> None:
    if part == "findings":
        run["findings"][0]["score"] = 20
    elif part == "plan":
        run["planned_checks"].append({"test": "unrecorded"})
    else:
        run["audit"][0]["event"] = "rewritten"
    db.save("assurance", run)
    assert service.integrity(run)["valid"] is False


def anchors(ident: str) -> list:
    with db.connect() as connection:
        return connection.execute(
            "SELECT sequence, hash, body FROM audit_chain WHERE run_id=? ORDER BY sequence",
            (ident,),
        ).fetchall()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "post",
            "review",
            {
                "bot": 0,
                "mode": "black",
                "test_id": "fixture",
                "false_positive": True,
                "reason": "Reviewed the exact synthetic evidence.",
            },
        ),
        ("put", "retention", {"days": 5}),
        ("post", "canary-logs", {"bot": 0, "logs": str(uuid.uuid4())}),
    ],
)
@pytest.mark.parametrize("part", ["findings", "plan", "audit"])
def test_tampered_run_cannot_be_resealed_by_mutation(method, path, body, part):
    run = saved_run()
    tamper(run, part)
    before = anchors(run["id"])
    response = TestClient(blackbox_app.app).request(
        method,
        f"/api/assurance/runs/{run['id']}/{path}",
        json=body,
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"]
    assert db.get("assurance", run["id"]) == run
    assert anchors(run["id"]) == before


@pytest.mark.parametrize("corrupt", [False, True])
def test_judge_switch_requires_valid_record_before_changing_config(monkeypatch, corrupt):
    run = saved_run(status="running")
    config = Settings(
        targets=[Target(url="http://localhost/chat")],
        judges=[JudgeSelection(model="original", local=True)],
    )
    monkeypatch.setitem(service.TASKS, run["id"], object())
    monkeypatch.setitem(studio_engine.LIVE_CONFIGS, run["id"], config)
    monkeypatch.setitem(studio_engine.LIVE_RUNS, run["id"], copy.deepcopy(run))
    if corrupt:
        tamper(run)
    before = anchors(run["id"])
    response = TestClient(blackbox_app.app).put(
        f"/api/assurance/runs/{run['id']}/judges",
        json={"consent": True, "judges": [{"model": "replacement", "local": True}]},
        headers=HEADERS,
    )
    if corrupt:
        assert response.status_code == 409
        assert config.judges[0].model == "original"
        assert db.get("assurance", run["id"]) == run
        assert anchors(run["id"]) == before
    else:
        assert response.status_code == 200
        assert config.judges[0].model == "replacement"
        saved = db.get("assurance", run["id"])
        assert saved["config"]["judges"][0]["model"] == "replacement"
        assert service.integrity(saved)["valid"] is True


@pytest.mark.parametrize("corrupt", [False, True])
def test_status_recovery_keeps_corrupt_evidence_readable_without_resealing(corrupt):
    run = saved_run(status="running")
    if corrupt:
        tamper(run)
    before = anchors(run["id"])
    response = TestClient(blackbox_app.app).get(f"/api/assurance/runs/{run['id']}")
    assert response.status_code == 200
    assert response.json()["audit_integrity"]["valid"] is not corrupt
    saved = db.get("assurance", run["id"])
    if corrupt:
        assert saved == run
        assert anchors(run["id"]) == before
    else:
        assert saved["status"] == "interrupted"
        assert len(anchors(run["id"])) > len(before)


def test_expiry_does_not_reseal_corrupt_evidence_but_owner_can_delete_it():
    corrupt = saved_run(uploads_deleted=False, upload_expires_at=0)
    valid = saved_run(uploads_deleted=False, upload_expires_at=0)
    tamper(corrupt)
    before = anchors(corrupt["id"])
    service.expire()
    assert db.get("assurance", corrupt["id"]) == corrupt
    assert anchors(corrupt["id"]) == before
    assert db.get("assurance", valid["id"])["uploads_deleted"] is True
    assert service.integrity(db.get("assurance", valid["id"]))["valid"] is True
    response = TestClient(blackbox_app.app).delete(
        f"/api/assurance/runs/{corrupt['id']}", headers=HEADERS
    )
    assert response.status_code == 200
    assert db.get("assurance", corrupt["id"]) is None


def test_pending_review_blocks_release_until_recorded_review_resolves_it():
    run = saved_run(findings=[finding(review=True).model_dump()])
    assert run["combined"]["verdict"] == "Fix before launch"
    assert run["combined"]["review_queue"] == ["0:black:fixture"]
    response = TestClient(blackbox_app.app).post(
        f"/api/assurance/runs/{run['id']}/review",
        json={
            "bot": 0,
            "mode": "black",
            "test_id": "fixture",
            "false_positive": False,
            "reason": "Checked the uncertainty against the exact transcript.",
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    saved = db.get("assurance", run["id"])
    assert saved["combined"]["verdict"] == "Ready to launch"
    assert saved["combined"]["review_queue"] == []
    assert saved["findings"][0]["original_finding"]["score"] == 90
    assert service.integrity(saved)["valid"] is True


def test_pending_review_does_not_weaken_critical_release_block():
    result = combine([finding(verdict="fail", severity="Critical", score=0)], ["black"])
    assert result["verdict"] == "Do not launch"
