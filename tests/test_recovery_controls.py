import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.blackbox import judge, runner
from app.blackbox.catalog import build_cases
from app.blackbox.schema import ImportedCase, Settings, Target


def config(**kw):
    return Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat", kind="rest")],
        categories=["hallucination"],
        **kw,
    )


def test_prompt_rubric_and_no_import_truncation():
    rows = [
        ImportedCase(
            category="hallucination", name=f"Case {i}", prompt="Question", rubric="Answer honestly"
        )
        for i in range(79)
    ]
    assert len(build_cases(config(custom_cases=rows, all_imported_cases=True))) == 79
    assert len(build_cases(config(custom_cases=rows))) == 30


def test_transient_judge_retry_but_not_auth(monkeypatch):
    class Error(Exception):
        status_code = 503

    async def run():
        count = 0

        async def send():
            nonlocal count
            count += 1
            if count == 1:
                raise Error()
            return {"ok": True}

        monkeypatch.setattr(judge.asyncio, "sleep", AsyncMock())
        assert await judge.judge_request(config(), send, []) == {"ok": True}
        assert count == 2
        Error.status_code = 401
        count = 0
        with pytest.raises(Error):
            await judge.judge_request(config(), send, [])
        assert count == 1

    asyncio.run(run())


def test_delete_is_scoped_and_rejects_active():
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    for ident in (first, second):
        db.save("blackbox", {"id": ident})
    runner.ACTIVE[first] = asyncio.Event()
    client = TestClient(blackbox_app.app)
    assert (
        client.delete("/api/blackbox/runs/" + first, headers={"x-studio-request": "1"}).status_code
        == 409
    )
    runner.ACTIVE.pop(first)
    assert (
        client.delete("/api/blackbox/runs/" + first, headers={"x-studio-request": "1"}).status_code
        == 200
    )
    assert db.get("blackbox", first) is None and db.get("blackbox", second)
    db.delete("blackbox", second)


def test_saved_transcript_is_rejudged_without_bot_call(monkeypatch):
    cfg = config(consent=True)
    run = runner.make_run(cfg)
    case = run["cases"][0]
    observation = {
        "transcript": [{"input": "Q", "output": "Evidence", "seconds": 1}],
        "error": None,
    }
    case["resume_observations"] = {"0": observation}

    class Connector:
        def __init__(self, *args):
            pass

        async def conversation(self, case):
            raise AssertionError("Bot should not be billed again")

    monkeypatch.setattr(
        runner, "evaluate", AsyncMock(return_value={"score": 90, "reason": "fixture"})
    )

    async def run_case():
        executor = runner.EvaluationExecutor(run, cfg, Connector)
        with executor.runtime.context():
            await executor.target_result(case, 0)
        await executor.runtime.close()
        runner.ACTIVE.pop(run["id"], None)

    asyncio.run(run_case())
    assert case["results"][0]["score"] == 90


def test_gemini_compatible_total_includes_thoughts():
    from app.blackbox.metering import normalize

    data = {"usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 27}}
    counts = normalize(data, "gemini-2.5-flash")
    assert counts["input_tokens"] == 7
    assert counts["output_tokens"] == 1
    assert counts["reasoning_tokens"] == 19
    data["usage"]["completion_tokens"] = 20
    data["usage"]["completion_tokens_details"] = {"reasoning_tokens": 19}
    assert normalize(data, "gemini-2.5-flash") == counts


def test_rate_limit_recovery_keeps_attempt_and_does_not_retry_speed(monkeypatch):
    async def scenario(category):
        cfg = config(consent=True)
        record = runner.make_run(cfg)
        case = record["cases"][0]
        case["category"] = category
        failure = {"error": "HTTP 429 rate_limit", "transcript": [{"error": "429"}]}
        success = {"error": None, "transcript": [{"input": "Q", "output": "A"}]}
        mock = AsyncMock(side_effect=[failure, success])

        class Client:
            def __init__(self, *args):
                self.conversation = mock

        executor = runner.EvaluationExecutor(record, cfg, Client)
        monkeypatch.setattr(executor, "checkpoint", lambda: None)
        monkeypatch.setattr(runner.asyncio, "sleep", AsyncMock())
        result = await executor.conversation_with_recovery(case, 0, 5)
        await executor.runtime.close()
        runner.ACTIVE.pop(record["id"], None)
        if category == "performance":
            assert result == failure and mock.await_count == 1
        else:
            assert result == success and mock.await_count == 2
            assert case["request_attempts"][0]["observation"] == failure

    asyncio.run(scenario("hallucination"))
    asyncio.run(scenario("performance"))


def test_empty_balance_is_not_transient():
    class NoBalance(Exception):
        status_code = 429

    assert not judge.transient_error(NoBalance("insufficient balance"))


def test_incomplete_judge_retries_once_with_larger_limit(monkeypatch):
    answers = AsyncMock(
        side_effect=[
            {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"score":90,"reason":"Supported","evidence":["Recorded answer"]}'
                        },
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(judge, "judge_request", answers)
    cfg = config(judge_consent=True, judge_model="fixture")
    result = asyncio.run(judge.ask(cfg, {"transcript": [{"output": "Recorded answer"}]}))
    assert result["score"] == 90 and answers.await_count == 2
    assert answers.await_args.args[3] == 3000
