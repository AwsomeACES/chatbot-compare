"""Export parity (T-020): JSON, PDF and the teammate Markdown must agree.

The review found the shareable explanation lived outside the product. These tests assert the
three supported exports describe the same optional AI explanation, the same provider failures and
the same cost status, and that none of them drops or rewrites a recorded Finding.
"""

import json
import uuid

import pytest

from app import database as db
from app.assurance import readiness, service
from app.assurance.models import Evidence, Finding, missing
from app.assurance.white import CHECKS


def finding(test: str, verdict: str, **extra) -> dict:
    category, tool = CHECKS[test]
    if verdict == "not_tested":
        row = missing("white", 0, category, test, extra.pop("reason", "No evidence."))
    else:
        row = Finding(
            mode="white",
            category=category,
            test_id=test,
            verdict=verdict,
            evidence=[
                Evidence(kind="code", excerpt="SECRET_FIXTURE_EXCERPT", file="bot.py", line=7)
            ],
            explanation="fixture explanation",
            checked=test,
            consequence="fixture consequence",
            fix="Review the cited lines.",
        )
    row.tool = tool
    row.details = {"scanner_completed": True}
    return row.model_copy(update=extra).model_dump()


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


def assessment(with_explanation: bool = True) -> dict:
    run = {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "modes": ["white"],
        "config": {"targets": [{"name": "Fixture bot"}], "judges": []},
        "findings": [
            finding("hardcoded_secrets", "fail"),
            finding("unsafe_patterns", "pass"),
            finding("retention", "not_tested", reason="No retention evidence supplied."),
        ],
        "combined": {
            "assurance": "White-box evidence",
            "verdict": "Review required",
            "reason": "One check needs attention.",
            "mapping": {"note": "Informational framework reference only."},
        },
        "input_hashes": {"source_zip": "b" * 64},
        "audit": [],
    }
    if with_explanation:
        run["ai_explanations"] = [
            {
                "id": "expl1",
                "source": "Automated AI explanation",
                "status": "accepted",
                "model": "llama3.2:3b",
                "provider_model": "llama3.2:3b-rev-7",
                "local": True,
                "cloud_consent": False,
                "payload_hash": "a" * 64,
                "purpose": "Supplemental explanation. Original verdicts are unchanged.",
                "checks": [
                    {
                        "test_id": "hardcoded_secrets",
                        "assessment": "false_positive",
                        "explanation": "These are model identifiers, not keys.",
                    }
                ],
                "attempts": [
                    {
                        "model": "gpt-fixture",
                        "local": False,
                        "status": "failed",
                        "reason": "Provider quota or billing unavailable.",
                    },
                    {
                        "model": "llama3.2:3b",
                        "local": True,
                        "status": "accepted",
                        "provider_model": "llama3.2:3b-rev-7",
                    },
                ],
            }
        ]
    db.save("assurance", run)
    return run


def exports(run: dict) -> tuple[dict, str, str]:
    """The JSON export, the teammate Markdown and the PDF's plain text."""
    from app.assurance import routes

    exported = service.export(run)
    teammate = readiness.teammate_markdown(exported)
    captured: list[str] = []

    class Doc:
        def __init__(self, *args, **kwargs):
            pass

        def build(self, story):
            captured.extend(p.getPlainText() for p in story if hasattr(p, "getPlainText"))

    import reportlab.platypus as platypus

    real = platypus.SimpleDocTemplate
    platypus.SimpleDocTemplate = Doc
    try:
        routes.download(uuid.UUID(run["id"]), format="pdf")
    finally:
        platypus.SimpleDocTemplate = real
    return exported, teammate, "\n".join(captured)


# --- parity ----------------------------------------------------------------------------------


def test_every_export_names_the_same_explanation_and_model():
    run = assessment()
    exported, teammate, pdf = exports(run)
    block = exported["ai_explanation_provenance"]
    assert block["present"] is True
    assert "llama3.2:3b" in block["model"]
    assert "Automated AI explanation" in block["model"]
    assert block["returned_model"] == "llama3.2:3b-rev-7"
    for text in (teammate, pdf):
        assert "Optional AI explanation" in text
        assert "llama3.2:3b" in text
        assert "llama3.2:3b-rev-7" in text
        assert "not a guaranteed immutable revision" in text


def test_every_export_records_the_same_provider_failure():
    run = assessment()
    exported, teammate, pdf = exports(run)
    failures = exported["ai_explanation_provenance"]["provider_failures"]
    assert [f["model"] for f in failures] == ["gpt-fixture"]
    for text in (teammate, pdf):
        assert "gpt-fixture" in text
        assert "quota or billing unavailable" in text


def test_every_export_reports_the_same_cost_status_and_never_invents_zero():
    run = assessment()
    exported, teammate, pdf = exports(run)
    cost = exported["ai_explanation_provenance"]["cost"]
    assert cost["calls"] == 0
    assert cost["status"] == "No explanation calls"
    for text in (teammate, pdf):
        assert "Explanation cost: No explanation calls" in text
        assert "$0.00" not in text, "an unmetered explanation must not be shown as zero"


def test_every_export_says_so_when_no_explanation_is_attached():
    run = assessment(with_explanation=False)
    exported, teammate, pdf = exports(run)
    block = exported["ai_explanation_provenance"]
    assert block["present"] is False
    assert "No optional AI explanation is attached" in block["note"]
    for text in (teammate, pdf):
        assert "No optional AI explanation is attached" in text


# --- the original Findings survive ------------------------------------------------------------


def test_the_json_export_preserves_every_recorded_finding_and_its_evidence():
    run = assessment()
    exported, _, _ = exports(run)
    assert len(exported["findings"]) == len(run["findings"])
    verdicts = {f["test_id"]: f["verdict"] for f in exported["findings"]}
    assert verdicts == {
        "hardcoded_secrets": "fail",
        "unsafe_patterns": "pass",
        "retention": "not_tested",
    }
    secrets = next(f for f in exported["findings"] if f["test_id"] == "hardcoded_secrets")
    assert secrets["evidence"][0]["excerpt"] == "SECRET_FIXTURE_EXCERPT"
    assert secrets["evidence"][0]["file"] == "bot.py"
    assert secrets["evidence"][0]["line"] == 7


def test_a_not_tested_finding_keeps_a_none_score_and_a_reason_in_every_export():
    """Non-negotiable: missing evidence is never a measured zero."""
    run = assessment()
    exported, teammate, pdf = exports(run)
    row = next(f for f in exported["findings"] if f["test_id"] == "retention")
    assert row["verdict"] == "not_tested"
    assert row["score"] is None
    assert row["explanation"]
    for text in (teammate, pdf):
        assert "retention" in text


def test_an_explanation_never_changes_a_recorded_verdict():
    run = assessment()
    exported, _, _ = exports(run)
    assessed = exported["ai_explanation_provenance"]
    assert assessed["present"] is True
    # The explanation calls the secrets finding a false positive; the verdict stays "fail".
    secrets = next(f for f in exported["findings"] if f["test_id"] == "hardcoded_secrets")
    assert secrets["verdict"] == "fail"
    assert "unchanged" in assessed["note"]


@pytest.mark.parametrize("fmt", ["json", "teammate"])
def test_the_download_endpoint_serves_both_text_formats(fmt):
    from app.assurance import routes

    run = assessment()
    response = routes.download(uuid.UUID(run["id"]), format=fmt)
    body = response.body.decode("utf-8")
    assert "llama3.2:3b" in body
    if fmt == "json":
        assert json.loads(body)["ai_explanation_provenance"]["present"] is True
