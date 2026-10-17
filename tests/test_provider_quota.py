"""Account exhaustion must pause dispatch without becoming a failed answer."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.blackbox import judge, runner
from app.blackbox.quota import ProviderQuotaUnavailable, quota_reason
from app.blackbox.schema import Settings, Target


def test_daily_quota_body_is_recognized_without_leaking_key():
    response = httpx.Response(
        429,
        json=[
            {
                "error": {
                    "message": "secret-fixture",
                    "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
                }
            }
        ],
        request=httpx.Request("POST", "https://example.test/chat"),
    )
    error = httpx.HTTPStatusError("429", request=response.request, response=response)
    reason = quota_reason(error)
    assert "daily" in reason and "secret-fixture" not in reason
    assert quota_reason(reason) == reason
    assert quota_reason("Provider API balance or billing quota is exhausted.")
    assert quota_reason("HTTP 429 rate_limit") is None


def test_daily_quota_judge_does_not_retry(monkeypatch):
    class DailyQuotaError(Exception):
        status_code = 429
        body = {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}

    operation = AsyncMock(side_effect=DailyQuotaError("untrusted private message"))
    monkeypatch.setattr(judge.metering, "call", operation)
    with pytest.raises(ProviderQuotaUnavailable):
        asyncio.run(
            judge.judge_request(
                Settings(targets=[Target(url="http://127.0.0.1:8000/chat")]), AsyncMock(), []
            )
        )
    assert operation.await_count == 1


def test_quota_pauses_suite_preserving_scores_and_transcripts(monkeypatch):
    config = Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat", kind="rest")],
        categories=["hallucination"],
        consent=True,
        case_concurrency=1,
    )
    run = runner.make_run(config)
    run["cases"] = run["cases"][:3]
    first = run["cases"][0]
    first["completed"] = True
    first["results"][0].update(
        status="passed",
        score=90,
        reason="Previous evidence",
        transcript=[{"output": "Earlier answer", "seconds": 1}],
    )
    conversation = AsyncMock(
        return_value={
            "transcript": [{"input": "Q", "output": "Saved answer", "seconds": 1}],
            "error": None,
        }
    )

    class Client:
        def __init__(self, *args):
            self.conversation = conversation

        async def detect(self):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(
        runner,
        "evaluate",
        AsyncMock(side_effect=ProviderQuotaUnavailable("AI judge: daily quota exhausted")),
    )
    result = asyncio.run(runner.execute(run, config, Client))
    assert result["status"] == "provider_limit"
    assert conversation.await_count == 1
    assert first["results"][0]["score"] == 90
    second = result["cases"][1]["results"][0]
    assert second["status"] == "not_tested" and second["score"] is None
    assert second["transcript"][0]["output"] == "Saved answer"
    assert "daily quota" in result["stage"]
    assert "daily quota" in result["cases"][2]["results"][0]["reason"]


def test_target_daily_quota_does_not_retry(monkeypatch):
    config = Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat", kind="rest")],
        categories=["hallucination"],
        consent=True,
        case_concurrency=1,
    )
    run = runner.make_run(config)
    conversation = AsyncMock(
        return_value={"error": "Chat stream error: quota_exhausted", "transcript": []}
    )

    class Client:
        def __init__(self, *args):
            self.conversation = conversation

        async def detect(self):
            pass

        async def close(self):
            pass

    result = asyncio.run(runner.execute(run, config, Client))
    assert result["status"] == "provider_limit"
    assert conversation.await_count == 1
    assert result["summary"][0]["tested"] == 0
