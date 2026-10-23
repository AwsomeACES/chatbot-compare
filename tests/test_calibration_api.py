"""Calibration API: validation, conflicts, persistence-before-dispatch, privacy and deletion."""

import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_judge_calibration import (
    CLOUD,
    LOCAL,
    Provider,
    clean_state,  # noqa: F401 - autouse isolation fixture
    labeled_set,
    make_run,
)

from app import blackbox_app
from app import database as db
from app.blackbox import judge_calibration as cal
from app.blackbox import metering
from app.blackbox.calibration_models import KIND_EVALUATION, KIND_SET

H = {"x-studio-request": "1"}
BASE = "/api/studio/judge-calibration"


@pytest.fixture
def client():
    return TestClient(blackbox_app.app)


def create(client, run, size=12):
    response = client.post(
        f"{BASE}/sets",
        headers=H,
        json={
            "name": "API set",
            "selection": {
                "source": {"kind": "blackbox_run", "id": run["id"]},
                "sample": {"size": size, "seed": 5},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["set"]["id"]


def test_validation_and_not_found_errors_are_clear(client):
    assert client.get(f"{BASE}/sets/not-a-uuid").status_code == 422
    assert client.get(f"{BASE}/sets/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{BASE}/sources/filesystem/{uuid.uuid4()}/items").status_code == 404
    assert client.get(f"{BASE}/sources/blackbox_run/{uuid.uuid4()}/items").status_code == 404
    body = {
        "name": "x",
        "selection": {
            "source": {"kind": "blackbox_run", "id": "../../etc/passwd"},
            "sample": {"size": 1},
        },
    }
    assert client.post(f"{BASE}/sets", headers=H, json=body).status_code == 422
    both = {
        "source": {"kind": "blackbox_run", "id": str(uuid.uuid4())},
        "sample": {"size": 1},
        "items": [{"case_id": "a", "bot_slot": 0}],
    }
    assert (
        client.post(f"{BASE}/sets", headers=H, json={"name": "x", "selection": both}).status_code
        == 422
    )
    assert client.post(f"{BASE}/sets", json=body).status_code == 403  # Studio header required


def test_selection_labels_conflicts_and_freeze(client):
    run = make_run(scenarios=4, slots=2)
    listing = client.get(f"{BASE}/sources/blackbox_run/{run['id']}/items").json()
    assert len(listing["eligible"]) == 8 and "ORIGINAL JUDGE REASON" not in str(listing)
    ident = create(client, run, size=3)
    detail = client.get(f"{BASE}/sets/{ident}").json()
    assert detail["items"] == 3 and detail["blinding"]["prior_exposure_possible"] is True
    assert all(i["label"] is None for i in detail["items_detail"])
    item = detail["items_detail"][0]["id"]
    url = f"{BASE}/sets/{ident}/items/{item}/label"
    assert (
        client.put(url, headers=H, json={"expected_revision": 0, "score": True}).status_code == 422
    )
    assert client.put(url, headers=H, json={"expected_revision": 0, "score": 80}).status_code == 200
    stale = client.put(url, headers=H, json={"expected_revision": 0, "verdict": "fail"})
    assert stale.status_code == 409 and "stale" in stale.json()["detail"]
    assert (
        client.put(url, headers=H, json={"expected_revision": 1, "verdict": "fail"}).status_code
        == 422
    )
    revision = client.get(f"{BASE}/sets/{ident}").json()["revision"]
    assert (
        client.post(
            f"{BASE}/sets/{ident}/freeze", headers=H, json={"expected_set_revision": revision + 5}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{BASE}/sets/{ident}/freeze", headers=H, json={"expected_set_revision": revision}
        ).status_code
        == 200
    )
    removed = client.delete(f"{BASE}/sets/{ident}/items/{item}?expected_set_revision=0", headers=H)
    assert removed.status_code == 409


def test_evaluation_is_persisted_before_dispatch_and_cloud_needs_consent(client):
    run = make_run(scenarios=3)
    record, _ = labeled_set(run)
    version = record["versions"][0]
    cloud = {"model": "m", "url": CLOUD, "local": False}
    missing = client.post(
        f"{BASE}/sets/{record['id']}/evaluations", headers=H, json={"version": 1, "judge": cloud}
    )
    assert missing.status_code == 422 and "consent" in missing.json()["detail"]
    assert db.all_records(KIND_EVALUATION) == []
    local = {"model": "m", "url": LOCAL, "local": True}
    with patch.object(cal, "launch") as launch, patch.object(metering, "completion") as provider:
        ok = client.post(
            f"{BASE}/sets/{record['id']}/evaluations",
            headers=H,
            json={"version": 1, "judge": local},
        )
    assert ok.status_code == 202
    stored = db.get(KIND_EVALUATION, ok.json()["id"])
    assert stored["status"] == "queued" and stored["set_version_hash"] == version["hash"]
    assert launch.called and not provider.called
    duplicate = client.post(
        f"{BASE}/sets/{record['id']}/evaluations", headers=H, json={"version": 1, "judge": local}
    )
    assert duplicate.status_code == 409 and "resume" in duplicate.json()["detail"]
    assert (
        client.post(
            f"{BASE}/sets/{record['id']}/evaluations",
            headers=H,
            json={"version": 9, "judge": local},
        ).status_code
        == 404
    )


def wait_for(client, ident, states=("completed", "cancelled", "interrupted")):
    for _ in range(200):
        body = client.get(f"{BASE}/evaluations/{ident}").json()
        if body["status"] in states:
            return body
        time.sleep(0.1)
    raise AssertionError("evaluation did not finish")


def test_http_evaluation_progress_results_export_and_deletion(client):
    run = make_run(scenarios=12)
    record, _ = labeled_set(run, labels=[i % 2 == 0 for i in range(12)])
    provider = Provider(flip=("answer 2 ",))
    with TestClient(blackbox_app.app) as live, patch.object(metering, "completion", provider):
        started = live.post(
            f"{BASE}/sets/{record['id']}/evaluations",
            headers=H,
            json={"version": 1, "judge": {"model": "judge-a", "url": LOCAL, "local": True}},
        )
        assert started.status_code == 202
        ident = started.json()["id"]
        body = wait_for(live, ident)
    assert body["status"] == "completed" and body["summary"]["agreement"]["percent"] == 91.67
    assert len(body["disagreements"]) == 1
    listing = client.get(f"{BASE}/evaluations?set_id={record['id']}").json()
    assert listing[0]["id"] == ident and "results" not in listing[0]
    compat = client.post(
        f"{BASE}/compatibility", headers=H, json={"model": "judge-a", "url": LOCAL}
    ).json()
    assert compat["state"] == "meets" and compat["model_to_model_note"]
    other = client.post(
        f"{BASE}/compatibility", headers=H, json={"model": "judge-z", "url": LOCAL}
    ).json()
    assert other["state"] == "stale" and other["warnings"]
    exported = client.get(f"{BASE}/evaluations/{ident}/export")
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    assert exported.json()["limitations"]
    assert client.post(f"{BASE}/evaluations/{ident}/resume", headers=H, json={}).status_code == 409
    assert client.post(f"{BASE}/evaluations/{ident}/cancel", headers=H).status_code == 409
    assert client.delete(f"{BASE}/evaluations/{ident}", headers=H).status_code == 200
    assert client.get(f"{BASE}/evaluations/{ident}").status_code == 404
    assert client.delete(f"{BASE}/sets/{record['id']}", headers=H).status_code == 200
    assert db.get(KIND_SET, record["id"]) is None


def test_run_deletion_removes_copied_evidence_and_invalidates_calibration(client):
    run = make_run(scenarios=4)
    record, _ = labeled_set(run)
    assert client.delete(f"/api/blackbox/runs/{run['id']}").status_code in (200, 403)
    response = client.delete(f"/api/blackbox/runs/{run['id']}", headers=H)
    assert response.status_code in (200, 404)
    stored = str(db.get(KIND_SET, record["id"]))
    assert "GOOD answer" not in stored and "HUMAN RATIONALE" not in stored
    assert db.get(KIND_SET, record["id"])["invalidated"]
    resumed = client.get(f"{BASE}/sets/{record['id']}").json()
    assert resumed["invalidated"] and all(v["purged"] for v in resumed["versions"])


def test_assessment_deletion_removes_dependent_calibration(client):
    run = make_run(scenarios=4)
    assessment = {
        "id": str(uuid.uuid4()),
        "blackbox_run_id": run["id"],
        "status": "completed",
        "modes": ["black"],
        "audit": [],
    }
    db.save("assurance", assessment)
    response = client.post(
        f"{BASE}/sets",
        headers=H,
        json={
            "name": "via assessment",
            "selection": {
                "source": {"kind": "assurance_assessment", "id": assessment["id"]},
                "sample": {"size": 4},
            },
        },
    )
    assert response.status_code == 201
    ident = response.json()["set"]["id"]
    assert cal.purge_source(assessment_id=assessment["id"]) == 1
    assert db.get(KIND_SET, ident)["invalidated"]
    assert str(db.get(KIND_SET, ident)["draft"]["items"][0]["payload"]["transcript"]) == "[]"
