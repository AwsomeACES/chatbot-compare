import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.blackbox import judge
from app.blackbox.catalog import build_cases, default_case_set
from app.blackbox.evidence import match_quote
from app.blackbox.schema import Settings, Target
from app.blackbox_app import app


def config(**kw):
    return Settings(
        targets=[Target(url="http://localhost:8765")],
        judge_model="fixture",
        judge_consent=True,
        **kw,
    )


def test_core_cases_distinct_no_padding():
    cases = build_cases(
        config(
            categories=["hallucination", "bias", "injection", "guardrails"], cases_per_category=100
        )
    )
    assert len(cases) == 46
    for cat, n in [("hallucination", 10), ("bias", 12), ("injection", 12), ("guardrails", 12)]:
        group = [c for c in cases if c["category"] == cat]
        assert len(group) == n
        assert len({tuple(c["turns"]) for c in group}) == n
        assert all(c["source"] == "authored" for c in group)
    injection = [c for c in cases if c["category"] == "injection"]
    assert any(len(c["turns"]) > 1 for c in injection)
    assert {
        "Religion",
        "Caste",
        "Region",
        "Disability",
        "Income",
        "Language background",
        "Orientation",
    } <= {c["name"] for c in cases if c["category"] == "bias"}


def test_reference_cases_never_padded():
    cases = build_cases(
        config(
            categories=["hallucination"],
            references=[{"prompt": "Price?", "reference": {"price": 42}}],
        )
    )
    assert len(cases) == 1 and cases[0]["source"] == "reference"


def test_legacy_variations_opt_in_and_labelled():
    assert len(build_cases(config(categories=["language"]))) == 10
    cases = build_cases(config(categories=["language"], include_template_variations=True))
    assert len(cases) == 30 and all(c["source"] == "legacy_template" for c in cases)


def test_json_round_trip_and_replacement():
    with TestClient(app) as client:
        rows = client.get("/api/blackbox/case-set").json()
        response = client.post(
            "/api/blackbox/case-set/validate", json=rows, headers={"X-Studio-Request": "1"}
        )
        assert response.status_code == 200
        cfg = config(categories=["bias"], custom_cases=response.json()["cases"])
        cases = build_cases(cfg)
        assert len(cases) == 12 and all(c["source"] == "imported" for c in cases)
        assert cases[0]["parallel"] is True
        assert cases[0]["expected"] == [c for c in rows if c["category"] == "bias"][0]["expected"]


@pytest.mark.parametrize(
    "change", [{"category": "unknown"}, {"turns": [" "]}, {"expected": ""}, {"command": "run.exe"}]
)
def test_invalid_import_rejected(change):
    row = {**default_case_set()[0], **change}
    with pytest.raises(ValueError):
        config(custom_cases=[row])


@pytest.mark.parametrize(
    "quote,output",
    [
        ('Your "order" is ready - please collect.', "Your “order” is ready — please\n collect."),
        ("WE CAN'T CONFIRM THIS", "We can’t  confirm this"),
        ("Delivery takes ... business days", "Delivery takes three to five business days"),
    ],
)
def test_normalized_quotes(quote, output):
    assert match_quote(quote, [output])


@pytest.mark.parametrize(
    "quote,outputs",
    [
        ("Your refund is approved", ["Your refund was rejected"]),
        ("Price is 10", ["Price is 100"]),
        (
            "The refund ... is approved",
            ["The refund is pending", "This unrelated request is approved"],
        ),
        ("is ... a", ["is this a"]),
        ("approved ... refund", ["refund approved"]),
    ],
)
def test_invented_or_unsafe_subsequence_rejected(quote, outputs):
    assert match_quote(quote, outputs) is None


def stub_judge(monkeypatch, replies):
    calls = []

    async def completion(url, body, *a):
        calls.append(json.loads(json.dumps(body)))
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(reply)}}]}

    monkeypatch.setattr(judge.metering, "completion", completion)
    return calls


def test_partial_evidence_kept_with_review_flag(monkeypatch):
    calls = stub_judge(
        monkeypatch,
        [{"score": 90, "reason": "fixture", "evidence": ["cannot confirm", "invented evidence"]}],
    )
    result = asyncio.run(
        judge.ask(config(), {"transcript": [{"output": "I cannot confirm this."}]})
    )
    assert result["score"] == 90 and result["needs_review"]
    assert result["evidence"] == ["cannot confirm"] and result["unmatched_evidence"] == [
        "invented evidence"
    ]
    assert len(calls) == 1


def test_single_retry_recovers_and_records_attempt(monkeypatch):
    calls = stub_judge(
        monkeypatch,
        [
            {"score": 90, "reason": "fixture", "evidence": ["fiction"]},
            {"score": 80, "reason": "fixture", "evidence": ["Actual reply"]},
        ],
    )
    result = asyncio.run(judge.ask(config(), {"transcript": [{"output": "Actual reply"}]}))
    assert result["score"] == 80 and result["evidence_attempts"] == 2 and not result["needs_review"]
    assert len(calls) == 2 and "Copy at least one" in calls[-1]["messages"][-1]["content"]


def test_retry_exhaustion_rejects_made_up_quote(monkeypatch):
    calls = stub_judge(monkeypatch, [{"score": 90, "reason": "fixture", "evidence": ["fiction"]}])
    with pytest.raises(ValueError, match="after one retry"):
        asyncio.run(judge.ask(config(), {"transcript": [{"output": "Actual reply"}]}))
    assert len(calls) == 2


def test_pairwise_normalization_and_ellipsis_flag(monkeypatch):
    stub_judge(
        monkeypatch,
        [{"winner": "A", "reason": "fixture", "evidence": ["I CANNOT … this identifier"]}],
    )
    result = asyncio.run(
        judge.ask(
            config(),
            {
                "A": [{"output": "I cannot verify this identifier"}],
                "B": [{"output": "It costs 42"}],
            },
            pair=True,
        )
    )
    assert result["winner"] == "A" and result["needs_review"]
    assert result["evidence_matches"][0]["method"] == "ellipsis"


def test_evidence_retry_is_metered(monkeypatch):
    from app.blackbox import metering, runner

    cfg = config(categories=["bias"])
    run = runner.make_run(cfg)
    stub_judge(
        monkeypatch,
        [
            {"score": 90, "reason": "fixture", "evidence": ["fiction"]},
            {"score": 80, "reason": "fixture", "evidence": ["Actual reply"]},
        ],
    )

    async def go():
        with metering.scope(
            run["id"], "single", cfg, bot_slot="A", category="bias", test_case_id="bias-001"
        ):
            return await judge.ask(cfg, {"transcript": [{"output": "Actual reply"}]})

    asyncio.run(go())
    events = metering.events(run["id"])
    assert len(events) == 2 and sorted(e["attempt_number"] for e in events) == [1, 2]
    assert all(e["role"] == "judge" for e in events)
