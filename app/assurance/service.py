"""Concurrent plug-in planner with durable mode checkpoints and explicit coverage."""

import asyncio
import copy
import time
import uuid

from .. import database as db
from ..blackbox import governance, metering, pricing
from ..blackbox.execution_cache import digest
from ..blackbox.schema import Settings
from ..blackbox.studio_engine import LIVE_CONFIGS, LIVE_RUNS, settings_file
from .black import BlackEngine
from .combine import combine
from .gray import GrayEngine
from .intake import load, remove
from .models import Assessment, Finding, missing
from .privacy import safe
from .white import WhiteEngine

TASKS: dict[str, asyncio.Task] = {}
STOPS: dict[str, asyncio.Event] = {}


def public_settings(config: Settings) -> dict:
    public = config.model_dump(
        exclude={"judge_token", "secondary_judge_token", "targets", "judges"}
    )
    public["targets"] = [t.model_dump(exclude={"token"}) for t in config.targets]
    public["judges"] = [j.model_dump(exclude={"token"}) for j in config.judges]
    return public


def checkpoint(run: dict) -> None:
    run["combined"] = combine([Finding.model_validate(f) for f in run["findings"]], run["modes"])
    governance.append(
        run,
        "state_checkpoint",
        findings_hash=digest(run["findings"]),
        planned_hash=digest(run.get("planned_checks", [])),
    )
    db.save("assurance", run)


def record_findings(run: dict, findings: list[Finding]) -> None:
    """Merge by planned identity: a short/failed adapter must not erase planned checks."""
    indexed = {(f["mode"], f["bot"], f["test_id"]): f for f in run["findings"]}
    for finding in findings:
        key = (finding.mode, finding.bot, finding.test_id)
        if key not in indexed:
            raise ValueError("Engine returned an unplanned finding identity.")
        indexed[(finding.mode, finding.bot, finding.test_id)] = finding.model_dump()
    run["findings"] = list(indexed.values())


def integrity(run: dict) -> dict:
    result = governance.verify(run)
    seal = next(
        (e for e in reversed(run.get("audit", [])) if e["event"] == "state_checkpoint"), None
    )
    if seal and (
        seal["findings_hash"] != digest(run["findings"])
        or seal["planned_hash"] != digest(run.get("planned_checks", []))
    ):
        return {"valid": False, "reason": "Saved findings or plan differ from their anchored hash."}
    return result


def start(request: Assessment, original: dict | None = None) -> dict:
    if len(TASKS) >= 2:
        raise ValueError("Two assurance assessments are active; wait or stop one first.")
    config = request.settings
    config.ownership_confirmed = request.ownership_confirmed
    config.simple_mode = True
    if config._protocol_override is None:
        config._protocol_override = settings_file()
    from ..config import ROOT

    if "gray_suite" not in config._protocol_override:
        import json

        config._protocol_override["gray_suite"] = json.loads(
            (ROOT / "app/studio/gray-v1.json").read_text()
        )
    config.local_classifiers = config.local_classifiers or config._protocol_override.get(
        "local_classifiers", {}
    )
    pricing.pin(config)
    if "black" in request.modes:
        from ..blackbox.studio_routes import prepare

        config = prepare(
            config, original.get("protocol_snapshot") if original else config._protocol_override
        )
    inputs = request.inputs or [dict() for _ in config.targets]
    inputs = [i.model_dump() if hasattr(i, "model_dump") else i for i in inputs]
    hashes = []
    for slot, fields in enumerate(inputs):
        for kind, ident in fields.items():
            if ident:
                _, metadata = load(ident, kind)
                hashes.append(
                    {"bot": slot, "kind": kind, "sha256": metadata["sha256"], "input_id": ident}
                )
    if original:
        if original["id"] in TASKS:
            raise ValueError("This assessment is already active.")
        old = original["config"]
        previous_hashes = {
            (r["bot"], r["kind"]): r["sha256"] for r in original.get("input_hashes", [])
        }
        if any(
            previous_hashes.get((r["bot"], r["kind"]), r["sha256"]) != r["sha256"] for r in hashes
        ):
            raise ValueError(
                "Resume requires identical input hashes. Start a new assessment for changed private inputs."
            )
        # A resume may change judge credentials/models, not the experimental design.
        for key in ("targets", "references", "policy", "scope", "repeat_counts", "seed"):
            if public_settings(config).get(key) != old.get(key):
                raise ValueError(
                    "Resume must retain the original bot, cases, reference facts and scope."
                )
        if request.modes != original["modes"]:
            raise ValueError("Resume must use the original selected engines.")
        run = original
        run["status"] = "queued"
        run["config"]["judges"] = public_settings(config)["judges"]
    else:
        run = {
            "id": str(uuid.uuid4()),
            "config": public_settings(config),
            "protocol_snapshot": config._protocol_override or settings_file(),
            "modes": request.modes,
            "status": "queued",
            "created_at": time.time(),
            "findings": [],
            "engine_status": {m: "queued" for m in request.modes},
            "audit": [],
            "blackbox_run_id": "",
            "inputs": inputs,
            "reproduced_from": config._reproduced_from,
        }
    run.update(
        input_hashes=hashes,
        private_cloud_opt_in=request.private_cloud_opt_in,
        upload_retention_days=request.upload_retention_days,
        inputs=inputs,
    )
    # Seed every selected check before execution so crashes cannot erase planned work.
    planners = {
        "white": WhiteEngine(),
        "gray": GrayEngine(config, run["id"], request.private_cloud_opt_in, asyncio.Event()),
        "black": BlackEngine(config, lambda ident: None),
    }
    planned = []
    for mode in request.modes:
        for slot, fields in enumerate(inputs):
            if mode == "black" and slot:
                continue
            for item in planners[mode].plan({**fields, "bot": slot}):
                planned.append(
                    {
                        "mode": mode,
                        "bot": item["bot"],
                        "category": item["category"],
                        "test": item["test"],
                    }
                )
                if not any(
                    f["mode"] == mode and f["bot"] == item["bot"] and f["test_id"] == item["test"]
                    for f in run["findings"]
                ):
                    run["findings"].append(
                        missing(
                            mode, item["bot"], item["category"], item["test"], "Pending execution."
                        ).model_dump()
                    )
    run["planned_checks"] = planned
    LIVE_CONFIGS[run["id"]] = config
    LIVE_RUNS[run["id"]] = run
    governance.append(
        run,
        "ownership_confirmed",
        written_permission_or_owner=True,
        selected_modes=request.modes,
        private_cloud_opt_in=request.private_cloud_opt_in,
        input_hashes=hashes,
        price_snapshot=config.price_snapshot_id,
        scanner_rules_version="source-audit-v1",
    )
    checkpoint(run)
    stop = STOPS[run["id"]] = asyncio.Event()
    task = asyncio.create_task(execute(run, request, config, stop))
    TASKS[run["id"]] = task
    return {"id": run["id"], "modes": request.modes}


async def execute(run: dict, request: Assessment, config: Settings, stop: asyncio.Event) -> None:
    started = time.monotonic()
    run["status"] = "running"
    checkpoint(run)

    def source_progress(findings: list[Finding]) -> None:
        record_findings(run, findings)
        governance.append(
            run,
            "scanner_progress",
            tests=[f.test_id for f in findings],
            tools=sorted({f.tool for f in findings if f.tool}),
        )
        checkpoint(run)

    white = WhiteEngine(on_progress=source_progress)
    gray = GrayEngine(config, run["id"], request.private_cloud_opt_in, stop)

    def attach(ident: str) -> None:
        run["blackbox_run_id"] = ident
        governance.append(run, "blackbox_linked", source_run=ident)
        checkpoint(run)

    def black_progress(findings: list[Finding]) -> None:
        record_findings(run, findings)
        checkpoint(run)

    black = BlackEngine(config, attach, run.get("blackbox_run_id", ""), black_progress)
    engines = {"black": black, "gray": gray, "white": white}

    async def mode_job(mode: str) -> None:
        run["engine_status"][mode] = "running"
        checkpoint(run)
        plans = []
        for slot, fields in enumerate(run["inputs"]):
            if mode == "black" and slot:
                continue
            plans.extend(engines[mode].plan({**fields, "bot": slot}))
        try:
            if mode == "black":
                findings = await engines[mode].run(plans)
                record_findings(run, findings)
            else:
                # Persist every check, not merely an entire engine at completion.
                for row in plans:
                    if stop.is_set():
                        result = [
                            missing(
                                mode,
                                row["bot"],
                                row["category"],
                                row["test"],
                                "Stopped by user before this check.",
                            )
                        ]
                    else:
                        old = next(
                            (
                                f
                                for f in run["findings"]
                                if f["mode"] == mode
                                and f["bot"] == row["bot"]
                                and f["test_id"] == row["test"]
                            ),
                            None,
                        )
                        if old and old["verdict"] != "not_tested":
                            continue
                        # White checks share one extracted source/tool result bundle per bot.
                        if mode == "white":
                            continue
                        result = await engines[mode].run([row])
                    for finding in result:
                        run["findings"] = [
                            f
                            for f in run["findings"]
                            if not (
                                f["mode"] == mode
                                and f["bot"] == finding.bot
                                and f["test_id"] == finding.test_id
                            )
                        ]
                        run["findings"].append(finding.model_dump())
                        governance.append(
                            run,
                            "finding",
                            mode=mode,
                            test=finding.test_id,
                            verdict=finding.verdict,
                            tool=finding.tool,
                            tool_version=finding.tool_version,
                            details=finding.details,
                        )
                        checkpoint(run)
                if mode == "white":
                    for slot in range(len(config.targets)):
                        selected = [r for r in plans if r["bot"] == slot]
                        if stop.is_set():
                            result = [
                                missing(
                                    mode,
                                    slot,
                                    r["category"],
                                    r["test"],
                                    "Stopped before source scan.",
                                )
                                for r in selected
                            ]
                        else:
                            result = await engines[mode].run(selected)
                        run["findings"] = [
                            f for f in run["findings"] if f["mode"] != mode or f["bot"] != slot
                        ]
                        run["findings"].extend(f.model_dump() for f in result)
                        for finding in result:
                            governance.append(
                                run,
                                "scanner_result",
                                mode=mode,
                                test=finding.test_id,
                                tool=finding.tool,
                                tool_version=finding.tool_version,
                                details=finding.details,
                            )
                        checkpoint(run)
            run["engine_status"][mode] = "completed"
        except asyncio.CancelledError:
            run["engine_status"][mode] = "interrupted"
            raise
        except Exception as exc:
            run["engine_status"][mode] = "error"
            governance.append(run, "engine_error", mode=mode, error=type(exc).__name__)
            for row in plans:
                run["findings"].append(
                    missing(
                        mode,
                        row.get("bot", 0),
                        row.get("category", "configuration_reliability"),
                        row.get("test", "engine"),
                        f"Engine error: {type(exc).__name__}; no pass inferred.",
                    ).model_dump()
                )
        finally:
            checkpoint(run)

    try:
        async with asyncio.timeout(config.max_minutes * 60):
            await asyncio.gather(*(mode_job(mode) for mode in request.modes))
        run["status"] = "stopped" if stop.is_set() else "completed"
    except asyncio.CancelledError:
        run["status"] = "interrupted"
    except TimeoutError:
        run["status"] = "timed_out"
        stop.set()
    finally:
        if run["status"] in ("interrupted", "timed_out", "stopped"):
            from ..blackbox.runner import ACTIVE

            if run.get("blackbox_run_id") in ACTIVE:
                ACTIVE[run["blackbox_run_id"]].set()
        for finding in run["findings"]:
            if finding["explanation"] == "Pending execution.":
                finding["explanation"] = (
                    "Assessment interrupted before this check produced evidence. Resume after resolving its missing input/tool/provider."
                )
        run["duration_seconds"] = round(
            run.get("duration_seconds", 0) + time.monotonic() - started, 3
        )
        run["finished_at"] = time.time()
        run["upload_expires_at"] = time.time() + request.upload_retention_days * 86400
        for mode in request.modes:
            governance.append(run, "mode_finished", mode=mode, status=run["engine_status"][mode])
        if request.upload_retention_days == 0:
            release_inputs(run)
            governance.append(run, "private_inputs_deleted", policy="Immediately after run")
        checkpoint(run)
        LIVE_CONFIGS.pop(run["id"], None)
        LIVE_RUNS.pop(run["id"], None)
        TASKS.pop(run["id"], None)
        STOPS.pop(run["id"], None)


def expire() -> None:
    for run in db.all_records("assurance"):
        if run["id"] in TASKS or run.get("uploads_deleted"):
            continue
        if run.get("upload_expires_at", float("inf")) <= time.time():
            release_inputs(run)
            governance.append(run, "private_inputs_deleted", policy="Retention expired")
            checkpoint(run)
    referenced = {
        r["input_id"]
        for run in db.all_records("assurance")
        if not run.get("uploads_deleted")
        for r in run.get("input_hashes", [])
    }
    for record in db.all_records("assurance_input"):
        if record["id"] not in referenced and record["created_at"] + 86400 < time.time():
            remove(record["id"])


def release_inputs(run: dict) -> None:
    protected = {
        r["input_id"]
        for other in db.all_records("assurance")
        if other["id"] != run["id"]
        and not other.get("uploads_deleted")
        and (other["id"] in TASKS or other.get("upload_expires_at", 0) > time.time())
        for r in other.get("input_hashes", [])
    }
    shared = False
    for item in run.get("input_hashes", []):
        if item["input_id"] in protected:
            shared = True
        else:
            remove(item["input_id"])
    run["uploads_deleted"] = not shared
    run["uploads_shared"] = shared


def export(run: dict, include_child: bool = True) -> dict:
    clean = safe(copy.deepcopy(run))
    clean["audit_integrity"] = integrity(run)
    from ..blackbox.cost_summary import totals

    rows = metering.events(run["id"])
    if run.get("blackbox_run_id"):
        rows += metering.events(run["blackbox_run_id"])
    clean["assurance_costs"] = {
        "bot": totals([r for r in rows if r["role"] == "target"]),
        "evaluation": totals([r for r in rows if r["role"] != "target"]),
    }
    clean["privacy_note"] = (
        "Private input contents excluded; transcripts redacted. Source hashes describe local originals."
    )
    if include_child and run.get("blackbox_run_id"):
        child = db.get("blackbox", run["blackbox_run_id"])
        if child:
            clean["blackbox"] = governance.export_run(child)
    from ..blackbox.bias import model_family

    rules = run.get("protocol_snapshot", {}).get("model_families", {})
    declared = {j["model"] for j in run["config"].get("judges", [])}
    actual = {e["model"] for e in run.get("audit", []) if e.get("model")}
    actual.update(
        j["model"]
        for f in run["findings"]
        for j in f.get("details", {}).get("judges", [])
        if j.get("model")
    )
    clean["model_cards"] = {
        "bots": run["config"].get("targets", []),
        "judges": sorted(declared | actual),
        "warning": [],
    }
    for target in clean["model_cards"]["bots"]:
        family = model_family(target.get("model", ""), rules)
        if family and any(model_family(j, rules) == family for j in declared | actual):
            clean["model_cards"]["warning"].append(
                f"{target['name']} shares model family {family} with a judge; use independent review."
            )
    return clean
