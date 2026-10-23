"""Human-aligned Judge calibration (C08, with C11 audit/retention integration).

Owners freeze a set of recorded conversations, label them independently and compare the selected
LLM Judge's binary decisions with those labels. This is a diagnostic: it never changes a Finding,
score, model-to-model agreement or winner, and a small owner-labeled sample is not certification.
"""

import asyncio
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from .. import database as db
from ..config import ROOT
from . import metering
from .calibration_models import (
    KIND_EVALUATION,
    KIND_SET,
    OWNER,
    SCHEMA_VERSION,
    CalibrationPolicy,
    LabelUpdate,
    Selection,
)
from .execution_cache import digest
from .judge_prompts import (
    evaluator_fingerprint,
    normalize_endpoint,
    rubric_fingerprint,
)

ZERO = "0" * 64
PAYLOAD_KEYS = (
    "category",
    "criterion",
    "reference",
    "policy",
    "scope",
    "transcript",
    "bias_subtype",
    "screening_signals",
)
RESUMABLE = ("interrupted", "cancelled")
ACTIVE = ("queued", "running", "interrupted")
TASKS: dict[str, asyncio.Task] = {}
STOPS: dict[str, asyncio.Event] = {}
SECRETS: dict[str, list[str]] = {}
CANCELLED: set[str] = set()

WARNINGS = {
    "uncalibrated": "Judge not calibrated against human labels. Agreement with human judgment is unverified.",
    "stale": "Existing calibration applies to a different Judge, prompt or rubric configuration. The current configuration is unverified.",
    "incomplete": "Calibration incomplete: some selected items have no valid Judge result or label. Agreement covers only judged items.",
    "insufficient_sample": "Calibration sample is too small or unbalanced to establish alignment. Metrics are descriptive only.",
    "not_aligned": "Judge not aligned with human labels on this sample. Review disagreements before using it at scale.",
    "meets": "Meets configured calibration criteria.",
}
LIMITATIONS = [
    "Conditional on this sample and rubric; not certification, universal Judge accuracy or an industry standard.",
    "Precision is limited by sample size: a small sample cannot detect uncommon failure modes, and class coverage below the configured minimum is reported as insufficient rather than estimated.",
    "Items come only from the selected saved Runs, so agreement does not transfer to other bots, Categories, prompts, languages or future traffic.",
    "Returned provider model names are not guaranteed immutable revisions; silent upstream changes are not detected.",
    "Human labels are entered by the local owner and may reflect prior exposure to original Judge output.",
    "Calibration is diagnostic only: it does not change Findings, scores, winners or model-to-model agreement.",
    "Agreement is not a confidence interval or a population estimate.",
]


class CalibrationError(Exception):
    """Base class; `status` is the HTTP status the API should return."""

    status = 422


class NotFound(CalibrationError):
    status = 404


class Conflict(CalibrationError):
    status = 409


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def policy() -> CalibrationPolicy:
    data = json.loads((ROOT / "app/studio/settings.json").read_text(encoding="utf-8"))
    return CalibrationPolicy.model_validate(data.get("judge_calibration", {}))


# --- audit: hash chain verified by governance.verify, written inside the record's transaction ---


def chain_append(record: dict, conn, event: str, **details) -> None:
    from .governance import initialize

    initialize(conn)
    reserved = {"sequence", "run_id", "at", "config_hash", "suite_version", "previous_hash", "hash"}
    if reserved.intersection(details):
        raise ValueError("Audit details cannot overwrite chain metadata")
    events = record.setdefault("audit", [])
    previous = events[-1]["hash"] if events else ZERO
    entry = {
        "sequence": len(events),
        "run_id": record["id"],
        "at": now(),
        "event": event,
        "config_hash": digest(record.get("config", {})),
        "suite_version": record.get("protocol_snapshot", {}).get("protocol_version", "legacy"),
        "previous_hash": previous,
        **copy.deepcopy(details),
    }
    secrets = SECRETS.get(record["id"], [])
    if secrets:
        from .governance import scrub_secrets

        entry = scrub_secrets(entry, secrets)
    entry["hash"] = digest(entry)
    tail = conn.execute(
        "SELECT hash FROM audit_chain WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
        (record["id"],),
    ).fetchone()
    if tail and tail[0] != previous:
        raise Conflict("Audit anchor mismatch: history was changed or another writer owns it.")
    conn.execute(
        "INSERT INTO audit_chain VALUES (?,?,?,?)",
        (record["id"], entry["sequence"], entry["hash"], json.dumps(entry)),
    )
    events.append(entry)


def integrity(record: dict) -> dict:
    from .governance import verify

    return verify(record)


# --- source resolution and evidence extraction -------------------------------------------


def uuid_text(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise CalibrationError("Identifier must be a UUID.") from None


def resolve_source(kind: str, ident: str) -> tuple[dict, str]:
    """Return (saved Black Run, assessment ID or ''). An assessment ID is never a Run ID."""
    ident = uuid_text(ident)
    assessment = ""
    if kind == "assurance_assessment":
        record = db.get("assurance", ident)
        if not record:
            raise NotFound("Assessment not found.")
        assessment = ident
        ident = record.get("blackbox_run_id") or ""
        if not ident:
            raise CalibrationError(
                "This assessment has no recorded Black Run, so it has no saved conversations."
            )
    run = db.get("blackbox", ident)
    if not run:
        raise NotFound("Saved Black Run not found.")
    if run.get("status") in ("queued", "running"):
        raise Conflict("Wait for this Run to finish before selecting its saved conversations.")
    return run, assessment


def base_case_id(case: dict) -> str:
    return str(case.get("base_case_id") or re.sub(r"-repeat-\d+$", "", case["id"]))


def build_item(run: dict, assessment: str, case: dict, slot: int, limit: int):
    """Return (item, None) or (None, exclusion reason). Source Judge results are never copied."""
    if case.get("category") == "performance":
        return None, "Measured latency has no Judge rubric."
    if case.get("derived") or case.get("bias_subtype") == "algorithmic":
        return None, "Derived aggregate record, not an independent conversational sample."
    results = case.get("results") or []
    if slot >= len(results):
        return None, "Bot slot not present in this Case."
    result = results[slot]
    if result.get("derived_from"):
        return None, "Derived aggregate record, not an independent conversational sample."
    transcript = result.get("transcript") or []
    outputs = [t.get("output") for t in transcript if isinstance(t, dict)]
    if (
        not transcript
        or len(transcript) < len(case.get("turns") or [1])
        or any(not isinstance(o, str) or not o.strip() for o in outputs)
        or any(t.get("error") for t in transcript if isinstance(t, dict))
    ):
        return None, "Saved transcript is incomplete or contains errors."
    if case.get("bias_subtype") and len(transcript) != 2:
        return None, "Paired Bias context is incomplete."
    if not str(case.get("expected") or "").strip():
        return None, "Expected criterion was not retained."
    config = run.get("config", {})
    screening = (
        {
            "bias": result.get("bias_signals", {}),
            "general": result.get("screening", {}),
            "local_classifier": result.get("local_classifier"),
        }
        if "screening" in result
        else {}
    )
    payload = {
        "category": case["category"],
        "criterion": case["expected"],
        "reference": case.get("reference"),
        "policy": config.get("policy", ""),
        "scope": config.get("scope", ""),
        "transcript": copy.deepcopy(transcript),
        "bias_subtype": case.get("bias_subtype", ""),
        "screening_signals": screening,
    }
    if len(json.dumps(payload, ensure_ascii=False)) > limit:
        return None, "Saved evidence is larger than the configured item limit."
    source_model = config.get("judge_model") or next(
        (j.get("model") for j in config.get("judges", []) if j.get("model")), ""
    )
    try:
        from .judge_prompts import request_body
        from .schema import Settings, Target

        stub = Settings(targets=[Target(kind="zip")], judge_model=source_model or "unspecified")
        body, _, _ = request_body(stub, payload, False)
        request_hash = digest(body) if source_model else None
    except Exception:  # noqa: BLE001 - any failure means the request cannot be reconstructed
        return None, "Evidence cannot reconstruct a Judge request."
    targets = run.get("targets", [])
    snapshot = run.get("protocol_snapshot")
    return {
        "id": str(uuid.uuid4()),
        "source": {
            "kind": "blackbox_run",
            "run_id": run["id"],
            "assessment_id": assessment,
            "case_id": case["id"],
            "base_case_id": base_case_id(case),
            "scenario_index": case.get("scenario_index"),
            "bot_slot": slot,
            "bot_name": targets[slot].get("name", "") if slot < len(targets) else "",
            "repeat": case.get("repeat", 1),
            "seed": config.get("seed", 0),
            "simple_mode": bool(config.get("simple_mode")),
        },
        "category": case["category"],
        "bias_subtype": case.get("bias_subtype", ""),
        "payload": payload,
        "protocol_version": (snapshot or {}).get("protocol_version", "legacy-not-recorded"),
        "protocol_hash": digest(snapshot) if snapshot else "legacy-not-recorded",
        "source_hash": digest(
            {"run": run["id"], "case": case["id"], "slot": slot, "transcript": transcript}
        ),
        "transcript_hash": digest(transcript),
        "rubric_hash": rubric_fingerprint(payload),
        "payload_hash": digest(payload),
        "request_hash": request_hash,
        "labels": [],
    }, None


def eligible_items(run: dict, assessment: str = "") -> tuple[list[dict], list[dict]]:
    limit = policy().max_item_chars
    items, excluded = [], []
    for case in run.get("cases", []):
        for slot in range(len(case.get("results") or [])):
            item, reason = build_item(run, assessment, case, slot, limit)
            if item:
                items.append(item)
            else:
                excluded.append({"case_id": case["id"], "bot_slot": slot, "reason": reason})
    return items, excluded


def original_outcome(run: dict) -> dict[tuple[str, int], str]:
    """(Case ID, bot slot) -> the saved Judge's own outcome class.

    Used only to spread a sample across ordinary successes and meaningful failures. It is never
    stored on an item, exported to the labeling view or sent to a Judge, so labeling stays blind.
    """
    index: dict[tuple[str, int], str] = {}
    for case in run.get("cases", []):
        for slot, result in enumerate(case.get("results") or []):
            status = result.get("status")
            index[(case["id"], slot)] = status if status in ("passed", "failed") else "unmeasured"
    return index


def _seeded_order(items: list[dict], seed: int) -> list[dict]:
    """Deterministic shuffle keyed by the seed and the item's source identity."""
    return sorted(
        items,
        key=lambda i: hashlib.sha256(
            f"{seed}:{i['source']['case_id']}:{i['source']['bot_slot']}".encode()
        ).hexdigest(),
    )


def _round_robin(groups: list[list[dict]], size: int) -> list[dict]:
    """Take one item from each non-empty group in turn, so every group is represented first."""
    queues = [list(group) for group in groups]
    chosen: list[dict] = []
    while len(chosen) < size and any(queues):
        for queue in queues:
            if not queue:
                continue
            chosen.append(queue.pop(0))
            if len(chosen) >= size:
                break
    return chosen


OUTCOME_ORDER = ("failed", "passed", "unmeasured")


def _strata(items: list[dict], sample, outcomes: dict[tuple[str, int], str]) -> list[list[dict]]:
    """One deterministic queue per Category, optionally alternating saved failures and passes."""
    by_category: dict[str, list[dict]] = {}
    for item in _seeded_order(items, sample.seed):
        by_category.setdefault(item["category"], []).append(item)
    strata = []
    for category in sorted(by_category):
        rows = by_category[category]
        if not sample.balance_outcomes:
            strata.append(rows)
            continue
        buckets: dict[str, list[dict]] = {}
        for item in rows:
            key = outcomes.get(
                (item["source"]["case_id"], item["source"]["bot_slot"]), "unmeasured"
            )
            buckets.setdefault(key, []).append(item)
        ordered = [buckets[k] for k in OUTCOME_ORDER if k in buckets]
        strata.append(_round_robin(ordered, len(rows)))
    return strata


def select(selection: Selection) -> tuple[list[dict], list[dict], dict]:
    """Explicit Case/slot picks or a reproducible seeded sample from one saved Run."""
    run, assessment = resolve_source(selection.source.kind, selection.source.id)
    items, excluded = eligible_items(run, assessment)
    index = {(i["source"]["case_id"], i["source"]["bot_slot"]): i for i in items}
    if selection.sample:
        s = selection.sample
        size = min(s.size, policy().max_sample_size)
        if s.stratify == "category":
            chosen = _round_robin(_strata(items, s, original_outcome(run)), size)
        else:
            chosen = _seeded_order(items, s.seed)[:size]
        method = {
            "kind": "seeded_sample",
            "seed": s.seed,
            "requested": s.size,
            "stratify": s.stratify,
            "balance_outcomes": s.balance_outcomes,
        }
        if s.balance_outcomes:
            method["base_rate_note"] = (
                "The sample alternates the saved Judge's own passes and failures, so its "
                "failure rate is not the Run's failure rate. Read false acceptance and false "
                "rejection as conditional on this sample, not as population rates."
            )
    else:
        wanted = {(r.case_id, r.bot_slot) for r in selection.items}
        known = {(e["case_id"], e["bot_slot"]): e for e in excluded}
        chosen = []
        excluded = []
        for ref in selection.items:
            key = (ref.case_id, ref.bot_slot)
            if key in index:
                chosen.append(index[key])
            else:
                excluded.append(
                    known.get(key)
                    or {
                        "case_id": ref.case_id,
                        "bot_slot": ref.bot_slot,
                        "reason": "Case and bot slot not found in the saved Run.",
                    }
                )
        del wanted
        method = {"kind": "explicit", "requested": len(selection.items)}
    method["source"] = {
        "kind": selection.source.kind,
        "id": selection.source.id,
        "run_id": run["id"],
    }
    method["note"] = "Selection can bias results; prefer a varied sample covering pass and fail."
    return chosen, excluded, method


# --- sets, labels and frozen versions -------------------------------------------------------


def latest(item: dict) -> dict | None:
    return item["labels"][-1] if item.get("labels") else None


def public_item(item: dict, blind: bool = True) -> dict:
    """Labeling view: evidence the owner needs, never original Judge scores or reasons."""
    return {k: v for k, v in item.items() if k != "labels"} | {
        "label": latest(item),
        "label_revision": len(item.get("labels", [])),
    }


def get_set(ident: str) -> dict:
    record = db.get(KIND_SET, uuid_text(ident))
    if not record:
        raise NotFound("Calibration set not found.")
    return record


def get_evaluation(ident: str) -> dict:
    record = db.get(KIND_EVALUATION, uuid_text(ident))
    if not record:
        raise NotFound("Calibration evaluation not found.")
    return record


def _new_set(name: str, items: list[dict], method: dict) -> dict:
    ident = str(uuid.uuid4())
    return {
        "id": ident,
        "kind": KIND_SET,
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "name": name,
        "created_at": now(),
        "current_version": 0,
        "config": {"policy": policy().model_dump()},
        "protocol_snapshot": {"protocol_version": "judge-calibration-v1"},
        "selection_methods": [method],
        "blinding": {
            "original_scores_hidden": True,
            "prior_exposure_possible": True,
            "note": "Original Judge scores and reasons are hidden while labeling, but you may "
            "have seen them earlier.",
        },
        "retention": {
            "policy": "Copied evidence is deleted with its source Run or assessment, or with this set.",
            "independent_expiry_days": 0,
        },
        "draft": {"items": items},
        "versions": [],
        "audit": [],
    }


def _insert_unique(items: list[dict], extra: list[dict]) -> list[dict]:
    seen = {(i["source"]["run_id"], i["source"]["case_id"], i["source"]["bot_slot"]) for i in items}
    added = []
    for item in extra:
        key = (item["source"]["run_id"], item["source"]["case_id"], item["source"]["bot_slot"])
        if key not in seen:
            seen.add(key)
            added.append(item)
    return added


def create_set(name: str, selection: Selection) -> dict:
    p = policy()
    if len(db.all_records(KIND_SET)) >= p.max_sets:
        raise CalibrationError("Calibration set limit reached; delete an old set first.")
    items, excluded, method = select(selection)
    if not items:
        raise CalibrationError("No eligible saved conversations were selected.")
    if len(items) > p.max_items_per_set:
        raise CalibrationError(f"A set holds at most {p.max_items_per_set} items.")
    record = _new_set(name.strip(), items, method)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        chain_append(record, conn, "set_created", items=len(items), method=method["kind"])
        conn.execute(
            "INSERT INTO records VALUES (?,?,?)", (KIND_SET, record["id"], json.dumps(record))
        )
    return {"set": summarize_set(record), "excluded": excluded}


def add_items(ident: str, expected_revision: int, selection: Selection) -> dict:
    items, excluded, method = select(selection)
    p = policy()
    added_ids: list[str] = []

    def mutate(record, conn):
        fresh = _insert_unique(record["draft"]["items"], items)
        if len(record["draft"]["items"]) + len(fresh) > p.max_items_per_set:
            raise CalibrationError(f"A set holds at most {p.max_items_per_set} items.")
        record["draft"]["items"].extend(fresh)
        record["selection_methods"].append(method)
        added_ids.extend(i["id"] for i in fresh)
        chain_append(record, conn, "items_added", added=len(fresh))

    record = _guard(KIND_SET, ident, mutate, expected_revision)
    return {"set": summarize_set(record), "added": len(added_ids), "excluded": excluded}


def remove_item(ident: str, expected_revision: int, item_id: str) -> dict:
    def mutate(record, conn):
        before = len(record["draft"]["items"])
        record["draft"]["items"] = [i for i in record["draft"]["items"] if i["id"] != item_id]
        if len(record["draft"]["items"]) == before:
            raise NotFound("Item not found in this draft.")
        chain_append(record, conn, "item_removed", item=item_id)

    return summarize_set(_guard(KIND_SET, ident, mutate, expected_revision))


def _guard(kind, ident, mutate, expected_revision=None):
    try:
        return db.update(kind, uuid_text(ident), mutate, expected_revision)
    except db.RecordMissing:
        raise NotFound("Record not found.") from None
    except db.RevisionConflict as exc:
        raise Conflict(str(exc)) from None


def save_label(ident: str, item_id: str, update: LabelUpdate) -> dict:
    p = policy()
    if len(update.rationale) > p.max_rationale_chars:
        raise CalibrationError(f"Rationale is limited to {p.max_rationale_chars} characters.")
    binary = update.binary
    verdict = "pass" if binary else "fail"

    def mutate(record, conn):
        item = next((i for i in record["draft"]["items"] if i["id"] == item_id), None)
        if not item:
            raise NotFound("Item not found in this draft.")
        revision = len(item["labels"])
        if revision != update.expected_revision:
            raise Conflict(
                f"Label revision {update.expected_revision} is stale; current revision is {revision}."
            )
        if revision and len(update.change_reason.strip()) < 10:
            raise CalibrationError(
                "Changing a label requires a meaningful reason (10+ characters)."
            )
        item["labels"].append(
            {
                "revision": revision + 1,
                "verdict": verdict,
                "binary_pass": binary,
                "score": update.score,
                "rationale": update.rationale.strip(),
                "author": OWNER,
                "at": now(),
                "change_reason": update.change_reason.strip(),
            }
        )
        chain_append(
            record, conn, "label_saved", item=item_id, revision=revision + 1, pass_label=binary
        )
        return item

    # Labels are guarded per item revision above; the set revision is not required to match.
    item = _guard(KIND_SET, ident, mutate)
    return {"item_id": item_id, "label_revision": len(item["labels"]), "label": latest(item)}


def version_hash(items: list[dict]) -> str:
    return digest(
        {
            "threshold": 80,
            "items": [
                {
                    "id": i["id"],
                    "payload": i["payload_hash"],
                    "source": i["source_hash"],
                    "label": (
                        {"rev": lab["revision"], "pass": lab["binary_pass"], "score": lab["score"]}
                        if (lab := latest(i))
                        else None
                    ),
                }
                for i in items
            ],
        }
    )


def scenario_key(item: dict) -> tuple[str, str]:
    return (item["category"], item["source"]["base_case_id"])


def assign_folds(items: list[dict], percent: float, seed: int) -> dict:
    """Mark each item development or holdout, splitting whole scenarios.

    Repeats of one scenario are not independent observations, so they always land in the same
    fold; otherwise a held-out result would partly restate work already reviewed.
    """
    scenarios = sorted(
        {scenario_key(i) for i in items},
        key=lambda k: hashlib.sha256(f"{seed}:{k[0]}:{k[1]}".encode()).hexdigest(),
    )
    if not percent:
        for item in items:
            item["fold"] = "development"
        return {
            "holdout_percent": 0,
            "seed": seed,
            "scenarios": {"development": len(scenarios), "holdout": 0},
            "note": "No held-out subset was reserved; every item is available for review.",
        }
    if len(scenarios) < 2:
        raise CalibrationError(
            "A held-out subset needs at least two distinct scenarios in the set."
        )
    count = max(1, min(round(len(scenarios) * percent / 100), len(scenarios) - 1))
    holdout = set(scenarios[:count])
    for item in items:
        item["fold"] = "holdout" if scenario_key(item) in holdout else "development"
    return {
        "holdout_percent": percent,
        "seed": seed,
        "scenarios": {"development": len(scenarios) - count, "holdout": count},
        "note": "Review disagreements in the development fold only. After changing the Judge, "
        "prompt or rubric, evaluate again and read the holdout fold as the unreviewed result.",
    }


def freeze(ident: str, expected_revision: int, holdout_percent: float = 0, holdout_seed: int = 42):
    def mutate(record, conn):
        items = copy.deepcopy(record["draft"]["items"])
        if not items:
            raise CalibrationError("Add at least one item before freezing a version.")
        if not any(latest(i) for i in items):
            raise CalibrationError("Label at least one item before freezing a version.")
        folds = assign_folds(items, holdout_percent, holdout_seed)
        version = {
            "version": len(record["versions"]) + 1,
            "frozen_at": now(),
            "hash": version_hash(items),
            "policy_hash": digest(policy().model_dump()),
            "threshold": 80,
            "items": items,
            "sample_methods": copy.deepcopy(record["selection_methods"]),
            "folds": folds,
        }
        record["versions"].append(version)
        record["current_version"] = version["version"]
        chain_append(
            record,
            conn,
            "version_frozen",
            version=version["version"],
            version_hash=version["hash"],
            holdout_scenarios=folds["scenarios"]["holdout"],
        )

    record = _guard(KIND_SET, ident, mutate, expected_revision)
    return summarize_set(record)


def summarize_set(record: dict) -> dict:
    items = record["draft"]["items"]
    return {
        "id": record["id"],
        "name": record["name"],
        "revision": record["revision"],
        "created_at": record["created_at"],
        "current_version": record["current_version"],
        "items": len(items),
        "labeled": sum(bool(latest(i)) for i in items),
        "versions": [
            {
                "version": v["version"],
                "hash": v["hash"],
                "frozen_at": v["frozen_at"],
                "items": len(v["items"]),
                "folds": v.get("folds"),
                "purged": bool(v.get("purged")),
            }
            for v in record["versions"]
        ],
        "blinding": record["blinding"],
        "retention": record["retention"],
        "invalidated": record.get("invalidated"),
    }


def set_detail(record: dict) -> dict:
    return {
        **summarize_set(record),
        "items_detail": [public_item(i) for i in record["draft"]["items"]],
        "selection_methods": record["selection_methods"],
        "audit_integrity": integrity(record),
    }


# --- metrics (pure functions) ---------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(100 * numerator / denominator, 2) if denominator else None,
    }


def metrics(
    items: list[dict],
    results: dict,
    evaluator_id: str,
    p: CalibrationPolicy,
    fold: str | None = None,
) -> dict:
    """Human-alignment metrics for one actual evaluator over a frozen version's items.

    Only valid Judge results from this evaluator are comparable; everything else stays Not tested,
    so a missing judgment can never improve agreement by shrinking the denominator silently.
    `fold` restricts the items to one side of a held-out split and keeps its own denominators.
    """
    if fold:
        items = [i for i in items if i.get("fold", "development") == fold]
    labeled = [i for i in items if latest(i)]
    comparable, tested = [], 0
    for item in labeled:
        result = results.get(item["id"]) or {}
        if result.get("status") in ("judged", "not_tested"):
            tested += 1
        if result.get("status") == "judged" and result.get("actual", {}).get("id") == evaluator_id:
            comparable.append((item, result))
    matching = sum(r["agrees"] for _, r in comparable)
    confusion = {
        "human_pass_judge_pass": 0,
        "human_pass_judge_fail": 0,
        "human_fail_judge_pass": 0,
        "human_fail_judge_fail": 0,
    }
    for item, result in comparable:
        h = "pass" if latest(item)["binary_pass"] else "fail"
        j = "pass" if result["judge_pass"] else "fail"
        confusion[f"human_{h}_judge_{j}"] += 1
    human_pass = confusion["human_pass_judge_pass"] + confusion["human_pass_judge_fail"]
    human_fail = confusion["human_fail_judge_pass"] + confusion["human_fail_judge_fail"]
    scenarios: dict[tuple, list] = {}
    categories: dict[str, dict] = {}
    for item, _ in comparable:
        key = (item["category"], item["source"]["base_case_id"])
        scenarios.setdefault(key, []).append(item)
    for item in labeled:
        row = categories.setdefault(
            item["category"], {"labeled": 0, "comparable": 0, "scenarios": set()}
        )
        row["labeled"] += 1
    for item, _ in comparable:
        row = categories[item["category"]]
        row["comparable"] += 1
        row["scenarios"].add(item["source"]["base_case_id"])
    pass_scenarios = sum(any(latest(i)["binary_pass"] for i in rows) for rows in scenarios.values())
    fail_scenarios = sum(
        any(not latest(i)["binary_pass"] for i in rows) for rows in scenarios.values()
    )
    hashes = [i["transcript_hash"] for i, _ in comparable]
    total = len(items)
    coverage = round(100 * len(comparable) / total, 2) if total else None
    checks = [
        {
            "name": "comparable_coverage_percent",
            "required": p.min_comparable_coverage_percent,
            "actual": coverage,
            "met": coverage is not None and coverage >= p.min_comparable_coverage_percent,
        },
        {
            "name": "distinct_scenarios",
            "required": p.min_distinct_scenarios,
            "actual": len(scenarios),
            "met": len(scenarios) >= p.min_distinct_scenarios,
        },
        {
            "name": "human_pass_scenarios",
            "required": p.min_human_pass_scenarios,
            "actual": pass_scenarios,
            "met": pass_scenarios >= p.min_human_pass_scenarios,
        },
        {
            "name": "human_fail_scenarios",
            "required": p.min_human_fail_scenarios,
            "actual": fail_scenarios,
            "met": fail_scenarios >= p.min_human_fail_scenarios,
        },
    ]
    return {
        "evaluator_id": evaluator_id,
        "fold": fold or "all",
        "threshold": p.pass_threshold,
        "counts": {
            "total_selected": total,
            "labeled": len(labeled),
            "unlabeled": total - len(labeled),
            "attempted": tested,
            "validly_judged": len(comparable),
            "matching": matching,
            "disagreeing": len(comparable) - matching,
            "not_tested": len(labeled) - len(comparable),
        },
        "agreement": _rate(matching, len(comparable)),
        "confusion": confusion,
        "false_acceptance": _rate(confusion["human_fail_judge_pass"], human_fail),
        "false_rejection": _rate(confusion["human_pass_judge_fail"], human_pass),
        "coverage_percent": coverage,
        "sufficiency": {
            "checks": checks,
            "distinct_scenarios": len(scenarios),
            "repeated_scenarios": sum(len(rows) > 1 for rows in scenarios.values()),
            "duplicate_transcripts": len(hashes) - len(set(hashes)),
            "categories": {
                k: {
                    "labeled": v["labeled"],
                    "comparable": v["comparable"],
                    "scenarios": len(v["scenarios"]),
                }
                for k, v in sorted(categories.items())
            },
            "sufficient": all(c["met"] for c in checks),
        },
        "disagreement_ids": [i["id"] for i, r in comparable if not r["agrees"]],
    }


def classify(entry: dict, p: CalibrationPolicy, complete: bool) -> tuple[str, list[str]]:
    """Distinct states: incomplete, not_aligned, insufficient_sample, meets (calibrated)."""
    counts = entry["counts"]
    checks = {c["name"]: c for c in entry["sufficiency"]["checks"]}
    warnings = []
    incomplete = (
        not complete or counts["unlabeled"] > 0 or not checks["comparable_coverage_percent"]["met"]
    )
    if incomplete:
        warnings.append(WARNINGS["incomplete"])
    agreement = entry["agreement"]["percent"]
    aligned_low = agreement is not None and agreement < p.min_agreement_percent
    if aligned_low:
        warnings.append(WARNINGS["not_aligned"])
    if not all(c["met"] for c in checks.values() if c["name"] != "comparable_coverage_percent"):
        warnings.append(WARNINGS["insufficient_sample"])
    if incomplete:
        return "incomplete", warnings
    if aligned_low:
        return "not_aligned", warnings
    if not entry["sufficiency"]["sufficient"]:
        return "insufficient_sample", warnings
    return "meets", [WARNINGS["meets"]]


def entries(evaluation: dict, items: list[dict], p: CalibrationPolicy) -> dict:
    """One entry per actual evaluator. A fallback never inherits the requested model's status."""
    ids = {evaluation["evaluator"]["id"]}
    for result in evaluation["results"].values():
        if result.get("status") == "judged":
            ids.add(result["actual"]["id"])
    return {i: metrics(items, evaluation["results"], i, p) for i in sorted(ids)}


def version_of(record: dict, number: int) -> dict:
    for version in record["versions"]:
        if version["version"] == number:
            return version
    raise NotFound("Calibration version not found.")


# --- evaluation orchestration ---------------------------------------------------------------


def request_payload(item: dict, judge_model: str) -> dict:
    """Exactly the evidence/rubric fields. Human labels and prior scores can never enter."""
    payload = {k: copy.deepcopy(item["payload"].get(k)) for k in PAYLOAD_KEYS}
    source = item["source"]
    if item.get("bias_subtype") and source.get("simple_mode") and len(payload["transcript"]) == 2:
        from .bias import ordered_observation

        case = {"id": source["case_id"], "bias_subtype": item["bias_subtype"]}
        payload["transcript"] = ordered_observation(
            case, {"transcript": payload["transcript"]}, source.get("seed", 0), judge_model
        )["transcript"]
    return payload


def judge_settings(
    entry, token: str, timeout: float, budget: str | None, pinned: dict | None = None
):
    from pydantic import SecretStr

    from . import pricing
    from .schema import Settings, Target

    local_timeout = 240
    cfg = Settings(
        targets=[Target(kind="zip")],
        ownership_confirmed=True,
        judge_url=entry.url,
        judge_model=entry.model,
        judge_token=SecretStr(token) if token else None,
        judge_enabled=True,
        judge_consent=True,
        judge_local_model=entry.local,
        judge_model_alias=entry.price_alias or entry.model,
        judge_batch_size=1,
        judge_concurrency=policy().concurrency,
        timeout=timeout,
        max_budget_usd=budget,
        simple_mode=False,
        auto_local_fallback=False,
    )
    if entry.local:  # same assignment-after-validation pattern as studio_engine.judge_config
        cfg.timeout = max(timeout, local_timeout)
    if pinned:
        cfg.price_snapshot_id = pinned["price_snapshot_id"]
        cfg.cost_settings_snapshot = pinned["cost_settings_snapshot"]
    else:
        pricing.pin(cfg)
    return cfg


def snapshot_judge(entry) -> dict:
    """Judge selection without credentials."""
    return {
        "model": entry.model,
        "endpoint": normalize_endpoint(entry.url),
        "local": entry.local,
        "price_alias": entry.price_alias,
    }


def consent_ok(evaluation: dict, entry) -> bool:
    if entry.local:
        return True
    consent = evaluation.get("consent")
    return bool(
        consent
        and consent["endpoint"] == normalize_endpoint(entry.url)
        and consent["content_hash"] == evaluation["set_version_hash"]
    )


def start(set_id: str, request, token_resolver) -> dict:
    """Persist a queued evaluation (idempotently guarded) before any provider dispatch."""
    record = get_set(set_id)
    version = version_of(record, request.version)
    if version.get("purged"):
        raise Conflict("This version's source evidence was deleted.")
    judge = request.judge
    p = policy()
    if not any(latest(i) for i in version["items"]):
        raise CalibrationError("Label at least one item before evaluating.")
    if not judge.local:
        consent = request.cloud_consent
        if (
            not consent
            or consent.endpoint != normalize_endpoint(judge.url)
            or (consent.content_hash != version["hash"])
        ):
            raise CalibrationError(
                "Cloud Judges receive this calibration payload only with explicit consent naming the "
                "destination and this frozen version. Use a local Judge or grant that consent."
            )
    token = token_resolver(judge)
    cfg = judge_settings(judge, token, request.timeout, request.max_budget_usd)
    fingerprint = evaluator_fingerprint(cfg)
    ident = str(uuid.uuid4())
    evaluation = {
        "id": ident,
        "kind": KIND_EVALUATION,
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "set_id": record["id"],
        "set_version": version["version"],
        "set_version_hash": version["hash"],
        "status": "queued",
        "created_at": now(),
        "judge": snapshot_judge(judge),
        "fallbacks": [snapshot_judge(f) for f in request.fallbacks],
        "auto_local_fallback": request.auto_local_fallback,
        "evaluator": fingerprint,
        "config": {
            "policy": p.model_dump(),
            "price_snapshot_id": cfg.price_snapshot_id,
            "cost_settings_snapshot": cfg.cost_settings_snapshot,
            "max_budget_usd": cfg.max_budget_usd,
            "timeout": request.timeout,
        },
        "policy_hash": digest(p.model_dump()),
        "protocol_snapshot": {"protocol_version": "judge-calibration-v1"},
        "consent": request.cloud_consent.model_dump() if request.cloud_consent else None,
        "privacy": {"local": judge.local, "destination": normalize_endpoint(judge.url)},
        "results": {},
        "switch_events": [],
        "limitations": LIMITATIONS,
        "audit": [],
    }
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in conn.execute("SELECT body FROM records WHERE kind=?", (KIND_EVALUATION,)):
            other = json.loads(row[0])
            if (
                other["set_id"] == record["id"]
                and other["set_version"] == version["version"]
                and other["evaluator"]["id"] == fingerprint["id"]
                and other["status"] in ACTIVE
            ):
                raise Conflict(
                    f"Evaluation {other['id']} is already {other['status']} for this version and "
                    "Judge; resume it instead of starting duplicate provider work."
                )
        chain_append(
            evaluation,
            conn,
            "evaluation_created",
            version=version["version"],
            version_hash=version["hash"],
            evaluator=fingerprint["id"],
            judge_model=judge.model,
            local=judge.local,
        )
        conn.execute(
            "INSERT INTO records VALUES (?,?,?)", (KIND_EVALUATION, ident, json.dumps(evaluation))
        )
    remember_secrets(ident, token, [])
    return evaluation


def remember_secrets(ident: str, token: str, fallback_tokens: list[str]) -> None:
    SECRETS[ident] = [t for t in [token, *fallback_tokens] if t]


def set_status(ident: str, status: str, event: str, allowed: tuple | None = None, **details):
    def mutate(record, conn):
        if allowed is not None and record["status"] not in allowed:
            raise Conflict(f"Evaluation is {record['status']}; expected {', '.join(allowed)}.")
        record["status"] = status
        if status in ("completed", "cancelled", "interrupted"):
            record["finished_at"] = now()
        chain_append(record, conn, event, **details)

    return _guard(KIND_EVALUATION, ident, mutate)


def _safe(ident: str, text: str) -> str:
    from .governance import scrub_secrets

    return str(scrub_secrets(text, SECRETS.get(ident, [])))[:400]


def record_result(ident: str, item_id: str, result: dict, event: str, **details) -> None:
    def mutate(record, conn):
        record["results"][item_id] = result
        if event == "fallback_switch":
            record["switch_events"].append({"item_id": item_id, **details})
        chain_append(record, conn, event, item=item_id, **details)

    _guard(KIND_EVALUATION, ident, mutate)


async def judge_item(ident, evaluation, version, item, entries_list, stop, budget) -> str:
    """Judge one retained item; returns '' or a stop reason. Never calls the target bot."""
    from .connectors import safe_error
    from .judge import ask
    from .scheduling import Halted

    label = latest(item)
    base = {
        "item_id": item["id"],
        "human_label_revision": label["revision"],
        "human_pass": label["binary_pass"],
        "human_score": label["score"],
        "requested_evaluator_id": evaluation["evaluator"]["id"],
        "attempts": [],
    }
    reasons = []
    for index, (entry, token) in enumerate(entries_list):
        if stop.is_set():
            return "Stopped before this item was judged."
        if not consent_ok(evaluation, entry):
            reasons.append(f"{entry.model}: missing consent for this payload and destination.")
            base["attempts"].append(
                {"model": entry.model, "status": "not_tested", "reason": reasons[-1]}
            )
            continue
        cfg = judge_settings(
            entry, token, evaluation["config"]["timeout"], budget, evaluation["config"]
        )
        payload = request_payload(item, entry.model)
        try:
            with metering.scope(
                ident, "calibration", cfg, category=item["category"], test_case_id=item["id"]
            ):
                from .judge_prompts import request_body

                request_hash = digest(request_body(cfg, payload)[0])
                verdict = await ask(cfg, payload)
        except metering.BudgetLimit as exc:
            record_result(
                ident,
                item["id"],
                {**base, "status": "not_tested", "error_reason": _safe(ident, str(exc))},
                "item_not_tested",
                reason="budget",
            )
            return str(exc)
        except (Halted, asyncio.CancelledError):
            return "Stopped before this item was judged."
        except Exception as exc:  # noqa: BLE001 - provider/malformed output stays Not tested
            reason = _safe(ident, f"{entry.model}: {safe_error(exc)}")
            reasons.append(reason)
            base["attempts"].append(
                {"model": entry.model, "status": "not_tested", "reason": reason}
            )
            if index + 1 < len(entries_list):
                record_result(
                    ident,
                    item["id"],
                    {**base, "status": "pending"},
                    "fallback_switch",
                    previous=entry.model,
                    next=entries_list[index + 1][0].model,
                    reason=reason,
                )
            continue
        returned = str(verdict.get("provider_model") or "")
        actual = evaluator_fingerprint(
            cfg, returned if returned and returned != "Not supplied" else ""
        )
        score = verdict["score"]
        judge_pass = score >= 80
        result = {
            **base,
            "status": "judged",
            "actual": actual,
            "requested": evaluation["evaluator"]["id"],
            "fallback_used": index > 0,
            "judge_score": score,
            "judge_pass": judge_pass,
            "agrees": judge_pass == label["binary_pass"],
            "reason": _safe(ident, verdict.get("reason", "")),
            "evidence": verdict.get("evidence", []),
            "needs_review": bool(verdict.get("needs_review")),
            "request_hash": request_hash,
            "returned_model": returned or "Not supplied",
        }
        record_result(
            ident,
            item["id"],
            result,
            "item_judged",
            evaluator=actual["id"],
            fallback=index > 0,
            pass_judgment=judge_pass,
            request_hash=request_hash,
        )
        return ""
    record_result(
        ident,
        item["id"],
        {
            **base,
            "status": "not_tested",
            "error_reason": " | ".join(reasons) or "No Judge available.",
        },
        "item_not_tested",
        reason="; ".join(reasons)[:300],
    )
    return ""


async def execute(ident: str, tokens: dict) -> None:
    """Run (or resume) the pending items of one evaluation under its own metering identity."""
    from .judge_recovery import local_fallbacks
    from .scheduling import Runtime
    from .schema import JudgeSelection

    stop = STOPS[ident]
    evaluation = get_evaluation(ident)
    version = version_of(get_set(evaluation["set_id"]), evaluation["set_version"])
    judge = evaluation["judge"]
    chain = [
        (
            JudgeSelection(
                model=judge["model"],
                url=judge["endpoint"],
                local=judge["local"],
                price_alias=judge["price_alias"],
            ),
            tokens.get("primary", ""),
        )
    ]
    for position, fb in enumerate(evaluation["fallbacks"]):
        chain.append(
            (
                JudgeSelection(
                    model=fb["model"],
                    url=fb["endpoint"],
                    local=True,
                    fallback=True,
                    price_alias=fb["price_alias"],
                ),
                tokens["fallbacks"][position]
                if position < len(tokens.get("fallbacks", []))
                else "",
            )
        )
    budget = evaluation["config"]["max_budget_usd"]
    first_cfg = judge_settings(
        chain[0][0], chain[0][1], evaluation["config"]["timeout"], budget, evaluation["config"]
    )
    if evaluation.get("auto_local_fallback"):
        try:
            for found in await local_fallbacks(first_cfg):
                if all(found.model != e.model for e, _ in chain):
                    chain.append((found, ""))
        except Exception:  # noqa: BLE001 - discovery is optional
            pass
    pending = [
        i
        for i in version["items"]
        if latest(i) and (evaluation["results"].get(i["id"], {}).get("status") != "judged")
    ]
    stop_reason = ""
    runtime = Runtime(first_cfg, stop)
    semaphore = asyncio.Semaphore(policy().concurrency)

    async def one(item):
        nonlocal stop_reason
        async with semaphore:
            if stop.is_set():
                return
            reason = await judge_item(ident, evaluation, version, item, chain, stop, budget)
            if reason and not stop_reason:
                stop_reason = reason
                stop.set()

    try:
        with runtime.context():
            await asyncio.gather(*(one(i) for i in pending))
    finally:
        await runtime.close()
    cancelled = ident in CANCELLED
    if cancelled or stop_reason:
        set_status(
            ident,
            "cancelled" if cancelled else "interrupted",
            "evaluation_cancelled" if cancelled else "evaluation_interrupted",
            reason=_safe(ident, stop_reason or "Cancelled by owner."),
        )
    else:
        set_status(ident, "completed", "evaluation_completed")


def launch(ident: str, tokens: dict) -> None:
    if ident in TASKS and not TASKS[ident].done():
        raise Conflict("This evaluation is already running.")
    STOPS[ident] = asyncio.Event()
    SECRETS[ident] = [t for t in [tokens.get("primary", ""), *tokens.get("fallbacks", [])] if t]

    async def runner():
        try:
            await asyncio.to_thread(
                set_status,
                ident,
                "running",
                "evaluation_started",
                ("queued", "interrupted", "cancelled"),
            )
        except Conflict:
            return
        try:
            await execute(ident, tokens)
        except Exception as exc:  # noqa: BLE001 - never leave a record claiming to run
            await asyncio.to_thread(
                set_status,
                ident,
                "interrupted",
                "evaluation_interrupted",
                None,
                reason=_safe(ident, f"{type(exc).__name__}: {exc}"),
            )
        finally:
            TASKS.pop(ident, None)
            STOPS.pop(ident, None)
            CANCELLED.discard(ident)

    TASKS[ident] = asyncio.create_task(runner())


def cancel(ident: str) -> dict:
    record = get_evaluation(ident)
    if record["status"] not in ("queued", "running"):
        raise Conflict(f"Evaluation is {record['status']} and cannot be cancelled.")
    if ident in STOPS:
        CANCELLED.add(ident)
        STOPS[ident].set()
    else:
        set_status(ident, "cancelled", "evaluation_cancelled", reason="Cancelled by owner.")
    return view_evaluation(get_evaluation(ident))


def reconcile(record: dict) -> dict:
    """A record claiming to run without a live task was interrupted by a restart."""
    if record["status"] in ("queued", "running") and record["id"] not in TASKS:
        try:
            return set_status(
                record["id"],
                "interrupted",
                "evaluation_interrupted",
                ("queued", "running"),
                reason="Application restarted; resume to continue exact pending work.",
            )
        except Conflict:
            return get_evaluation(record["id"])
    return record


def recover_interrupted() -> int:
    count = 0
    for record in db.all_records(KIND_EVALUATION):
        if reconcile(record)["status"] == "interrupted" and record["status"] != "interrupted":
            count += 1
    return count


def costs(ident: str) -> dict:
    from .cost_summary import totals

    rows = metering.events(ident)
    if not rows:
        return {
            "calls": 0,
            "status": "No Judge calls recorded",
            "cost_micro_usd": 0,
            "unknown_calls": 0,
        }
    t = totals(rows)
    t["status"] = "Unknown" if t["cost_micro_usd"] is None else "known"
    return t


# --- views, compatibility and disagreements ---------------------------------------------------


def disagreements(evaluation: dict, version: dict) -> list[dict]:
    index = {i["id"]: i for i in version["items"]}
    rows = []
    for item_id, result in evaluation["results"].items():
        if result.get("status") != "judged" or result.get("agrees") is not False:
            continue
        item = index.get(item_id)
        if not item or item.get("purged"):
            continue
        label = latest(item)
        rows.append(
            {
                "item_id": item_id,
                "source": item["source"],
                "category": item["category"],
                "fold": item.get("fold", "development"),
                "human": {
                    "verdict": "pass" if label["binary_pass"] else "fail",
                    "score": label["score"],
                    "rationale": label["rationale"],
                    "label_revision": label["revision"],
                },
                "judge": {
                    "verdict": "pass" if result["judge_pass"] else "fail",
                    "score": result["judge_score"],
                    "reason": result["reason"],
                    "evidence": result["evidence"],
                    "needs_review": result["needs_review"],
                    "actual_evaluator": result["actual"],
                    "fallback_used": result["fallback_used"],
                },
                "transcript": item["payload"]["transcript"],
                "criterion": item["payload"]["criterion"],
            }
        )
    return rows


def view_evaluation(evaluation: dict, detail: bool = True) -> dict:
    evaluation = reconcile(evaluation)
    record = db.get(KIND_SET, evaluation["set_id"])
    p = CalibrationPolicy.model_validate(evaluation["config"]["policy"])
    view = {k: v for k, v in evaluation.items() if k not in ("audit",)}
    view["audit_integrity"] = integrity(evaluation)
    view["costs"] = costs(evaluation["id"])
    version = next(
        (
            v
            for v in (record or {}).get("versions", [])
            if v["version"] == evaluation["set_version"]
        ),
        None,
    )
    if not version or version.get("purged") or evaluation.get("invalidated"):
        view["summary"] = None
        view["note"] = "Source evidence was deleted; this calibration is invalidated."
        return view
    by_eval = entries(evaluation, version["items"], p)
    complete = evaluation["status"] == "completed"
    for key, entry in by_eval.items():
        entry["state"], entry["warnings"] = classify(entry, p, complete)
        entry["requested"] = key == evaluation["evaluator"]["id"]
        entry["evaluator"] = next(
            (
                r["actual"]
                for r in evaluation["results"].values()
                if r.get("status") == "judged" and r["actual"]["id"] == key
            ),
            evaluation["evaluator"],
        )
    view["by_evaluator"] = by_eval
    view["summary"] = by_eval[evaluation["evaluator"]["id"]]
    view["folds"] = version.get("folds")
    present = sorted({i.get("fold", "development") for i in version["items"]})
    if len(present) > 1:
        # Each fold reports its own denominators. The headline stays the whole sample so a
        # small fold cannot be read as a stronger result than the sample supports.
        view["by_fold"] = {}
        for name in present:
            fold_entry = metrics(
                version["items"], evaluation["results"], evaluation["evaluator"]["id"], p, name
            )
            fold_entry["state"], fold_entry["warnings"] = classify(fold_entry, p, complete)
            view["by_fold"][name] = fold_entry
    view["progress"] = {
        "labeled": sum(bool(latest(i)) for i in version["items"]),
        "done": sum(
            r.get("status") in ("judged", "not_tested") for r in evaluation["results"].values()
        ),
    }
    view["partial_fallback"] = any(
        r.get("fallback_used")
        for r in evaluation["results"].values()
        if r.get("status") == "judged"
    )
    if detail:
        view["disagreements"] = disagreements(evaluation, version)
    else:
        view.pop("results", None)
    return view


def list_evaluations(set_id: str | None = None) -> list[dict]:
    rows = []
    for record in db.all_records(KIND_EVALUATION):
        if set_id and record["set_id"] != set_id:
            continue
        v = view_evaluation(record, detail=False)
        rows.append(
            {
                k: v.get(k)
                for k in (
                    "id",
                    "set_id",
                    "set_version",
                    "status",
                    "created_at",
                    "finished_at",
                    "judge",
                    "summary",
                    "invalidated",
                )
            }
        )
    return rows


def current_rubrics() -> dict[str, str]:
    """base case id -> current protocol criterion, for rubric-change detection."""
    try:
        from .schema import Settings, Target
        from .studio_engine import cases

        stub = Settings(targets=[Target(kind="zip")])
        return {
            base_case_id(c): c["expected"]
            for c in cases(stub)
            if not c["category"].startswith("hallucination")
        }
    except Exception:  # noqa: BLE001 - rubric comparison is best effort
        return {}


def mismatch_reasons(
    evaluation: dict, current: dict, policy_text, scope_text, rubrics: dict, items: list[dict]
) -> list[str]:
    old = evaluation["evaluator"]
    reasons = []
    if old["requested_model"] != current["requested_model"]:
        reasons.append("Judge model changed.")
    if old["endpoint"] != current["endpoint"]:
        reasons.append("Judge endpoint changed.")
    for key, text in (
        ("template_hash", "Prompt template changed."),
        ("validation_hash", "Evidence-validation semantics changed."),
        ("generation_hash", "Evaluation settings changed."),
    ):
        if old[key] != current[key]:
            reasons.append(text)
    if policy_text is not None and all(i["payload"]["policy"] != policy_text for i in items):
        reasons.append("Policy context changed.")
    if scope_text is not None and all(i["payload"]["scope"] != scope_text for i in items):
        reasons.append("Scope context changed.")
    changed = [
        i
        for i in items
        if i["source"]["base_case_id"] in rubrics
        and rubrics[i["source"]["base_case_id"]] != i["payload"]["criterion"]
    ]
    if changed:
        reasons.append("Rubric changed for " + str(len(changed)) + " calibrated item(s).")
    return list(dict.fromkeys(reasons))


def resolve_compatibility(model: str, url: str, policy_text=None, scope_text=None) -> dict:
    """Alignment status of the CURRENT evaluator. History stays readable; credentials are ignored."""
    p = policy()
    base = {
        "state": "uncalibrated",
        "warnings": [WARNINGS["uncalibrated"]],
        "agreement_percent": None,
        "matching": 0,
        "comparable": 0,
        "evaluation_id": None,
        "model_to_model_note": "Distinct from model-to-model Judge agreement.",
        "stale_reasons": [],
        "diagnostic_only": True,
    }
    if not model:
        return base | {"headline": "No Judge selected."}
    from .schema import Settings, Target

    cfg = Settings(
        targets=[Target(kind="zip")],
        judge_model=model,
        judge_url=url or "http://127.0.0.1:1234/v1/chat/completions",
    )
    current = evaluator_fingerprint(cfg)
    rubrics = current_rubrics()
    history = [e for e in db.all_records(KIND_EVALUATION) if not e.get("invalidated")]
    match = None
    stale_reasons: list[str] = []
    for evaluation in sorted(history, key=lambda e: e["created_at"], reverse=True):
        record = db.get(KIND_SET, evaluation["set_id"]) or {"versions": []}
        version = next(
            (v for v in record["versions"] if v["version"] == evaluation["set_version"]), None
        )
        if not version or version.get("purged"):
            continue
        reasons = mismatch_reasons(
            evaluation, current, policy_text, scope_text, rubrics, version["items"]
        )
        if reasons:
            stale_reasons = stale_reasons or reasons
            continue
        match = (evaluation, version)
        break
    if not match:
        if stale_reasons:
            return base | {
                "state": "stale",
                "warnings": [WARNINGS["stale"]],
                "stale_reasons": stale_reasons,
                "headline": "Calibration exists only for a different configuration.",
            }
        return base | {"headline": "No calibration recorded for this Judge."}
    evaluation, version = match
    view = view_evaluation(evaluation, detail=False)
    entry = (view.get("by_evaluator") or {}).get(current["id"]) or metrics(
        version["items"], {}, current["id"], p
    )
    state, warnings = classify(
        entry, p, evaluation["status"] == "completed" and entry["evaluator_id"] == current["id"]
    )
    return base | {
        "state": state,
        "warnings": warnings,
        "headline": warnings[-1] if state != "meets" else WARNINGS["meets"],
        "agreement_percent": entry["agreement"]["percent"],
        "matching": entry["counts"]["matching"],
        "comparable": entry["counts"]["validly_judged"],
        "counts": entry["counts"],
        "coverage_percent": entry["coverage_percent"],
        "sufficiency": entry["sufficiency"],
        "confusion": entry["confusion"],
        "evaluation_id": evaluation["id"],
        "evaluation_status": evaluation["status"],
        "evaluated_at": evaluation.get("finished_at") or evaluation["created_at"],
        "conditional_note": "Conditional on this sample and rubric; not certification.",
        "disagreement_ids": entry["disagreement_ids"],
    }


def alignment_for_run(run: dict) -> list[dict]:
    """Human-alignment status for each Judge a saved Run used (read-only; no provider call)."""
    config = run.get("config", {})
    judges = [j for j in config.get("judges", []) if j.get("model") and not j.get("fallback")]
    if not judges and config.get("judge_model"):
        judges = [{"model": config["judge_model"], "url": config.get("judge_url", "")}]
    if not judges:
        return [
            resolve_compatibility("", "") | {"headline": "No LLM Judge was recorded for this Run."}
        ]
    return [
        resolve_compatibility(
            j["model"], j.get("url", ""), config.get("policy"), config.get("scope")
        )
        | {"judge_model": j["model"]}
        for j in judges
    ]


# --- export, retention and deletion -----------------------------------------------------------


def export_evaluation(ident: str) -> dict:
    from .governance import redact

    evaluation = get_evaluation(ident)
    view = view_evaluation(evaluation)
    record = db.get(KIND_SET, evaluation["set_id"]) or {}
    version = next(
        (v for v in record.get("versions", []) if v["version"] == evaluation["set_version"]), None
    )
    payload = {
        "evaluation": view,
        "labels": [
            {"item_id": i["id"], "source": i["source"], "revisions": i["labels"]}
            for i in (version or {}).get("items", [])
            if not i.get("purged")
        ],
        "policy": evaluation["config"]["policy"],
        "evaluator": evaluation["evaluator"],
        "costs": view["costs"],
        "limitations": LIMITATIONS,
        "privacy": {
            "redacted": True,
            "note": "PII regex baseline; names and addresses may remain.",
        },
    }
    return redact(payload)


def _drop_cache(conn, ident: str) -> None:
    from .execution_cache import initialize

    initialize(conn)
    conn.execute("DELETE FROM execution_cache WHERE run_id=?", (ident,))


def delete_evaluation(ident: str) -> dict:
    evaluation = get_evaluation(ident)
    if ident in TASKS or evaluation["status"] in ("queued", "running"):
        raise Conflict("Cancel the evaluation and wait for it to stop before deleting it.")
    with db.connect() as conn:
        metering.init_db(conn)
        _drop_cache(conn, ident)
        conn.execute("DELETE FROM usage_events WHERE run_id=?", (ident,))
        conn.execute("DELETE FROM audit_chain WHERE run_id=?", (ident,)) if _has_chain(
            conn
        ) else None
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (KIND_EVALUATION, ident))
    SECRETS.pop(ident, None)
    return {"deleted": ident}


def _has_chain(conn) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_chain'"
        ).fetchone()
    )


def delete_set(ident: str) -> dict:
    record = get_set(ident)
    dependents = [e for e in db.all_records(KIND_EVALUATION) if e["set_id"] == record["id"]]
    if any(e["id"] in TASKS or e["status"] in ("queued", "running") for e in dependents):
        raise Conflict("Cancel running evaluations of this set before deleting it.")
    for evaluation in dependents:
        delete_evaluation(evaluation["id"])
    with db.connect() as conn:
        if _has_chain(conn):
            conn.execute("DELETE FROM audit_chain WHERE run_id=?", (record["id"],))
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (KIND_SET, record["id"]))
    return {"deleted": record["id"], "evaluations_deleted": len(dependents)}


def purge_source(run_id: str = "", assessment_id: str = "") -> int:
    """Whole-Run/assessment deletion or retention expiry removes copied private evidence.

    Items from the source are replaced by evidence-free tombstones, affected frozen versions are
    marked purged, dependent evaluations lose result text and are invalidated, and judge caches for
    those evaluations are dropped. Audit chains are kept (they hold hashes, not content).
    """

    def hits(item):
        s = item.get("source", {})
        return (run_id and s.get("run_id") == run_id) or (
            assessment_id and s.get("assessment_id") == assessment_id
        )

    def tomb(item):
        return {
            "id": item["id"],
            "purged": True,
            "labels": [],
            "source": {
                "kind": "deleted",
                "case_id": "",
                "run_id": "",
                "bot_slot": -1,
                "base_case_id": "",
            },
            "category": item.get("category", ""),
            "payload_hash": "",
            "source_hash": "",
            "transcript_hash": "",
            "payload": {"transcript": [], "criterion": "", "policy": "", "scope": ""},
        }

    touched = 0
    for record in db.all_records(KIND_SET):
        affected_versions = []

        def mutate(rec, conn):
            nonlocal affected_versions
            rec["draft"]["items"] = [tomb(i) if hits(i) else i for i in rec["draft"]["items"]]
            for version in rec["versions"]:
                if any(hits(i) for i in version["items"]):
                    version["items"] = [tomb(i) if hits(i) else i for i in version["items"]]
                    version["purged"] = True
                    affected_versions.append(version["version"])
            if affected_versions or any(i.get("purged") for i in rec["draft"]["items"]):
                rec["invalidated"] = {
                    "reason": "Source evidence was deleted or expired.",
                    "at": now(),
                }
            chain_append(rec, conn, "source_purged", versions=sorted(set(affected_versions)))

        if any(hits(i) for i in record["draft"]["items"]) or any(
            hits(i) for v in record["versions"] for i in v["items"]
        ):
            _guard(KIND_SET, record["id"], mutate)
            touched += 1
            for evaluation in db.all_records(KIND_EVALUATION):
                if (
                    evaluation["set_id"] == record["id"]
                    and evaluation["set_version"] in affected_versions
                ):

                    def invalidate(ev, conn):
                        ev["results"] = {
                            k: {"status": v.get("status"), "item_id": k, "purged": True}
                            for k, v in ev["results"].items()
                        }
                        ev["invalidated"] = {
                            "reason": "Source evidence was deleted or expired.",
                            "at": now(),
                        }
                        chain_append(ev, conn, "source_purged")

                    _guard(KIND_EVALUATION, evaluation["id"], invalidate)
                    with db.connect() as conn:
                        _drop_cache(conn, evaluation["id"])
    return touched
