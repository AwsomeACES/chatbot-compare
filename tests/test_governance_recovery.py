"""Evidence, chain recovery, model-panel and batching failure contracts."""

import asyncio
import copy
import json
import uuid
from unittest.mock import patch

import pytest
from test_bias_governance import config, run_fixture

from app.blackbox import (
    classifier_runtime,
    governance,
    judge,
    judge_batch,
    local_metrics,
    metering,
    studio_engine,
)
from app.blackbox.schema import JudgeSelection


def test_removing_entire_audit_is_detected_and_metadata_is_reserved():
    run = {"id": str(uuid.uuid4()), "audit": []}
    governance.append(run, "start")
    changed = copy.deepcopy(run)
    changed["audit"] = []
    assert governance.verify(changed)["valid"] is False
    with pytest.raises(ValueError, match="metadata"):
        governance.append(run, "bad", sequence=0)


def test_crash_journal_catches_up_without_blessing_changed_history():
    run = {"id": str(uuid.uuid4()), "audit": []}
    governance.append(run, "first")
    checkpoint = copy.deepcopy(run)
    governance.append(run, "second")
    assert governance.verify(checkpoint)["valid"] is False
    assert governance.restore_journal(checkpoint) == 1
    assert governance.verify(checkpoint)["valid"] is True
    checkpoint["audit"][0]["event"] = "edited"
    with pytest.raises(ValueError, match="differs"):
        governance.restore_journal(checkpoint)


def test_multi_judge_concurrency_and_low_agreement_review(monkeypatch):
    active = peak = 0

    async def evaluate(cfg, case, observation):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.015)
            return {
                "score": 90 if cfg.judge_model == "first" else 30,
                "reason": "Exact source supports this",
                "evidence": ["answer"],
            }
        finally:
            active -= 1

    monkeypatch.setattr(judge, "evaluate", evaluate)
    cfg = config()
    cfg.judges = [JudgeSelection(model=m, local=True) for m in ("first", "second")]
    result = asyncio.run(
        studio_engine.panel(
            cfg,
            {"id": "paired", "category": "language", "turns": ["test"]},
            {"transcript": [{"output": "answer"}]},
        )
    )
    assert peak == 2 and result["needs_review"] and result["agreement"] is False
    assert [v["model"] for v in result["judges"]] == ["first", "second"]


def test_explicit_canary_failure_does_not_spend_judge_calls(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(judge, "evaluate", forbidden)
    result = asyncio.run(
        studio_engine.panel(
            config(),
            {"id": "injection", "category": "injection", "turns": ["STUDIO_OVERRIDE_OK"]},
            {"transcript": [{"output": "STUDIO_OVERRIDE_OK"}]},
        )
    )
    assert result["score"] == 0 and result["engine"] == "deterministic-text"


def test_bias_verdict_requires_actual_evidence_from_both_replies(monkeypatch):
    async def request(cfg, send, *args):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"score": 100, "reason": "fair", "evidence": ["First response only."]}
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(judge, "judge_request", request)
    cfg = config()
    cfg.judge_model = "fixture"
    payload = {
        "bias_subtype": "gender",
        "transcript": [
            {"output": "First response only."},
            {"output": "Second response has different words."},
        ],
    }
    with pytest.raises(ValueError, match="evidence"):
        asyncio.run(judge.ask(cfg, payload))


def test_duplicate_batch_ids_are_not_misattributed():
    async def run():
        cfg = config(judge_batch_size=2, judge_batch_wait_ms=1)

        async def request(*args):
            return {"choices": [{"message": {"content": '{"items":[{"id":0},{"id":0}]}'}}]}

        body = {
            "messages": [
                {"role": "system", "content": "criteria"},
                {"role": "user", "content": "{}"},
            ]
        }
        with patch.object(judge, "judge_request", request):
            rows = await asyncio.gather(
                *(judge_batch.completion(cfg, body) for _ in range(2)), return_exceptions=True
            )
        assert all(isinstance(r, ValueError) for r in rows)

    asyncio.run(run())


def test_classifier_timeout_terminates_worker():
    class Process:
        alive = True
        killed = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False
            self.killed = True

        def join(self, timeout):
            pass

    class Pipe:
        def send(self, value):
            pass

        def poll(self, timeout):
            return False

        def close(self):
            pass

    process = Process()

    async def run():
        service = classifier_runtime.Service(process=process, connection=Pipe())
        with pytest.raises(TimeoutError):
            await service.request({}, {}, {"timeout_seconds": 0.01})
        assert process.killed and service.process is None

    asyncio.run(run())


def test_disabled_classifier_does_not_start_worker(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("No automatic download/inference")

    monkeypatch.setattr(classifier_runtime, "request", forbidden)
    assert (
        asyncio.run(local_metrics.classify({"category": "guardrails"}, {"transcript": []}, {}))
        is None
    )


def test_same_family_warning_uses_actual_bot_metadata():
    _, run = run_fixture()
    run["targets"][0]["model"] = ""
    run["cases"][0]["results"][0]["transcript"][0]["response_metadata"] = {
        "model": "gemini-example"
    }
    run["config"]["judges"][0]["model"] = "gemini-judge"
    studio_engine.summarize(run)
    assert any("Same model family" in w for w in run["studio"]["warnings"])


def test_batch_metering_is_shared_and_keeps_all_case_ids(monkeypatch):
    seen = []

    async def request(*args):
        seen.append(dict(metering._context.get()))
        return {
            "choices": [
                {"message": {"content": '{"items":[{"id":0,"score":90},{"id":1,"score":80}]}'}}
            ]
        }

    monkeypatch.setattr(judge, "judge_request", request)

    async def run():
        cfg = config(judge_batch_size=2, judge_batch_wait_ms=1)
        body = {
            "messages": [
                {"role": "system", "content": "criteria"},
                {"role": "user", "content": "{}"},
            ]
        }

        async def item(slot):
            with metering.scope(
                "batch-fixture", "compare", cfg, bot_slot=slot, test_case_id="case-" + slot
            ):
                return await judge_batch.completion(cfg, body)

        await asyncio.gather(item("A"), item("B"))

    asyncio.run(run())
    assert len(seen) == 1 and seen[0]["bot_slot"] is None and seen[0]["category"] == "batch"
