"""Governance cards, reproducible config, privacy retention and lightweight progress."""

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from .governance import describe, expire_runs
from .schema import JudgeSelection, Settings

router = APIRouter(prefix="/api/studio")


class Reproduce(BaseModel):
    ownership_confirmed: bool = False
    judges: list[JudgeSelection] | None = None
    target_tokens: list[str | None] = Field(default_factory=list, max_length=4)


class Retention(BaseModel):
    days: int = Field(ge=0, le=3650)


def load(ident: uuid.UUID) -> dict:
    value = db.get("blackbox", str(ident))
    if not value:
        raise HTTPException(404, "Run not found")
    return value


def progress(run: dict) -> dict:
    bots = []
    for slot, target in enumerate(run["targets"]):
        groups = []
        for category in run["categories"]:
            cases = [c for c in run["cases"] if c["category"] == category]
            rows = [c["results"][slot] for c in cases]
            groups.append(
                {
                    "category": category,
                    "planned": len(rows),
                    "processed": sum(
                        c.get("completed", False)
                        or r["status"] in ("passed", "failed")
                        or r.get("reason", "Pending execution.") != "Pending execution."
                        for c, r in zip(cases, rows)
                    ),
                    "scored": sum(
                        r.get("score") is not None and r["status"] in ("passed", "failed")
                        for r in rows
                    ),
                    "bot_seconds": round(sum(r.get("seconds") or 0 for r in rows), 3),
                    "case_work_seconds": round(sum(c.get("elapsed_seconds", 0) for c in cases), 3),
                }
            )
        bots.append({"name": target["name"], "categories": groups})
    return {
        "run_id": run["id"],
        "status": run["status"],
        "progress": run["progress"],
        "stage": run["stage"],
        "active_seconds": run.get("active_elapsed_seconds", run.get("duration_seconds", 0)),
        "bots": bots,
    }


@router.get("/runs/{ident}/governance")
def governance(ident: uuid.UUID):
    return describe(load(ident))


@router.get("/runs/{ident}/events")
async def events(ident: uuid.UUID):
    load(ident)

    async def stream():
        previous = ""
        while True:
            run = db.get("blackbox", str(ident))
            if not run:
                return
            message = json.dumps(progress(run))
            if message != previous:
                yield "data: " + message + "\n\n"
                previous = message
            else:
                yield ": heartbeat\n\n"
            if run["status"] not in ("running", "queued"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{ident}/reproduce")
async def reproduce(ident: uuid.UUID, update: Reproduce):
    from ..blackbox_app import start
    from .studio_routes import prepare

    original = load(ident)
    from .governance import verify

    if verify(original)["valid"] is False:
        raise HTTPException(409, "Audit integrity failed; inspect this run before reproduction")
    if not original.get("protocol_snapshot"):
        raise HTTPException(422, "This legacy run lacks a full reproducible protocol snapshot")
    cfg = Settings.model_validate(original["config"])
    cfg.ownership_confirmed = update.ownership_confirmed or cfg.ownership_confirmed
    if update.judges is not None:
        # Same settings means same selected models; credentials may be re-entered.
        if [j.model_dump(exclude={"token"}) for j in update.judges] != [
            j.model_dump(exclude={"token"}) for j in cfg.judges
        ]:
            raise HTTPException(
                422, "Reproduce keeps judge configuration identical; enter credentials only"
            )
        cfg.judges = update.judges
    if update.target_tokens:
        if len(update.target_tokens) != len(cfg.targets):
            raise HTTPException(422, "Enter credentials for the original target slots")
        from pydantic import SecretStr

        for target, token in zip(cfg.targets, update.target_tokens):
            target.token = SecretStr(token) if token else None
    cfg = prepare(cfg, original["protocol_snapshot"])
    if any(not cfg.targets[i].token for i in original.get("target_auth_slots", [])) or any(
        not j.local and not j.token for j in cfg.judges
    ):
        raise HTTPException(
            422, "Re-enter the original target/judge API keys; keys are not stored in history"
        )
    cfg._reproduced_from = original["id"]
    return await start(cfg)


@router.put("/runs/{ident}/retention")
def retention(ident: uuid.UUID, value: Retention):
    from .runner import ACTIVE, save
    from .studio_engine import audit

    run = load(ident)
    if run["id"] in ACTIVE:
        raise HTTPException(409, "Set retention before starting, or after the run finishes")
    audit(
        run,
        "retention_changed",
        previous_days=run["config"].get("retention_days", 0),
        days=value.days,
    )
    run["config"]["retention_days"] = value.days
    save(run)
    return {"saved": True, "days": value.days}


async def retention_worker() -> None:
    """Enforce opt-in retention periodically and at app startup, not only on export."""
    from .runner import ACTIVE

    while True:
        expire_runs(set(ACTIVE))
        from ..assurance.service import expire

        expire()
        await asyncio.sleep(3600)
