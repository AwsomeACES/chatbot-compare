import asyncio
import json
from collections import Counter
from unittest.mock import AsyncMock

from app.blackbox import judge
from app.blackbox.catalog import build_cases
from app.blackbox.metering import normalize
from app.blackbox.schema import Settings, Target
from app.config import ROOT


def test_gemma_one_verdict_wrapper_and_evidence_validation(monkeypatch):
    operation = AsyncMock(
        return_value={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '[{"score":90,"reason":"Supported","evidence":["Actual answer"]}]'
                    },
                }
            ]
        }
    )
    monkeypatch.setattr(judge, "judge_request", operation)
    cfg = Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat")],
        judge_model="gemma-4-26b-a4b-it",
        judge_consent=True,
    )
    verdict = asyncio.run(judge.ask(cfg, {"transcript": [{"output": "Actual answer"}]}))
    assert verdict["score"] == 90 and verdict["evidence"] == ["Actual answer"]


def test_gemma_token_gap_is_counted():
    data = {"usage": {"prompt_tokens": 11, "completion_tokens": 0, "total_tokens": 108}}
    counts = normalize(data, "models/gemma-4-26b-a4b-it")
    assert counts["input_tokens"] == 11 and counts["reasoning_tokens"] == 97


def test_twenty_per_category_pack_is_complete():
    cases = json.loads(
        (ROOT / "app/blackbox/cases/reliance-20-per-category.json").read_text(encoding="utf-8")
    )
    cfg = Settings(
        targets=[Target(url="http://127.0.0.1:8000/chat")],
        custom_cases=cases,
        all_imported_cases=True,
        consent=True,
        judge_consent=True,
        judge_model="gemma-4-26b-a4b-it",
        policy="Protect personal information",
        scope="Electronics support",
        performance_consent=True,
    )
    built = build_cases(cfg)
    assert len(built) == 320
    assert set(Counter(c["category"] for c in built).values()) == {20}
    assert not any(c["prerequisite"] for c in built)


def test_native_gemma_excludes_thoughts_and_retains_usage():
    from app.blackbox.gemma_native import adapt_response, request_body

    data = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"thought": True, "text": "private thinking"},
                        {"text": "Actual answer"},
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 2,
            "thoughtsTokenCount": 4,
            "totalTokenCount": 16,
        },
    }
    result = adapt_response(data, "gemma-4-26b-a4b-it")
    assert result["choices"][0]["message"]["content"] == "Actual answer"
    counts = normalize(result)
    assert counts["reasoning_tokens"] == 4 and counts["output_tokens"] == 2
    body = request_body(
        [{"role": "system", "content": "Rules"}, {"role": "user", "content": "Question"}],
        1500,
        True,
    )
    assert body["systemInstruction"]["parts"][0]["text"] == "Rules"
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
