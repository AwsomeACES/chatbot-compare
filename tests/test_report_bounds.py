"""Bounded PDF rendering (T-046).

A saved Run with large evidence previously rendered unbounded flowables inside
the request handler, which blocked the single server worker until the client
timed out. These tests use synthetic runs only: no provider is called and no
real saved evaluation is read. They assert the document stays bounded, says so
when it truncates, keeps the JSON export complete, and never turns a rendering
failure into a silently successful export.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.blackbox import reports, runner
from app.blackbox.schema import Settings, Target


def settings(n: int = 1, count: int = 4) -> Settings:
    custom = [
        {
            "category": "injection",
            "name": f"Fixture {i}",
            "turns": [f"Fixture prompt {i}"],
            "expected": "Check marker",
            "checks": {"canary": "marker"},
        }
        for i in range(count)
    ]
    return Settings(
        targets=[Target(name=f"Bot {i}", url=f"http://localhost:{8700 + i}") for i in range(n)],
        categories=["injection"],
        consent=True,
        custom_cases=custom,
        judge_enabled=False,
    )


def saved(reply: str = "Short synthetic reply.", count: int = 4, n: int = 1) -> dict:
    """Build a completed synthetic Run whose transcripts carry the given reply."""
    config = settings(n, count)
    run = runner.make_run(config)
    run["status"] = "completed"
    for case in run["cases"]:
        for index, result in enumerate(case["results"]):
            result.update(
                status="passed",
                score=100.0,
                seconds=0.1,
                reason="Synthetic fixture reason.",
                transcript=[{"input": f"Fixture prompt {index}", "output": reply, "seconds": 0.1}],
            )
    return config, run


def exported(run: dict) -> dict:
    from app.blackbox.governance import export_run

    return export_run(run)


def test_a_normal_report_renders_without_a_truncation_notice():
    _, run = saved()
    path = reports.generate_pdf(exported(run))
    body = path.read_bytes()
    assert body.startswith(b"%PDF")
    assert path.stat().st_size > 1000


def rendered_story(monkeypatch, record) -> list:
    """Capture the flowables handed to ReportLab for this record."""
    captured: list = []
    original = reports.SimpleDocTemplate

    class Capturing(original):
        def build(self, story, *args, **kwargs):
            captured.extend(story)
            return original.build(self, story, *args, **kwargs)

    monkeypatch.setattr(reports, "SimpleDocTemplate", Capturing)
    reports.generate_pdf(record)
    return captured


def story_text(story) -> str:
    return " ".join(getattr(item, "text", "") for item in story)


def test_oversized_evidence_is_truncated_and_the_pdf_discloses_it(monkeypatch):
    """Large-but-supported evidence still renders, with the limit disclosed."""
    monkeypatch.setattr(reports, "MAX_PARAGRAPH_CHARS", 200)
    long_reply = "SYNTHETIC " * 400
    _, run = saved(reply=long_reply)
    record = exported(run)
    text = story_text(rendered_story(monkeypatch, record))
    assert reports.TRUNCATION_NOTICE in text
    assert "[truncated in this PDF]" in text
    # The stored evidence is unchanged; only this rendering was bounded.
    assert long_reply in json.dumps(record)


def test_a_report_within_the_bounds_carries_no_truncation_notice(monkeypatch):
    _, run = saved()
    text = story_text(rendered_story(monkeypatch, exported(run)))
    assert reports.TRUNCATION_NOTICE not in text
    assert "[truncated in this PDF]" not in text


def test_the_flowable_budget_stops_an_unbounded_document(monkeypatch):
    """The budget must actually shorten the document, not merely be present."""
    record = exported(saved(count=60)[1])
    monkeypatch.setattr(reports, "MAX_FLOWABLES", 10**9)
    unbounded = len(rendered_story(monkeypatch, record))
    monkeypatch.setattr(reports, "MAX_FLOWABLES", 40)
    bounded = rendered_story(monkeypatch, record)
    # The budget caps paragraph appends; one page break and the inserted
    # disclosure paragraph are the only flowables added beyond it.
    assert len(bounded) <= 42
    assert unbounded > 300
    assert len(bounded) < unbounded
    assert reports.TRUNCATION_NOTICE in story_text(bounded)


def test_the_governance_block_is_not_truncated_in_a_normal_report(monkeypatch):
    """The real per-paragraph cap must clear the serialized governance block."""
    story = rendered_story(monkeypatch, exported(saved(count=60)[1]))
    longest = max(len(getattr(item, "text", "")) for item in story)
    assert 8000 < longest < reports.MAX_PARAGRAPH_CHARS
    assert reports.TRUNCATION_NOTICE not in story_text(story)


def test_a_rendering_failure_becomes_an_actionable_refusal(monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def build(self, *args, **kwargs):
            raise RuntimeError("synthetic layout failure")

    monkeypatch.setattr(reports, "SimpleDocTemplate", Broken)
    _, run = saved()
    record = exported(run)
    with pytest.raises(reports.ReportTooLarge) as caught:
        reports.generate_pdf(record)
    message = str(caught.value)
    assert "JSON export" in message
    # The refusal must not leak report content into the error.
    assert "Fixture prompt" not in message
    assert not (reports.RUNTIME / "reports" / f"blackbox-{record['id']}.pdf").exists()


def test_the_download_route_refuses_with_413_and_json_still_works(monkeypatch):
    from app.blackbox_app import app

    config, run = saved()
    runner.aggregate(run)
    runner.save(run, config)
    client = TestClient(app)
    ident = run["id"]

    def refuse(_run):
        raise reports.ReportTooLarge("Too large; download the JSON export instead.")

    monkeypatch.setattr("app.blackbox_app.generate_pdf", refuse)
    response = client.get(f"/api/blackbox/runs/{ident}/download?format=pdf")
    assert response.status_code == 413
    assert "JSON export" in response.json()["detail"]
    # The same Run still exports completely as JSON.
    alternative = client.get(f"/api/blackbox/runs/{ident}/download?format=json")
    assert alternative.status_code == 200
    assert json.loads(alternative.content)["id"] == ident


def test_an_unfinished_run_is_refused_before_rendering():
    from app.blackbox_app import app

    config, run = saved()
    run["status"] = "running"
    runner.save(run, config)
    response = TestClient(app).get(f"/api/blackbox/runs/{run['id']}/download?format=pdf")
    assert response.status_code == 409


def test_an_unknown_format_is_refused():
    from app.blackbox_app import app

    response = TestClient(app).get(f"/api/blackbox/runs/{uuid.uuid4()}/download?format=spreadsheet")
    assert response.status_code in (404, 422)
