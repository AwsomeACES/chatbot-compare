"""Local API for human-aligned Judge calibration (C02). UUID-validated; no filesystem paths."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .. import database as db
from . import judge_calibration as cal
from .calibration_models import (
    KIND_SET,
    AddItems,
    CompatibilityRequest,
    CreateSet,
    Freeze,
    LabelUpdate,
    ResumeEvaluation,
    Selection,
    StartEvaluation,
)
from .judge_credentials import key_for_judge

router = APIRouter(prefix="/api/studio/judge-calibration")


def guarded(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except cal.CalibrationError as exc:
        raise HTTPException(exc.status, str(exc)) from None


def source_view(item: dict) -> dict:
    """Selection preview: identity and the first prompt only; never original Judge output."""
    transcript = item["payload"]["transcript"]
    return {
        "case_id": item["source"]["case_id"],
        "base_case_id": item["source"]["base_case_id"],
        "bot_slot": item["source"]["bot_slot"],
        "bot_name": item["source"]["bot_name"],
        "repeat": item["source"]["repeat"],
        "category": item["category"],
        "bias_subtype": item["bias_subtype"],
        "turns": len(transcript),
        "preview": str(transcript[0].get("input", ""))[:200] if transcript else "",
    }


@router.get("/policy")
def get_policy():
    return {
        "policy": cal.policy().model_dump(),
        "warnings": cal.WARNINGS,
        "limitations": cal.LIMITATIONS,
    }


@router.get("/sources/{kind}/{ident}/items")
def eligible(kind: str, ident: uuid.UUID):
    if kind not in ("blackbox_run", "assurance_assessment"):
        raise HTTPException(404, "Unknown source kind.")

    def work():
        run, assessment = cal.resolve_source(kind, str(ident))
        items, excluded = cal.eligible_items(run, assessment)
        return {
            "run_id": run["id"],
            "assessment_id": assessment,
            "eligible": [source_view(i) for i in items],
            "excluded": excluded,
            "note": "Derived aggregates and measured latency are not independent samples.",
        }

    return guarded(work)


@router.post("/sets", status_code=201)
def create(request: CreateSet):
    return guarded(cal.create_set, request.name, request.selection)


@router.get("/sets")
def list_sets():
    return [cal.summarize_set(s) for s in db.all_records(KIND_SET)]


@router.get("/sets/{ident}")
def get_set(ident: uuid.UUID):
    return guarded(lambda: cal.set_detail(cal.get_set(str(ident))))


@router.post("/sets/{ident}/items")
def add_items(ident: uuid.UUID, request: AddItems):
    return guarded(cal.add_items, str(ident), request.expected_set_revision, request.selection)


@router.delete("/sets/{ident}/items/{item_id}")
def remove_item(ident: uuid.UUID, item_id: uuid.UUID, expected_set_revision: int = Query(ge=0)):
    return guarded(cal.remove_item, str(ident), expected_set_revision, str(item_id))


@router.put("/sets/{ident}/items/{item_id}/label")
def label(ident: uuid.UUID, item_id: uuid.UUID, update: LabelUpdate):
    return guarded(cal.save_label, str(ident), str(item_id), update)


@router.post("/sets/{ident}/freeze")
def freeze(ident: uuid.UUID, request: Freeze):
    return guarded(
        cal.freeze,
        str(ident),
        request.expected_set_revision,
        request.holdout_percent,
        request.holdout_seed,
    )


@router.delete("/sets/{ident}")
def delete_set(ident: uuid.UUID):
    return guarded(cal.delete_set, str(ident))


def token_for(judge) -> str:
    if judge.token:
        return judge.token.get_secret_value()
    return "" if judge.local else key_for_judge(judge.url)


@router.post("/sets/{ident}/evaluations", status_code=202)
async def start(ident: uuid.UUID, request: StartEvaluation):
    evaluation = guarded(cal.start, str(ident), request, token_for)
    tokens = {
        "primary": token_for(request.judge),
        "fallbacks": [f.token.get_secret_value() if f.token else "" for f in request.fallbacks],
    }
    guarded(cal.launch, evaluation["id"], tokens)
    return {"id": evaluation["id"], "status": "queued"}


@router.get("/evaluations")
def list_evaluations(set_id: uuid.UUID | None = None):
    return cal.list_evaluations(str(set_id) if set_id else None)


@router.get("/evaluations/{ident}")
def get_evaluation(ident: uuid.UUID):
    return guarded(lambda: cal.view_evaluation(cal.get_evaluation(str(ident))))


@router.post("/evaluations/{ident}/cancel")
def cancel(ident: uuid.UUID):
    return guarded(cal.cancel, str(ident))


@router.post("/evaluations/{ident}/resume", status_code=202)
async def resume(ident: uuid.UUID, request: ResumeEvaluation):
    def check():
        record = cal.reconcile(cal.get_evaluation(str(ident)))
        if record.get("invalidated"):
            raise cal.Conflict("Source evidence was deleted; this evaluation cannot resume.")
        if record["status"] not in cal.RESUMABLE:
            raise cal.Conflict(
                f"Evaluation is {record['status']}; only interrupted or cancelled work resumes."
            )
        return record

    record = guarded(check)
    from .schema import JudgeSelection

    primary = JudgeSelection(
        model=record["judge"]["model"],
        url=record["judge"]["endpoint"],
        local=record["judge"]["local"],
    )
    tokens = {"primary": request.token or token_for(primary), "fallbacks": request.fallback_tokens}
    guarded(cal.launch, record["id"], tokens)
    return {"id": record["id"], "status": "resuming"}


@router.post("/compatibility")
def compatibility(request: CompatibilityRequest):
    """Alignment status for the currently selected Judge; read-only, no provider call."""
    return cal.resolve_compatibility(request.model, request.url, request.policy, request.scope)


@router.get("/evaluations/{ident}/export")
def export(ident: uuid.UUID, format: str = Query(default="json", pattern="^(json|markdown)$")):
    body = guarded(cal.export_evaluation, str(ident))
    body["exported_at"] = datetime.now(timezone.utc).isoformat()
    if format == "markdown":
        from .reports import calibration_markdown

        return Response(
            calibration_markdown(body),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="judge-calibration-{ident}.md"'},
        )
    return Response(
        json.dumps(body, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="judge-calibration-{ident}.json"'},
    )


@router.delete("/evaluations/{ident}")
def delete_evaluation(ident: uuid.UUID):
    return guarded(cal.delete_evaluation, str(ident))


__all__ = ["router", "Selection"]
