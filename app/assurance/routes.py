"""Local Studio API for assurance planning, review, retention and evidence exports."""

import asyncio
import io
import time
import uuid
import zipfile
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import database as db
from ..blackbox import governance
from ..blackbox.runner import ACTIVE
from ..blackbox.schema import JudgeSelection
from ..blackbox.studio_routes import JudgesUpdate
from . import intake, readiness, service
from .models import Assessment, BotInputs, Mode
from .privacy import safe
from .white import WhiteEngine

router = APIRouter(prefix="/api/assurance")


def get_run(ident: uuid.UUID) -> dict:
    run = db.get("assurance", str(ident))
    if not run:
        raise HTTPException(404, "Assessment not found.")
    return run


def require_integrity(run: dict) -> None:
    """Reject edits that would re-seal altered or unverified saved evidence."""
    if service.integrity(run).get("valid") is not True:
        raise HTTPException(
            409, "Audit or finding integrity failed; this record cannot be modified."
        )


@router.get("/capabilities")
def capabilities():
    from .gray import CHECKS

    return {
        "gray": {k: v for k, (_, v) in CHECKS.items()},
        "white": WhiteEngine().required_inputs(),
        "unlocks": intake.UNLOCKS,
        "limits": intake.LIMITS,
        "private_default": "Local judge only",
        "code_execution": False,
    }


@router.post("/inputs/{kind}")
async def upload(kind: str, file: UploadFile = File(...)):
    raw = bytearray()
    try:
        while chunk := await file.read(65536):
            raw.extend(chunk)
            if len(raw) > intake.LIMITS["max_bytes"]:
                raise HTTPException(413, "Input exceeds 20 MB.")
        return await asyncio.to_thread(intake.store, kind, bytes(raw), file.filename or "upload")
    except (
        ValueError,
        OSError,
        UnicodeError,
        RecursionError,
        zipfile.BadZipFile,
    ) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


class Repository(BaseModel):
    url: str = Field(max_length=2048)
    ownership_confirmed: bool


@router.post("/repository")
async def repository(value: Repository):
    parsed = urlsplit(value.url)
    pieces = parsed.path.strip("/").split("/")
    import re

    if not value.ownership_confirmed:
        raise HTTPException(422, "Confirm ownership or written permission first.")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.query
        or parsed.fragment
        or len(pieces) not in (2, 4)
    ):
        raise HTTPException(
            422,
            "Use https://github.com/owner/repo or /tree/ref for a public repository.",
        )
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in pieces) or (
        len(pieces) == 4 and pieces[2] != "tree"
    ):
        raise HTTPException(422, "Invalid repository path.")
    owner, repo = pieces[:2]
    refs = [pieces[3]] if len(pieces) == 4 else ["main", "master"]
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            for ref in refs:
                url = f"https://codeload.github.com/{quote(owner)}/{quote(repo)}/zip/{quote(ref)}"
                async with client.stream("GET", url) as response:
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > intake.LIMITS["max_bytes"]:
                            raise ValueError("Repository exceeds the source-only size limit.")
                    result = await asyncio.to_thread(
                        intake.store, "code", bytes(raw), repo + ".zip"
                    )
                    result["ref"] = ref
                    return result
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            422,
            "Repository import failed or exceeded source limits; upload a source ZIP instead.",
        ) from exc
    raise HTTPException(
        404,
        "Public repository/ref not found; private repositories require a source ZIP.",
    )


class Preflight(BaseModel):
    modes: list[Mode] = Field(min_length=1, max_length=3)
    inputs: list[BotInputs] = Field(default_factory=list, max_length=4)
    targets: list[dict] = Field(default_factory=list, max_length=4)


async def readiness_report(modes: list[str], inputs: list[dict], targets: list[dict]) -> dict:
    """Readiness never blocks a start; a failed check of readiness is itself recorded."""
    try:
        return await readiness.preflight(modes, inputs or [{} for _ in targets], targets)
    except (ValueError, OSError, KeyError) as exc:
        return {"checks": [], "counts": {}, "error": type(exc).__name__}


@router.post("/preflight")
async def preflight(value: Preflight):
    """Show Ready, Needs input, Tool unavailable or Not applicable before a test starts."""
    inputs = [i.model_dump() for i in value.inputs] or [{} for _ in value.targets] or [{}]
    targets = [{k: v for k, v in t.items() if k in ("url", "archive_id")} for t in value.targets]
    return await readiness_report(value.modes, inputs, targets)


@router.post("/runs")
async def start(request: Assessment):
    inputs = [i.model_dump() for i in request.inputs] or [{} for _ in request.settings.targets]
    targets = [
        {"url": t.url, "archive_id": getattr(t, "archive_id", "")} for t in request.settings.targets
    ]
    report = await readiness_report(request.modes, inputs, targets)
    try:
        return service.start(request, preflight=report)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs")
def list_runs():
    return db.record_summaries(
        "assurance",
        ("id", "status", "modes", "created_at", "blackbox_run_id", "combined"),
    )


@router.get("/runs/{ident}")
def status(ident: uuid.UUID):
    run = get_run(ident)
    # A process crash leaves durable evidence; the UI must offer explicit resume.
    if (
        run["status"] in ("running", "queued")
        and str(ident) not in service.TASKS
        and service.integrity(run).get("valid") is True
    ):
        run["status"] = "interrupted"
        governance.append(
            run,
            "recovery_waiting",
            reason="Process restarted; re-enter missing credentials and resume.",
        )
        service.checkpoint(run)
    result = service.export(run, include_child=False)
    child = db.get("blackbox", run.get("blackbox_run_id", ""))
    if child:
        result["live_blackbox"] = {
            "progress": child["progress"],
            "status": child["status"],
            "stage": child["stage"],
            "studio": child.get("studio"),
            "costs": child.get("costs"),
        }
    result.pop("blackbox", None)  # Separate full evidence export; don't resend it every poll.
    return result


@router.post("/runs/{ident}/resume")
async def resume(ident: uuid.UUID, request: Assessment):
    original = get_run(ident)
    if not service.integrity(original).get("valid"):
        raise HTTPException(409, "Audit integrity failed; do not resume this record.")
    try:
        return service.start(request, original)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs/{ident}/stop")
def stop(ident: uuid.UUID):
    run = get_run(ident)
    if str(ident) in service.STOPS:
        service.STOPS[str(ident)].set()
    if run.get("blackbox_run_id") in ACTIVE:
        ACTIVE[run["blackbox_run_id"]].set()
    return {"stopping": True}


@router.put("/runs/{ident}/judges")
async def update_judges(ident: uuid.UUID, value: JudgesUpdate):
    from ..blackbox.judge_recovery import identity
    from ..blackbox.studio_engine import LIVE_CONFIGS, LIVE_RUNS

    cfg = LIVE_CONFIGS.get(str(ident))
    if cfg is None or str(ident) not in service.TASKS:
        raise HTTPException(409, "This assessment is inactive; use Resume.")
    if not value.consent or not any(not j.fallback for j in value.judges):
        raise HTTPException(422, "Choose a primary judge and confirm transcript sharing.")
    require_integrity(get_run(ident))
    run = LIVE_RUNS[str(ident)]
    require_integrity(run)
    cfg._used_secrets.extend(j.token.get_secret_value() for j in cfg.judges if j.token)
    cfg.judges = value.judges
    first = next(j for j in cfg.judges if not j.fallback)
    cfg.judge_url, cfg.judge_model, cfg.judge_token = (
        first.url,
        first.model,
        first.token,
    )
    cfg.judge_local_model = first.local
    run["config"]["judges"] = [j.model_dump(exclude={"token"}) for j in cfg.judges]
    governance.append(
        run,
        "judge_key_switch",
        judges=[{"model": j.model, "key_endpoint_fingerprint": identity(j)} for j in cfg.judges],
        note="In-flight calls keep their original credentials; future cases use the new selection.",
    )
    service.checkpoint(run)
    return {"updated": True}


@router.post("/runs/{ident}/reproduce")
async def reproduce(ident: uuid.UUID, request: Assessment):
    original = get_run(ident)
    if not service.integrity(original).get("valid"):
        raise HTTPException(409, "Source audit/finding integrity failed.")
    before, after = original["config"], service.public_settings(request.settings)
    for key in (
        "targets",
        "judges",
        "references",
        "policy",
        "scope",
        "repeat_counts",
        "category_weights",
        "seed",
    ):
        if before.get(key) != after.get(key):
            raise HTTPException(
                422,
                "Reproduce needs the saved bot, models, cases and rules. Re-enter credentials without changing the model.",
            )
    if (
        request.modes != original["modes"]
        or request.private_cloud_opt_in != original["private_cloud_opt_in"]
    ):
        raise HTTPException(422, "Retain the same modes and private-sharing configuration.")
    expected = {(r["bot"], r["kind"]): r["sha256"] for r in original["input_hashes"]}
    supplied = {}
    for slot, fields in enumerate(request.inputs):
        for kind, input_id in fields.model_dump().items():
            if input_id:
                try:
                    _, record = intake.load(input_id, kind)
                except (ValueError, OSError) as exc:
                    raise HTTPException(
                        422,
                        "Re-upload the original deleted inputs before reproduction.",
                    ) from exc
                supplied[(slot, kind)] = record["sha256"]
    if expected != supplied:
        raise HTTPException(
            422,
            "Reproduce requires identical original input hashes; re-upload deleted inputs.",
        )
    request.settings._protocol_override = original["protocol_snapshot"]
    request.settings._reproduced_from = str(ident)
    request.settings.price_snapshot_id = before.get("price_snapshot_id", "")
    return service.start(request)


class ExplainRequest(BaseModel):
    judges: list[JudgeSelection] = Field(default_factory=list, max_length=3)
    cloud_consent: bool = False


@router.post("/runs/{ident}/explain")
async def explain_run(ident: uuid.UUID, value: ExplainRequest):
    """Add a supplemental AI explanation of White findings; verdicts never change."""
    from ..blackbox.schema import Settings
    from .explain import explain

    run = get_run(ident)
    require_integrity(run)
    if str(ident) in service.TASKS:
        raise HTTPException(409, "Wait for the test to finish before asking for an explanation.")
    if "white" not in run.get("modes", []):
        raise HTTPException(422, "Only White-box results can be explained here.")
    try:
        config = Settings.model_validate({**run["config"], "judges": value.judges})
    except ValueError as exc:
        raise HTTPException(422, "The saved test settings could not be loaded.") from exc
    result = await explain(run, config, value.cloud_consent)
    run = get_run(ident)  # Re-read: the explanation call may take a while.
    require_integrity(run)
    run.setdefault("ai_explanations", []).append(result)
    governance.append(
        run,
        "ai_explanation",
        status=result["status"],
        model=result.get("model", ""),
        cloud_consent=value.cloud_consent,
        payload_hash=result["payload_hash"],
        attempts=[
            {k: a.get(k) for k in ("model", "local", "status", "output_hash")}
            for a in result["attempts"]
        ],
        note="Supplemental explanation; findings unchanged.",
    )
    service.checkpoint(run)
    return result


class Review(BaseModel):
    bot: int = Field(ge=0, le=3)
    mode: str
    test_id: str
    false_positive: bool
    reason: str = Field(min_length=10, max_length=2000)


class CanaryLogs(BaseModel):
    bot: int = Field(ge=0, le=3)
    logs: uuid.UUID


@router.post("/runs/{ident}/canary-logs")
def canary_logs(ident: uuid.UUID, value: CanaryLogs):
    from ..blackbox.schema import Target
    from .gray import log_finding, runtime_expectations
    from .runtime_evidence import RUNTIME_CHECKS, evaluate

    run = get_run(ident)
    require_integrity(run)
    if str(ident) in service.TASKS:
        raise HTTPException(
            409, "Wait for the synthetic canary chat to finish before adding its logs."
        )
    if value.bot >= len(run["config"]["targets"]):
        raise HTTPException(422, "Unknown bot.")
    planted = any(
        f["bot"] == value.bot and f["test_id"] == "canary_chat" and f["evidence"]
        for f in run["findings"]
    )
    saved = {
        f["test_id"]: f
        for f in run["findings"]
        if f["mode"] == "gray" and f["bot"] == value.bot and f["test_id"] in RUNTIME_CHECKS
    }
    if not planted and not saved:
        raise HTTPException(422, "No recorded synthetic canary conversation for this bot.")
    try:
        data, record = intake.load(str(value.logs), "logs")
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Upload the new structured logs first.") from exc
    target = Target.model_validate(run["config"]["targets"][value.bot])
    findings = []
    if planted:
        findings.append(
            log_finding(
                "canary_logging", data, record.get("metadata", {}), target, value.bot, str(ident)
            )
        )
    policy = run.get("protocol_snapshot", {}).get("gray_suite", {}).get("runtime_policy", {})
    for test, old in saved.items():
        # Reuse the limits declared when the run started; a later upload cannot change them.
        expectations = old.get("details", {}).get("expectations") or runtime_expectations(
            {}, target, policy
        )
        result = evaluate(test, data, str(ident), value.bot, expectations)
        result.details["expectations"] = expectations
        findings.append(result)
    service.record_findings(run, findings)
    finding = findings[0]
    governance.append(
        run,
        "canary_logs_added",
        bot=value.bot,
        input_hash=record["sha256"],
        verdict=finding.verdict,
        verdicts={f.test_id: f.verdict for f in findings},
    )
    run["input_hashes"].append(
        {
            "bot": value.bot,
            "kind": "logs",
            "sha256": record["sha256"],
            "input_id": str(value.logs),
        }
    )
    if not run.get("upload_retention_days"):
        intake.remove(str(value.logs))
    service.checkpoint(run)
    return {"finding": finding.model_dump(), "findings": [f.model_dump() for f in findings]}


@router.post("/runs/{ident}/review")
def review(ident: uuid.UUID, value: Review):
    run = get_run(ident)
    require_integrity(run)
    if str(ident) in service.TASKS:
        raise HTTPException(409, "Stop the assessment before reviewing findings.")
    if not value.reason.strip() or len(value.reason.strip()) < 10:
        raise HTTPException(422, "Write a meaningful review reason.")
    finding = next(
        (
            f
            for f in run["findings"]
            if f["bot"] == value.bot and f["mode"] == value.mode and f["test_id"] == value.test_id
        ),
        None,
    )
    if not finding:
        raise HTTPException(404, "Finding not found.")
    if value.false_positive and (finding["verdict"] == "not_tested" or not finding["evidence"]):
        raise HTTPException(422, "Missing evidence cannot be overridden into a pass.")
    previous = {k: finding[k] for k in ("verdict", "score", "severity")}
    governance.append(
        run,
        "finding_review",
        old=previous,
        new={
            "verdict": "pass" if value.false_positive else previous["verdict"],
            "score": (100 if previous["score"] is not None else None)
            if value.false_positive
            else previous["score"],
        },
        bot=value.bot,
        mode=value.mode,
        test_id=value.test_id,
        false_positive=value.false_positive,
        reason=str(safe(value.reason)),
    )
    finding.setdefault("original_finding", {k: v for k, v in finding.items()})
    finding.update(overridden=True, review=False, review_reason=str(safe(value.reason)))
    if value.false_positive:
        finding.update(
            verdict="pass",
            score=100 if finding["score"] is not None else None,
            severity="Pass",
        )
    # Preserve original evidence and verdict; never remove the finding.
    service.checkpoint(run)
    return {"saved": True}


class Retention(BaseModel):
    days: int = Field(ge=0, le=30)


@router.put("/runs/{ident}/retention")
def retention(ident: uuid.UUID, value: Retention):
    run = get_run(ident)
    require_integrity(run)
    governance.append(
        run,
        "retention_changed",
        previous=run.get("upload_retention_days", 0),
        days=value.days,
    )
    run.update(
        upload_retention_days=value.days,
        upload_expires_at=time.time() + value.days * 86400,
    )
    service.checkpoint(run)
    service.expire()
    return {"saved": True, "note": "Already deleted uploads cannot be restored."}


@router.delete("/runs/{ident}")
def delete(ident: uuid.UUID):
    run = get_run(ident)
    if str(ident) in service.TASKS:
        raise HTTPException(409, "Stop the assessment before deleting it.")
    service.release_inputs(run)
    from ..blackbox.governance import purge_run

    purge_run(str(ident))
    from ..blackbox.judge_calibration import purge_source

    purge_source(assessment_id=str(ident))
    from ..blackbox import metering

    with db.connect() as connection:
        metering.init_db(connection)
        connection.execute("DELETE FROM usage_events WHERE run_id=?", (str(ident),))
    db.delete("assurance", str(ident))
    return {
        "deleted": True,
        "note": "Linked black-box history remains separately deletable.",
    }


@router.get("/runs/{ident}/download")
def download(ident: uuid.UUID, format: str = "json"):
    import json

    run = service.export(get_run(ident))
    if format == "json":
        return Response(
            json.dumps(run, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="assurance-{ident}.json"'},
        )
    if format == "teammate":
        return Response(
            readiness.teammate_markdown(run),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="assurance-{ident}-teammate.md"'
            },
        )
    if format != "pdf":
        raise HTTPException(422, "Choose JSON, PDF or teammate.")
    from html import escape

    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    output = io.BytesIO()
    styles = getSampleStyleSheet()
    combined = run["combined"]
    blocks = [
        Paragraph("AI Agent Studio assurance report", styles["Title"]),
        Paragraph(
            escape(f"{run['id']} | {combined['assurance']} | {combined['verdict']}"),
            styles["Normal"],
        ),
        Paragraph(escape(combined["reason"]), styles["Normal"]),
    ]
    status = run["evidence_status"]
    counts = status["counts"]
    blocks += [
        Paragraph("Evidence status", styles["Heading2"]),
        Paragraph(
            escape(
                f"{counts['planned']} checks planned, {counts['processed']} processed. "
                f"Measured: {counts['measured']} ({counts['passed']} passed, "
                f"{counts['failed']} need attention). Declarations only: "
                f"{counts['declarations']}. Not verified: {counts['unverified']}. "
                f"Waiting for human review: {counts['human_review']}."
            ),
            styles["Normal"],
        ),
        Paragraph(escape(status["notice"] + " " + status["historical_note"]), styles["Normal"]),
    ]
    review = readiness.supplemental(run)
    if review:
        blocks += [
            Paragraph("AI source review provenance", styles["Heading2"]),
            Paragraph(
                escape(
                    f"Source: {review.get('model', '')}. {review.get('provider_model', '')} "
                    f"{review.get('purpose', '')} Automation status: "
                    f"{review.get('automation_status', 'not recorded')}"
                ),
                styles["Normal"],
            ),
        ]
    guidance = {row["key"]: row for row in status["checks"]}
    for f in sorted(
        run["findings"],
        key=lambda f: {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Pass": 4}[f["severity"]],
    ):
        blocks += [
            Spacer(1, 8),
            Paragraph(
                escape(
                    f"Bot {f['bot'] + 1} / {f['mode']} / {f['test_id']} / {f['verdict']} / {f['confidence']} confidence"
                ),
                styles["Heading3"],
            ),
        ]
        for label, key in (
            ("What we checked", "checked"),
            ("What we found", "explanation"),
            ("Why it matters", "consequence"),
            ("How to fix it", "fix"),
        ):
            blocks.append(Paragraph(escape(label + ": " + f[key]), styles["Normal"]))
        row = guidance.get(f"{f['bot']}:{f['mode']}:{f['test_id']}")
        if row:
            blocks.append(
                Paragraph(
                    escape(
                        f"Result type: {row['outcome_label']} ({row['cause_label']}). {row['why']}"
                    ),
                    styles["Normal"],
                )
            )
            if row["required_evidence"]:
                blocks.append(
                    Paragraph(
                        escape("Evidence needed: " + "; ".join(row["required_evidence"])),
                        styles["Normal"],
                    )
                )
            if row["next_test"]:
                blocks.append(
                    Paragraph(
                        escape(
                            f"Owner action: {row['owner_action']} Next test: {row['next_test']}"
                        ),
                        styles["Normal"],
                    )
                )
            extra = row.get("supplemental_review")
            if extra:
                blocks.append(
                    Paragraph(
                        escape(
                            f"Supplemental {extra['source']}: "
                            f"{extra['assessment'].replace('_', ' ')}. {extra['explanation']} "
                            f"({extra['note']})"
                        ),
                        styles["Normal"],
                    )
                )
        for e in f["evidence"]:
            blocks.append(
                Paragraph(
                    escape(f"{e.get('file', '')}:{e.get('line') or ''} {e['excerpt']}"),
                    styles["Normal"],
                )
            )
    blocks += [
        Spacer(1, 10),
        Paragraph("Tokens and cost — all selected modes", styles["Heading2"]),
    ]
    from ..blackbox.cost_summary import money

    for role, total in run["assurance_costs"].items():
        amount = total["exact_micro_usd"] if total["cost_micro_usd"] is not None else None
        blocks.append(
            Paragraph(
                escape(
                    f"{role}: {money(amount, local=bool(total['calls']) and total['local_calls'] == total['calls'])}; {total['input_tokens']} input / {total['output_tokens']} output tokens"
                ),
                styles["Normal"],
            )
        )
    blocks += [
        Paragraph("Governance (informational, not certification)", styles["Heading2"]),
        Paragraph(
            escape(
                json.dumps(
                    {
                        "modes": run["modes"],
                        "audit": run["audit_integrity"],
                        "inputs": run["input_hashes"],
                        "mapping": combined["mapping"],
                    }
                )
            ),
            styles["Normal"],
        ),
    ]
    SimpleDocTemplate(output).build(blocks)
    return Response(
        output.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="assurance-{ident}.pdf"'},
    )
