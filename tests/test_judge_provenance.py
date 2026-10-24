"""Evaluator provenance (T-036): who actually scored each Case, and honest gaps.

The rule under test is that a saved Run either identifies its actual evaluator from recorded
metadata, or says the provenance is unavailable. It must never reconstruct a plausible-looking
evaluator for a Run saved before the metadata existed.
"""

import uuid

import pytest

from app import database as db
from app.blackbox import judge_provenance as prov
from app.blackbox.schema import JudgeSelection
from app.blackbox.studio_engine import provenance

LOCAL = "http://127.0.0.1:11434/v1/chat/completions"
CLOUD = "https://api.openai.com/v1/chat/completions"


@pytest.fixture(autouse=True)
def only_this_test_records():
    """Remove records this file creates, so a later test never sees them.

    The suite shares one temporary database. Leftover saved runs changed what auto-resume and
    the history listings found, which failed unrelated tests in a full-suite run.
    """
    kinds = ("blackbox", "assurance")
    before = {kind: {r["id"] for r in db.all_records(kind)} for kind in kinds}
    yield
    for kind in kinds:
        for record in db.all_records(kind):
            if record["id"] not in before[kind]:
                db.delete(kind, record["id"])


def verdict(model, requested=None, recorded=True, **extra):
    row = {"model": model, "requested_model": requested or model, "score": 90, **extra}
    if recorded:
        row = {
            "provenance_version": 1,
            "endpoint": extra.get("endpoint", CLOUD),
            "provider": "openai",
            "local": False,
            "family": "gpt",
            "fallback": False,
            "fallback_reasons": [],
            **row,
        }
    return row


def run_with(*judge_rows, config=None, studio=None, engine=None):
    cases = [
        {
            "id": f"case-{index}",
            "category": "functional",
            "results": [
                {
                    "status": "passed",
                    "score": 90,
                    "judges": [row],
                    "transcript": [{"input": "hi", "output": "safe reply", "seconds": 0.1}],
                    **({"engine": engine} if engine else {}),
                }
            ],
        }
        for index, row in enumerate(judge_rows)
    ]
    return {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "config": config if config is not None else {"judges": [{"model": "gpt-fixture"}]},
        "targets": [{"name": "bot"}],
        "categories": sorted({c["category"] for c in cases}),
        "cases": cases,
        "studio": studio or {},
    }


# --- recording -------------------------------------------------------------------------------


def test_provenance_records_the_actual_evaluator_and_omits_credentials():
    requested = JudgeSelection(model="gpt-fixture", url=CLOUD)
    row = provenance(requested, requested, [])
    assert row["provenance_version"] == 1
    assert row["endpoint"] == CLOUD
    assert row["provider"] == "openai"
    assert row["local"] is False
    assert row["fallback"] is False
    assert row["fallback_reasons"] == []
    assert not any("token" in key or "key" in key for key in row)


def test_provenance_records_why_a_fallback_answered():
    requested = JudgeSelection(model="gpt-fixture", url=CLOUD)
    fallback = JudgeSelection(model="llama3.2:3b", url=LOCAL, local=True, fallback=True)
    row = provenance(fallback, requested, [{"model": "gpt-fixture", "reason": "quota exhausted"}])
    assert row["fallback"] is True
    assert row["local"] is True
    assert row["provider"] == "local"
    assert row["requested_endpoint"] == CLOUD
    assert row["endpoint"] == LOCAL
    assert row["fallback_reasons"] == [
        {"model": "gpt-fixture", "reason": "quota exhausted"},
    ]


# --- describing ------------------------------------------------------------------------------


def test_requested_and_actual_evaluators_are_reported_separately():
    run = run_with(
        verdict("llama3.2:3b", requested="gpt-fixture", fallback=True, local=True, provider="local")
    )
    described = prov.describe(run)
    assert described["available"] is True
    assert [r["model"] for r in described["requested"]] == ["gpt-fixture"]
    only = described["evaluators"][0]
    assert only["actual_model"] == "llama3.2:3b"
    assert only["requested_models"] == ["gpt-fixture"]
    assert only["fallback_cases"] == 1


def test_returned_model_identifier_is_reported_with_its_uncertainty():
    run = run_with(verdict("gpt-fixture", provider_model="gpt-fixture-2026-01"))
    described = prov.describe(run)
    assert described["evaluators"][0]["returned_models"] == ["gpt-fixture-2026-01"]
    assert "not guaranteed immutable revisions" in described["revision_note"]
    assert "not guaranteed immutable revisions" in described["evaluators"][0]["revision_note"]


def test_a_missing_returned_identifier_says_so():
    described = prov.describe(run_with(verdict("gpt-fixture")))
    assert described["evaluators"][0]["returned_models"] == ["Not supplied by provider"]


def test_older_records_report_unavailable_provenance_without_guessing():
    """The central honesty rule: no reconstructed evaluator for a pre-provenance Run."""
    run = run_with(verdict("gpt-fixture", recorded=False))
    described = prov.describe(run)
    assert described["available"] is False
    assert described["verdicts_without_metadata"] == 1
    assert "have not" in described["unavailable_note"]
    only = described["evaluators"][0]
    assert only["provenance_recorded"] is False
    assert only["endpoint"] == prov.UNKNOWN
    assert only["provider"] == prov.UNKNOWN
    assert only["local"] is None, "an unrecorded local flag must stay unknown, not default False"
    assert only["fallback_cases"] == 0


def test_a_partly_recorded_run_is_marked_partial():
    run = run_with(verdict("gpt-fixture"), verdict("gpt-fixture", recorded=False))
    described = prov.describe(run)
    assert described["available"] is True
    assert described["partially_available"] is True
    assert described["verdicts_with_metadata"] == 1
    assert described["verdicts_without_metadata"] == 1
    assert described["unavailable_note"]


def test_mixed_judge_runs_stay_visibly_qualified():
    run = run_with(verdict("gpt-fixture"), verdict("other-fixture"))
    described = prov.describe(run)
    assert described["mixed_judges"] is True
    assert "not interchangeable" in described["mixed_note"]
    assert len(described["evaluators"]) == 2


def test_a_single_evaluator_run_is_not_qualified_as_mixed():
    described = prov.describe(run_with(verdict("gpt-fixture"), verdict("gpt-fixture")))
    assert described["mixed_judges"] is False
    assert described["mixed_note"] == ""
    assert described["evaluators"][0]["cases"] == 2


def test_deterministic_and_classifier_results_are_not_attributed_to_a_judge():
    run = run_with(config={"judges": []})
    run["cases"] = [
        {
            "id": "d1",
            "category": "functional",
            "results": [
                {
                    "status": "failed",
                    "score": 0,
                    "engine": "deterministic-text",
                    "transcript": [{"input": "hi", "output": "marker", "seconds": 0.1}],
                }
            ],
        },
        {
            "id": "p1",
            "category": "performance",
            "results": [
                {
                    "status": "passed",
                    "score": 100,
                    "engine": "measured-latency",
                    "transcript": [{"input": "hi", "output": "fast", "seconds": 0.1}],
                }
            ],
        },
        {
            "id": "c1",
            "category": "hallucination",
            "results": [
                {
                    "status": "failed",
                    "score": 10,
                    "engine": "hallucination_detector",
                    "local_classifier": {"label": "unsupported"},
                    "transcript": [{"input": "hi", "output": "claim", "seconds": 0.1}],
                }
            ],
        },
    ]
    described = prov.describe(run)
    assert described["evaluators"] == []
    counts = described["non_judge_engines"]
    assert counts["Deterministic rule, no Judge"] == 1
    assert counts["Measured latency, no Judge"] == 1
    assert counts["Local classifier, no Judge"] == 1


def test_same_family_warning_is_listed_separately_from_other_warnings():
    run = run_with(
        verdict("gpt-fixture"),
        studio={
            "warnings": [
                "Same model family: bot and judge (gpt). Shared model bias may affect scores.",
                "A cloud/local judge cannot repair an unavailable chatbot API.",
            ],
            "family_warnings": [
                "Same model family: bot and judge (gpt). Shared model bias may affect scores."
            ],
        },
    )
    described = prov.describe(run)
    assert len(described["family_warnings"]) == 1
    assert described["family_warnings"][0].startswith("Same model family")
    assert "separate from both the same-family warning" in described["calibration_note"]


def test_older_runs_without_the_separate_field_still_surface_family_warnings():
    run = run_with(
        verdict("gpt-fixture"),
        studio={
            "warnings": [
                "Same model family: bot and judge (gpt). Shared model bias may affect scores.",
                "A cloud/local judge cannot repair an unavailable chatbot API.",
            ]
        },
    )
    assert len(prov.describe(run)["family_warnings"]) == 1


def test_calibration_status_is_attached_per_evaluator_and_stays_diagnostic():
    run = run_with(verdict("gpt-fixture"))
    described = prov.describe(run)
    calibration = described["evaluators"][0]["calibration"]
    assert calibration["state"] == "uncalibrated"
    assert calibration["diagnostic_only"] is True
    assert calibration["agreement_percent"] is None
    assert "Distinct from model-to-model" in calibration["model_to_model_note"]


def test_describe_never_rescores_or_rewrites_the_saved_run():
    run = run_with(verdict("gpt-fixture"))
    db.save("blackbox", run)
    before = db.get("blackbox", run["id"])
    prov.describe(run)
    after = db.get("blackbox", run["id"])
    assert after == before
    assert after["cases"][0]["results"][0]["score"] == 90


def test_the_run_endpoint_serves_provenance_without_persisting_it():
    from fastapi.testclient import TestClient

    from app.main import app

    run = run_with(verdict("gpt-fixture"))
    run["progress"] = 100
    run["stage"] = "Complete"
    db.save("blackbox", run)
    with TestClient(app) as client:
        body = client.get(f"/api/blackbox/runs/{run['id']}").json()
    assert body["judge_provenance"]["evaluators"][0]["actual_model"] == "gpt-fixture"
    assert "judge_provenance" not in db.get("blackbox", run["id"])


@pytest.mark.parametrize("empty", [{}, {"cases": []}, {"cases": [{"id": "x", "results": []}]}])
def test_describe_tolerates_runs_with_no_verdicts(empty):
    described = prov.describe({"config": {}, **empty})
    assert described["available"] is False
    assert described["evaluators"] == []
    assert described["mixed_judges"] is False


# --- presentation: PDF, Governance and Results ------------------------------------------------


def studio_run(*judge_rows, studio_extra=None):
    """A real simple-protocol Run built by the runner, with chosen Judge verdicts injected.

    Built through `make_run` and `aggregate` so the PDF renderer sees the genuine saved shape
    rather than a hand-assembled dictionary that might drift from it.
    """
    from app.blackbox.runner import aggregate, make_run
    from app.blackbox.schema import Settings, Target

    cfg = Settings(
        targets=[Target(name="bot", url="http://localhost:8800/chat")],
        simple_mode=True,
        judges=[JudgeSelection(model="gpt-fixture", url=CLOUD)],
        consent=True,
        judge_consent=True,
    )
    run = make_run(cfg)
    run["status"] = "completed"
    run["stage"] = "Complete"
    for index, case in enumerate(run["cases"]):
        case["completed"] = True
        for result in case["results"]:
            result.update(
                status="passed",
                score=90.0,
                reason="fixture",
                seconds=0.1,
                transcript=[
                    {"input": str(turn), "output": "safe reply", "seconds": 0.1}
                    for turn in (case.get("turns") or ["prompt"])
                ],
                judges=[judge_rows[index % len(judge_rows)]],
            )
    aggregate(run)
    run["studio"].update(studio_extra or {})
    return run


def pdf_text(run, monkeypatch):
    from app.blackbox import reports

    captured = []
    monkeypatch.setattr(
        reports.SimpleDocTemplate,
        "build",
        lambda self, story, **kwargs: captured.extend(
            p.getPlainText() for p in story if hasattr(p, "getPlainText")
        ),
    )
    reports.generate_pdf(run)
    return "\n".join(captured)


def test_pdf_names_the_actual_evaluator_and_the_fallback_reason(monkeypatch):
    run = studio_run(
        verdict(
            "llama3.2:3b",
            requested="gpt-fixture",
            fallback=True,
            local=True,
            provider="local",
            provider_model="llama3.2:3b",
            fallback_reasons=[{"model": "gpt-fixture", "reason": "quota exhausted"}],
        )
    )
    text = pdf_text(run, monkeypatch)
    assert "Which judge scored each case" in text
    assert "Actual evaluator llama3.2:3b" in text
    assert "requested gpt-fixture" in text
    assert "quota exhausted" in text
    assert "not guaranteed immutable revisions" in text


def test_pdf_discloses_missing_provenance_for_an_older_record(monkeypatch):
    text = pdf_text(studio_run(verdict("gpt-fixture", recorded=False)), monkeypatch)
    assert "saved before evaluator provenance was recorded" in text
    assert "have not been reconstructed" in text


def test_pdf_qualifies_a_mixed_judge_run(monkeypatch):
    text = pdf_text(studio_run(verdict("gpt-fixture"), verdict("other-fixture")), monkeypatch)
    assert "not interchangeable across evaluators" in text


def test_governance_describe_separates_family_warnings_from_provenance():
    from app.blackbox import governance

    family = "Same model family: bot and judge (gpt). Shared model bias may affect scores."
    run = studio_run(verdict("gpt-fixture"))
    run["studio"]["warnings"] = [family, "A cloud/local judge cannot repair an unavailable API."]
    run["studio"]["family_warnings"] = [family]
    described = governance.describe(run)
    assert described["family_warnings"] == [family]
    assert described["judge_provenance"]["evaluators"][0]["actual_model"] == "gpt-fixture"
    assert described["judge_provenance"]["family_warnings"] == [family]
    # Human alignment and model-to-model agreement stay separate fields.
    assert "human_alignment" in described
    assert "agreement_percent" in described["run_integrity"]
