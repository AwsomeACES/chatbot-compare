"""Offline contracts for bias, governance, privacy and exact reproduction."""

import copy
import json
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.blackbox import bias, governance, studio_engine
from app.blackbox.execution_cache import bot_key, read, write
from app.blackbox.runner import aggregate, make_run, save
from app.blackbox.schema import Settings, Target


def config(**values):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        judges=[{"model": "fixture", "local": True}],
        consent=True,
        judge_consent=True,
        **values,
    )


def run_fixture():
    cfg = config(repeat_counts={c["category"]: 1 for c in studio_engine.settings_file()["cases"]})
    run = make_run(cfg)
    for case in run["cases"]:
        case["completed"] = True
        case["results"][0].update(
            status="passed",
            score=90,
            reason="Equivalent useful responses",
            transcript=[
                {"input": t, "output": "I can help you.", "seconds": 0.01} for t in case["turns"]
            ],
        )
    aggregate(run)
    return cfg, run


def test_bias_pair_templates_change_only_one_slot():
    from app.config import ROOT

    data = json.loads((ROOT / "app/studio/bias-v1.json").read_text(encoding="utf-8"))
    assert len(data["cases"]) == 9
    assert {s["bias_subtype"] for s in data["cases"]} == bias.COUNTERFACTUAL | {
        "cognitive",
        "media",
        "selection",
        "algorithmic",
    }
    for row in data["cases"][:5]:
        assert row["turns"] == [row["pair_template"].format(attribute=v) for v in row["attributes"]]
        assert row["parallel"]


def test_randomization_is_repeatable_and_does_not_mutate_evidence():
    observation = {
        "transcript": [{"input": "one", "output": "one"}, {"input": "two", "output": "two"}]
    }
    orders = set()
    for seed in range(20):
        case = {"id": "pair", "bias_subtype": "gender"}
        result = bias.ordered_observation(case, observation, seed, "model")
        assert result == bias.ordered_observation(case, observation, seed, "model")
        orders.add(tuple(result["pair_order"]))
    assert len(orders) == 2
    assert observation["transcript"][0]["input"] == "one"


def test_signals_are_descriptive_and_do_not_claim_discrimination():
    result = bias.signals(
        {
            "transcript": [
                {"output": "I cannot help."},
                {"output": "Happy to help. Please reset your router."},
            ]
        }
    )
    assert result["refusal_gap"] == 1 and result["length_gap"] > 0
    assert "standalone" not in result or not result["standalone"]
    assert "judge" in result["limitation"]


def test_algorithmic_aggregate_is_not_a_ninth_weight():
    _, run = run_fixture()
    for c in run["cases"]:
        if c.get("bias_subtype") == "gender":
            c["results"][0]["score"] = 10
    studio_engine.summarize(run)
    bot = run["studio"]["bots"][0]
    group = next(g for g in bot["categories"] if g["id"] == "bias")
    assert group["score"] == 80  # (10 + 7*90) / 8; derived is excluded.
    algorithmic = next(c for c in run["cases"] if c.get("derived"))
    assert algorithmic["results"][0]["score"] == 74
    assert len(bot["bias_subtests"]) == 9
    assert bot["planned"] == 17


def test_missing_pair_prevents_derived_disparity():
    _, run = run_fixture()
    case = next(c for c in run["cases"] if c.get("bias_subtype") == "age")
    case["results"][0].update(score=None, status="not_tested", reason="Provider timeout")
    bias.derive_algorithmic(run)
    row = next(c for c in run["cases"] if c.get("derived"))["results"][0]
    assert row["score"] is None and row["status"] == "not_tested"


def test_hash_chain_detects_edit_and_tail_truncation():
    run = {"id": str(uuid.uuid4()), "config": {}, "audit": []}
    governance.append(run, "start", config={"judge": "fixture"})
    governance.append(run, "retry", reason="timeout")
    assert governance.verify(run)["valid"] is True
    changed = copy.deepcopy(run)
    changed["audit"][0]["event"] = "forged"
    assert governance.verify(changed)["valid"] is False
    changed = copy.deepcopy(run)
    changed["audit"].pop()
    assert governance.verify(changed)["valid"] is False


def test_cached_repeats_are_distinct_and_scoped_to_run():
    bot = {"url": "http://localhost/chat"}
    one = {"id": "case-repeat-1", "repeat": 1, "turns": ["same"]}
    two = {**one, "id": "case-repeat-2", "repeat": 2}
    assert bot_key(bot, one) != bot_key(bot, two)
    ident = str(uuid.uuid4())
    write(ident, "bot", bot_key(bot, one), {"output": "fresh1"})
    assert read(ident, "bot", bot_key(bot, two)) is None
    assert read("new-run", "bot", bot_key(bot, one)) is None
    assert read(ident, "bot", bot_key(bot, one))["output"] == "fresh1"
    assert bot_key(bot, {**one, "turns": ["changed"]}) != bot_key(bot, one)


def test_override_is_logged_and_export_redacts_without_changing_source():
    cfg, run = run_fixture()
    case = run["cases"][0]
    case["results"][0]["transcript"][0]["output"] = "Contact person@example.com or +91 98765 43210"
    save(run, cfg)
    response = TestClient(blackbox_app.app).post(
        f"/api/studio/runs/{run['id']}/override",
        headers={"X-Studio-Request": "1"},
        json={
            "case_id": case["id"],
            "bot": 0,
            "score": 40,
            "note": "Expert review: incorrect answer",
        },
    )
    assert response.status_code == 200
    stored = db.get("blackbox", run["id"])
    row = stored["cases"][0]["results"][0]
    assert row["overridden"] and row["original_verdict"]["score"] == 90
    event = stored["audit"][-1]
    assert event["previous_score"] == 90 and event["score"] == 40
    assert governance.verify(stored)["valid"]
    exported = governance.export_run(stored)
    assert "person@example.com" not in json.dumps(exported)
    assert "person@example.com" in json.dumps(stored)
    assert exported["governance"]["run_integrity"]["overrides"] == 1


def test_reproduce_preserves_protocol_prices_and_seed():
    cfg, run = run_fixture()
    save(run, cfg)
    captured = []

    async def start(reproduction):
        captured.append(reproduction)
        return {"id": "new"}

    with patch("app.blackbox_app.start", start):
        response = TestClient(blackbox_app.app).post(
            f"/api/studio/runs/{run['id']}/reproduce", headers={"X-Studio-Request": "1"}, json={}
        )
    assert response.status_code == 200
    reproduced = captured[0]
    assert reproduced._protocol_override == run["protocol_snapshot"]
    assert reproduced.price_snapshot_id == cfg.price_snapshot_id
    assert reproduced.seed == cfg.seed
    assert reproduced._reproduced_from == run["id"]


def test_governance_page_and_retention_cleanup():
    cfg, run = run_fixture()
    run.update(status="completed", finished_at="2020-01-01T00:00:00+00:00")
    run["config"]["retention_days"] = 1
    governance.append(run, "completed")
    save(run, cfg)
    write(run["id"], "bot", "test", {"text": "private"})
    client = TestClient(blackbox_app.app)
    assert "governance-redirect.js" in client.get("/governance.html").text
    assert 'id="governance"' in client.get("/").text
    assert governance.expire_runs({run["id"]}) == 0
    governance.expire_runs(set())
    assert db.get("blackbox", run["id"]) is None
    assert read(run["id"], "bot", "test") is None
