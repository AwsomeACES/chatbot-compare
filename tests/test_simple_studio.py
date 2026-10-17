"""Offline verification of the ten-case protocol and recovery decisions."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.blackbox import judge, studio_engine
from app.blackbox.runner import aggregate, execute, make_run
from app.blackbox.schema import JudgeSelection, Settings, Target


def config(**kwargs):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        judges=[JudgeSelection(model="fixture", local=True)],
        consent=True,
        judge_consent=True,
        **kwargs,
    )


def test_ten_scenarios_and_repeat_counts():
    rows = studio_engine.cases(config(repeat_counts={"bias": 1, "memory": 5}))

    protocol = studio_engine.settings_file()
    scenarios = protocol.get("scenario_sets", {})
    assert len({r["base_case_id"] for r in rows}) == sum(
        len(scenarios.get(c["category"], [c])) for c in protocol["cases"]
    )
    assert len(rows) == sum(
        len(scenarios.get(c["category"], [c]))
        * {"bias": 1, "memory": 5}.get(c["category"], protocol["default_repeats"])
        for c in protocol["cases"]
    )
    assert len({r["id"] for r in rows}) == len(rows)
    with pytest.raises(ValidationError):
        config(repeat_counts={"bias": 0})


def test_missing_is_zero_index_separate_from_quality(monkeypatch):
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    run = make_run(config())
    run["cases"][0]["results"][0].update(status="passed", score=90)
    aggregate(run)
    result = run["studio"]["bots"][0]
    category_score = 90 / studio_engine.settings_file()["default_repeats"]
    assert result["score"] == round(category_score / len(studio_engine.settings_file()["cases"]), 2)
    assert result["categories"][0]["quality"] == 90
    assert result["tested"] == 1
    assert result["categories"][0]["score"] == category_score


def test_winner_and_incomplete_evidence(monkeypatch):
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    cfg = config()
    cfg.targets.append(Target(name="Second", url="http://localhost:8001/chat"))
    run = make_run(cfg)
    for case in run["cases"]:
        case["results"][0].update(status="passed", score=95)
        case["results"][1].update(status="failed", score=40)
    aggregate(run)
    assert run["studio"]["winner"] == 0
    run["cases"][0]["results"][1].update(status="not_tested", score=None)
    aggregate(run)
    assert run["studio"]["winner"] is None


def test_judge_fallback_and_agreement(monkeypatch):
    async def fake(cfg, case, observation):
        if cfg.judge_model == "broken":
            raise ValueError("Provider quota exceeded")
        return {"score": 90, "reason": "Supported", "evidence": ["Answer"]}

    monkeypatch.setattr(judge, "evaluate", fake)
    cfg = config()
    cfg.judges = [
        JudgeSelection(model="broken"),
        JudgeSelection(model="local", local=True, fallback=True),
    ]
    result = asyncio.run(
        studio_engine.panel(cfg, {"id": "test"}, {"transcript": [{"output": "Answer"}]})
    )
    assert result["score"] == 90
    assert result["judges"][0]["model"] == "local"
    assert len(result["judge_failures"]) == 1


def test_secrets_are_not_in_public_run(monkeypatch):
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    cfg = config()
    cfg.judges[0].token = "synthetic-secret"
    # Assign a validated secret, not raw text.
    from pydantic import SecretStr

    cfg.judges[0].token = SecretStr("synthetic-secret")
    run = make_run(cfg)
    assert "token" not in run["config"]["judges"][0]


def test_runner_processes_every_case_after_target_failure(monkeypatch):
    import app.blackbox.runner as runner

    monkeypatch.setattr(runner, "save", lambda *args: None)
    monkeypatch.setattr(runner, "summarize", lambda run: {})
    monkeypatch.setattr(
        studio_engine,
        "panel",
        AsyncMock(return_value={"score": 85, "reason": "Measured", "evidence": ["Answer"]}),
    )

    class BrokenConnector:
        def __init__(self, target, timeout):
            self.kind = "rest"

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            return {"error": "Connection unavailable", "transcript": []}

    cfg = config(repeat_counts={c["category"]: 1 for c in studio_engine.settings_file()["cases"]})
    run = make_run(cfg)
    asyncio.run(execute(run, cfg, connector_factory=BrokenConnector))
    assert all(c["completed"] for c in run["cases"])
    assert all(c["results"][0]["status"] == "not_tested" for c in run["cases"])
    assert run["studio"]["bots"][0]["score"] == 0
    assert run["progress"] == 100


def test_same_model_fallback_is_not_independent_agreement(monkeypatch):
    async def fake(cfg, case, observation):
        if cfg.judge_model != "local":
            raise ValueError("Provider unavailable")
        return {"score": 90, "reason": "Evidence", "evidence": ["Answer"]}

    monkeypatch.setattr(judge, "evaluate", fake)
    cfg = config()
    cfg.judges = [
        JudgeSelection(model="broken-one"),
        JudgeSelection(model="broken-two"),
        JudgeSelection(model="local", local=True, fallback=True),
    ]
    result = asyncio.run(
        studio_engine.panel(cfg, {"id": "test"}, {"transcript": [{"output": "Answer"}]})
    )
    assert result["panel_complete"]
    assert result["agreement"] is None


def test_crashed_simple_run_is_auto_resumed(monkeypatch):
    from fastapi.testclient import TestClient

    import app.blackbox.runner as runner
    from app import blackbox_app
    from app import database as db

    monkeypatch.setattr(runner, "summarize", lambda run: {})
    cfg = config()
    run = make_run(cfg)
    run["status"] = "running"
    run["cases"][0]["results"][0].update(status="passed", score=90)
    db.save("blackbox", run)
    operation = AsyncMock(return_value={"id": run["id"]})
    monkeypatch.setattr(blackbox_app, "resume_run", operation)
    monkeypatch.setenv("STUDIO_AUTO_RESUME", "1")
    with TestClient(blackbox_app.app):
        assert sum(str(call.args[0]) == run["id"] for call in operation.await_args_list) == 1
    assert db.get("blackbox", run["id"])["cases"][0]["results"][0]["score"] == 90
    db.delete("blackbox", run["id"])


def test_evidence_ids_bind_only_literal_offered_excerpts(monkeypatch):
    from app.blackbox.evidence_ids import bind, options

    output = "मैं आपकी मदद कर सकता हूँ।"
    choices = options([output])
    assert bind({"evidence_ids": [0]}, choices)["evidence"] == [output]
    for invalid in ([99], [-1], [True], ["made up"]):
        with pytest.raises(ValueError):
            bind({"evidence_ids": invalid}, choices)
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"score":100,"reason":"Provides help","evidence_ids":[0]}'},
            }
        ]
    }
    monkeypatch.setattr(judge, "judge_request", AsyncMock(return_value=response))
    cfg = config()
    cfg.judge_model = "local"
    result = asyncio.run(judge.ask(cfg, {"transcript": [{"output": output}]}))
    assert result["evidence_matches"][0]["method"] == "exact"


def test_audit_prompt_snapshot_does_not_mutate_after_retry():
    run = {}
    messages = [{"role": "user", "content": "Original prompt"}]
    studio_engine.audit(run, "judge_request", messages=messages)
    messages.append({"role": "user", "content": "Retry reminder"})
    assert len(run["audit"][0]["messages"]) == 1


def test_rotated_keys_remain_redacted_in_saved_reports(monkeypatch):
    import json

    from pydantic import SecretStr

    from app.blackbox import runner

    saved = []
    monkeypatch.setattr(runner, "summarize", lambda run: {})
    monkeypatch.setattr(runner.db, "save", lambda kind, data: saved.append(json.dumps(data)))
    cfg = config()
    cfg.judges[0].token = SecretStr("old-private-password-field-key")
    run = make_run(cfg)
    run["cases"][0]["results"][0]["reason"] = "old-private-password-field-key"
    runner.save(run, cfg)
    cfg.judges[0].token = SecretStr("new-private-password-field-key")
    runner.save(run, cfg)
    assert "old-private-password-field-key" not in saved[-1]
    assert "new-private-password-field-key" not in saved[-1]
