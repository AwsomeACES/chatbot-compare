"""Transcript-only calibration intake never invents scores or repeats completed calls."""

import asyncio
import copy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.blackbox import runner
from app.blackbox.catalog import build_cases
from app.blackbox.schema import ImportedCase, Settings, Target


def config(**kwargs):
    return Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat", kind="rest")],
        categories=["memory"],
        custom_cases=[
            ImportedCase(category="memory", name="Remember", turns=["Q"], expected="Recall")
        ],
        judge_enabled=False,
        ownership_confirmed=True,
        consent=True,
        **kwargs,
    )


def test_collection_plans_without_judge_but_rejects_mixed_mode():
    assert build_cases(config())[0]["prerequisite"]
    assert not build_cases(config(collect_only=True))[0]["prerequisite"]
    with pytest.raises(ValueError):
        config(collect_only=True, simple_mode=True)
    with pytest.raises(ValueError):
        Settings(targets=[Target(url="http://localhost/chat")], collect_only=True)


def test_collection_and_exact_resume_never_judge_or_replay(monkeypatch):
    cfg = config(collect_only=True)
    run = runner.make_run(cfg)
    case = run["cases"][0]
    calls = []

    class Connector:
        def __init__(self, *args):
            pass

        async def conversation(self, item):
            calls.append(item["id"])
            return {
                "transcript": [{"input": "Q", "output": "Answer", "seconds": 0.1}],
                "error": None,
            }

    mock_judge = AsyncMock(side_effect=AssertionError("No Judge during collection"))
    monkeypatch.setattr(runner, "evaluate", mock_judge)

    async def check():
        executor = runner.EvaluationExecutor(run, cfg, Connector)
        try:
            with executor.runtime.context():
                await executor.target_result(case, 0)
                original = copy.deepcopy(case["results"][0])
                await executor.target_result(case, 0)
                assert case["results"][0] == original
                case["results"][0].update(status="passed", score=100)
                original = copy.deepcopy(case["results"][0])
                await executor.target_result(case, 0)
                assert case["results"][0] == original
        finally:
            await executor.runtime.close()
            runner.ACTIVE.pop(run["id"], None)

    asyncio.run(check())
    assert len(calls) == 1
    mock_judge.assert_not_called()


def test_resume_enables_collection_preserving_scored_result(monkeypatch):
    cfg = config()
    run = runner.make_run(cfg)
    second = copy.deepcopy(run["cases"][0])
    second["id"] = "memory-002"
    second["completed"] = True
    second["results"][0].update(
        status="passed", score=100, transcript=[{"input": "Q", "output": "Recorded", "seconds": 1}]
    )
    original = copy.deepcopy(second["results"][0])
    run["cases"].append(second)
    run["status"] = "completed"
    db.save("blackbox", run)
    monkeypatch.setattr(blackbox_app, "execute", AsyncMock())
    payload = cfg.model_dump(mode="json")
    payload["collect_only"] = True
    try:
        response = TestClient(blackbox_app.app).post(
            "/api/blackbox/runs/" + run["id"] + "/resume",
            headers={"x-studio-request": "1"},
            json=payload,
        )
        assert response.status_code == 200, response.text
        saved = db.get("blackbox", run["id"])
        assert not saved["cases"][0]["prerequisite"]
        assert saved["cases"][1]["results"][0] == original
        assert response.json()["pending_cases"] == 1
        assert saved["config"]["collect_only"] is True
    finally:
        runner.ACTIVE.pop(run["id"], None)


def test_collection_preserves_failed_attempt_without_replaying(monkeypatch):
    cfg = config(collect_only=True)
    run = runner.make_run(cfg)
    case = run["cases"][0]
    case["results"][0].update(
        transcript=[{"input": "Q", "output": "", "error": "busy"}], reason="busy"
    )
    original = copy.deepcopy(case["results"][0])

    class Connector:
        def __init__(self, *args):
            pass

        async def conversation(self, item):
            raise AssertionError("An attempted message must not be resent")

    async def check():
        executor = runner.EvaluationExecutor(run, cfg, Connector)
        try:
            with executor.runtime.context():
                await executor.target_result(case, 0)
        finally:
            await executor.runtime.close()
            runner.ACTIVE.pop(run["id"], None)

    asyncio.run(check())
    assert case["results"][0] == original
