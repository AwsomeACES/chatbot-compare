"""Preflight readiness and evidence status: explanation never changes a recorded verdict."""

import asyncio
import copy
import io
import json
import uuid
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import blackbox_app
from app import database as db
from app.assurance import intake, readiness, sandbox, service
from app.assurance.models import Evidence, Finding, missing
from app.assurance.white import CHECKS, WhiteEngine, parse
from app.blackbox import governance

HEADERS = {"X-Studio-Request": "1"}
READY_TOOLS = {tool: "" for _, tool in CHECKS.values()}


def archive(files: dict[str, str]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return data.getvalue()


def white(test: str, verdict: str, **kw) -> dict:
    """A saved-run style White finding, built like the historical VoltKart record."""
    category, tool = CHECKS[test]
    if verdict == "not_tested":
        finding = missing("white", 0, category, test, kw.pop("reason", "No evidence."))
    else:
        finding = Finding(
            mode="white",
            category=category,
            test_id=test,
            verdict=verdict,
            evidence=[Evidence(kind="code", excerpt="fixture", file="bot.py", line=1)],
            explanation="fixture",
            checked=test,
            consequence="fixture",
            fix="Review the cited lines.",
        )
    finding.tool = tool
    finding.details = kw.pop("details", {"scanner_completed": True})
    return finding.model_copy(update=kw).model_dump()


def voltkart_like() -> dict:
    rows = [
        white("hardcoded_secrets", "fail"),
        white("dependency_vulnerabilities", "fail"),
        white("unsafe_patterns", "pass"),
        white("python_security", "pass"),
        white("prompt_injection_paths", "pass"),
        white("endpoint_controls", "exists", control=True),
    ]
    rows += [
        white(
            test,
            "not_tested",
            reason="No matching control evidence found by these limited text rules.",
        )
        for test in (
            "container_vulnerabilities",
            "guardrail_path",
            "tool_permissions",
            "pii_logging",
            "retention",
            "model_config",
            "timeouts_retries",
            "ci_safety",
        )
    ]
    return {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "modes": ["white"],
        "config": {"targets": [{"name": "VoltKart <script>alert(1)</script>"}]},
        "findings": rows,
        "ai_source_review": {
            "model": "AI assistant source review",
            "checks": [
                {
                    "test_id": "hardcoded_secrets",
                    "assessment": "false_positive",
                    "explanation": "Model identifiers, not keys <b>bold</b>.",
                }
            ],
        },
    }


def test_historical_scan_counts_and_guidance_do_not_change_saved_findings():
    run = voltkart_like()
    before = copy.deepcopy(run)
    status = readiness.evidence_status(run)
    assert run == before
    counts = status["counts"]
    assert counts["planned"] == 14 and counts["processed"] == 14
    assert counts["measured"] == 5 and counts["passed"] == 3 and counts["failed"] == 2
    assert counts["declarations"] == 1 and counts["unverified"] == 8
    rows = {row["test_id"]: row for row in status["checks"]}
    gap = rows["retention"]
    assert gap["outcome"] == "insufficient_evidence"
    assert gap["cause"] == "target_information"
    assert gap["required_evidence"] and gap["next_test"]
    assert "install" not in gap["owner_action"].lower()
    assert rows["model_config"]["cause"] == "studio_limitation"
    assert rows["hardcoded_secrets"]["outcome"] == "flagged"
    assert rows["hardcoded_secrets"]["supplemental_review"]["assessment"] == "false_positive"
    assert rows["endpoint_controls"]["outcome"] == "declaration"
    assert rows["unsafe_patterns"]["unresolved"] is False


@pytest.mark.parametrize(
    ("finding", "expected"),
    [
        ({"verdict": "not_tested", "explanation": "Pending execution."}, "not_attempted"),
        ({"verdict": "not_tested", "explanation": "Stopped before source scan."}, "not_attempted"),
        (
            {
                "verdict": "not_tested",
                "explanation": "Docker scanner sandbox is unavailable.",
                "tool": "gitleaks",
            },
            "tool_unavailable",
        ),
        (
            {"verdict": "not_tested", "explanation": "Upload a source ZIP or import a repo."},
            "missing_input",
        ),
        (
            {"verdict": "not_tested", "explanation": "x", "details": {"outcome": "tool_error"}},
            "tool_error",
        ),
        (
            {"verdict": "pass", "overridden": True, "original_finding": {"verdict": "fail"}},
            "review_cleared",
        ),
        (
            {"verdict": "fail", "overridden": True, "original_finding": {"verdict": "fail"}},
            "confirmed_defect",
        ),
        ({"verdict": "not_tested", "explanation": "Something odd."}, "unverified"),
    ],
)
def test_outcome_distinguishes_tool_failure_missing_input_and_review(finding, expected):
    assert readiness.outcome({"details": {}, **finding}) == expected


def test_preflight_from_archive_listing_without_extraction(monkeypatch):
    monkeypatch.setattr(readiness, "tool_status", AsyncMock(return_value=READY_TOOLS))
    unpinned = intake.store(
        "code", archive({"app.js": "x", "requirements.txt": "fastapi\nhttpx>=0.27\n"}), "a.zip"
    )
    report = asyncio.run(readiness.preflight(["white"], [{"code": unpinned["id"]}], [{}]))
    rows = {row["test_id"]: row for row in report["checks"]}
    assert len(rows) == len(CHECKS)
    assert rows["python_security"]["status"] == "not_applicable"
    assert rows["dependency_vulnerabilities"]["status"] == "needs_input"
    assert "exact versions" in rows["dependency_vulnerabilities"]["reason"]
    assert rows["container_vulnerabilities"]["status"] == "needs_input"
    assert rows["ci_safety"]["status"] == "needs_input"
    assert rows["guardrail_path"]["status"] == "ready"
    assert "cannot show" in rows["guardrail_path"]["best_outcome"]

    complete = intake.store(
        "code",
        archive(
            {
                "bot.py": "print('never run')",
                "requirements.txt": "fastapi==0.115.0\n",
                "Dockerfile": "FROM python:3.12-slim",
                ".github/workflows/ci.yml": "jobs: {}",
            }
        ),
        "b.zip",
    )
    report = asyncio.run(readiness.preflight(["white"], [{"code": complete["id"]}], [{}]))
    assert {row["status"] for row in report["checks"]} == {"ready"}
    assert report["counts"]["ready"] == len(CHECKS)


def test_preflight_reports_missing_input_and_unavailable_tools(monkeypatch):
    report = asyncio.run(readiness.preflight(["white", "gray", "black"], [{}], [{"url": ""}]))
    assert {row["status"] for row in report["checks"]} == {"needs_input"}
    assert {row["mode"] for row in report["checks"]} == {"white", "gray", "black"}
    record = intake.store("code", archive({"bot.py": "x"}), "c.zip")
    monkeypatch.setattr(
        readiness,
        "tool_status",
        AsyncMock(return_value={**READY_TOOLS, "trivy": "Offline trivy database is missing."}),
    )
    report = asyncio.run(readiness.preflight(["white"], [{"code": record["id"]}], [{}]))
    row = next(r for r in report["checks"] if r["test_id"] == "container_vulnerabilities")
    assert row["status"] == "tool_unavailable" and "trivy" in row["reason"]


def test_tool_status_without_docker_names_every_tool(monkeypatch):
    monkeypatch.delenv("STUDIO_SCANNER_WSL_DISTRO", raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    result = asyncio.run(readiness.tool_status(["gitleaks", "osv"]))
    assert set(result) == {"gitleaks", "osv"}
    assert all("Docker" in reason for reason in result.values())


def test_scoped_osv_snapshot_blocks_uncovered_packages(tmp_path, monkeypatch):
    (tmp_path / "scope.json").write_text(
        json.dumps({"version": "osv-package-scope-v1", "packages": [["PyPI", "FastAPI"]]})
    )
    monkeypatch.setenv("STUDIO_SCANNER_OSV_DATABASE", str(tmp_path))
    assert readiness.osv_coverage(["fastapi"]) == ""
    message = readiness.osv_coverage(["fastapi", "httpx"])
    assert "httpx" in message and "fastapi" not in message


def test_new_white_findings_record_outcome_and_specific_next_step(tmp_path, monkeypatch):
    (tmp_path / "bot.py").write_text("print('x')")
    result = parse(
        "retention",
        {
            "data": {"files": 1, "hits": {"retention": []}},
            "version": "controls-v1",
            "image_id": "sha256:test",
            "ruleset": "v1",
        },
        tmp_path,
        0,
    )
    assert result.verdict == "not_tested" and result.score is None
    assert result.details["outcome"] == "insufficient_evidence"
    assert result.details["scanner_completed"] is True
    assert "install" not in result.fix.lower()
    record = intake.store("code", archive({"bot.py": "x"}), "d.zip")
    monkeypatch.setattr(
        sandbox, "scan", AsyncMock(side_effect=sandbox.ToolUnavailable("Docker not installed"))
    )
    engine = WhiteEngine()
    results = asyncio.run(engine.run(engine.plan({"code": record["id"]})))
    assert {f.details["outcome"] for f in results} == {"tool_unavailable"}
    assert all(f.verdict == "not_tested" and f.tool for f in results)
    dependency = next(f for f in results if f.test_id == "dependency_vulnerabilities")
    assert dependency.details["inventory"]["lockfiles"] == []
    assert "not proof" in dependency.details["inventory"]["note"]


def test_preflight_route_start_records_readiness_and_exports_escape(monkeypatch):
    monkeypatch.setattr(readiness, "tool_status", AsyncMock(return_value=READY_TOOLS))
    monkeypatch.setattr(sandbox, "scan", AsyncMock(side_effect=sandbox.ToolUnavailable("none")))
    client = TestClient(blackbox_app.app)
    response = client.post(
        "/api/assurance/preflight",
        json={"modes": ["white"], "inputs": [{}], "targets": [{"url": ""}]},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["counts"]["needs_input"] == len(CHECKS)
    assert (
        client.post("/api/assurance/preflight", json={"modes": []}, headers=HEADERS).status_code
        == 422
    )

    run = voltkart_like()
    governance.append(run, "start")
    run.update(protocol_snapshot={}, audit=run.get("audit", []), input_hashes=[])
    service.checkpoint(run)
    saved = copy.deepcopy(db.get("assurance", run["id"]))
    text = client.get(f"/api/assurance/runs/{run['id']}/download?format=teammate").text
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "<b>" not in text
    assert "Evidence needed" in text and "Owner action" in text
    assert "Supplemental AI assistant source review" in text
    assert db.get("assurance", run["id"])["findings"] == saved["findings"]
    exported = client.get(f"/api/assurance/runs/{run['id']}/download?format=json").json()
    assert exported["evidence_status"]["counts"]["unverified"] == 8
    assert exported["audit_integrity"]["valid"] is True
    pdf = client.get(f"/api/assurance/runs/{run['id']}/download?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_started_run_records_preflight_and_every_check_outcome(monkeypatch):
    from app.assurance import routes
    from app.assurance.models import Assessment
    from app.blackbox.schema import JudgeSelection, Settings, Target

    monkeypatch.setattr(sandbox, "scan", AsyncMock(side_effect=sandbox.ToolUnavailable("none")))
    request = Assessment(
        settings=Settings(
            targets=[Target(url="http://localhost:8000/chat")],
            judges=[JudgeSelection(model="fixture", local=True)],
            simple_mode=True,
            consent=True,
            judge_consent=True,
        ),
        modes=["white"],
        ownership_confirmed=True,
    )

    async def execute():
        started = await routes.start(request)
        await service.TASKS[started["id"]]
        return db.get("assurance", started["id"])

    run = asyncio.run(execute())
    assert len(run["preflight"]["checks"]) == len(CHECKS)
    assert {row["status"] for row in run["preflight"]["checks"]} == {"needs_input"}
    assert any(e["event"] == "preflight_recorded" for e in run["audit"])
    assert service.integrity(run)["valid"] is True
    status = readiness.evidence_status(run)
    assert {row["outcome"] for row in status["checks"]} == {"missing_input"}
    assert status["counts"]["processed"] == 0
