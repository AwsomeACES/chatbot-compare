"""Explicit per-bot baselines; never silently replace the reference run."""

import hashlib
import json
import statistics
import uuid

from .. import database as db


def bot_key(target):
    return hashlib.sha256(
        json.dumps([target["name"].strip().casefold(), target["url"].rstrip("/")]).encode()
    ).hexdigest()


def protocol(run):
    config = run["config"]
    value = {
        "cases": [
            {
                k: c.get(k)
                for k in ("id", "category", "turns", "parallel", "reference", "expected", "checks")
            }
            for c in sorted(run["cases"], key=lambda c: c["id"])
        ],
        "categories": sorted(run["categories"]),
        "policy": config.get("policy"),
        "scope": config.get("scope"),
        "judge": [
            config.get("judge_enabled", True),
            config.get("judge_url") if config.get("judge_enabled", True) else None,
            config.get("judge_model") if config.get("judge_enabled", True) else None,
        ],
        "latency_budget_seconds": config.get("latency_budget_seconds"),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def snapshot(targets):
    return [(db.get("baseline_pointer", bot_key(t)) or {}).get("baseline_id") for t in targets]


def save_baseline(run, index):
    if not 0 <= index < len(run["targets"]):
        raise ValueError("Unknown bot index.")
    if run["status"] != "completed" or not run["summary"][index]["rankable"]:
        raise ValueError(
            "Choose a completed run with sufficient coverage in every selected category."
        )
    baseline = {
        "id": str(uuid.uuid4()),
        "run_id": run["id"],
        "target": run["targets"][index]["name"],
        "bot_key": bot_key(run["targets"][index]),
        "protocol": protocol(run),
        "cases": {
            c["id"]: {
                "score": c["results"][index]["score"],
                "status": c["results"][index]["status"],
            }
            for c in run["cases"]
        },
    }
    db.save("baseline", baseline)
    db.save("baseline_pointer", {"id": baseline["bot_key"], "baseline_id": baseline["id"]})
    return {
        "baseline_id": baseline["id"],
        "run_id": run["id"],
        "target": baseline["target"],
        "note": "Saved for future runs with the same bot name, URL and evaluation protocol.",
    }


def regressions(run, scored):
    rows = []
    cutoff = run["config"].get("regression_threshold", 5)
    coverage = run["config"].get("min_coverage", 0.8)
    for i, target in enumerate(run["targets"]):
        ids = run.get("baseline_ids", [])
        ident = ids[i] if len(ids) > i else None
        row = {
            "target": target["name"],
            "baseline_id": ident,
            "status": "no_baseline",
            "categories": [],
            "alerts": [],
        }
        base = db.get("baseline", ident) if ident else None
        if base:
            row["baseline_run_id"] = base["run_id"]
            if base["protocol"] != protocol(run):
                row.update(
                    status="incompatible",
                    reason="Case set, policy, judge or evaluation protocol changed; save a new comparable baseline.",
                )
            else:
                enough = True
                for category in run["categories"]:
                    planned = [c for c in run["cases"] if c["category"] == category]
                    shared = [
                        c
                        for c in planned
                        if scored(c["results"][i]) and scored(base["cases"].get(c["id"], {}))
                    ]
                    ok = bool(shared) and len(shared) / len(planned) >= coverage
                    enough = enough and ok
                    old = (
                        statistics.mean(base["cases"][c["id"]]["score"] for c in shared)
                        if shared
                        else None
                    )
                    new = (
                        statistics.mean(c["results"][i]["score"] for c in shared)
                        if shared
                        else None
                    )
                    delta = round(new - old, 2) if shared else None
                    row["categories"].append(
                        {
                            "category": category,
                            "baseline_score": old,
                            "current_score": new,
                            "change_points": delta,
                            "shared": len(shared),
                            "planned": len(planned),
                            "alert": ok and delta < 0 and -delta >= cutoff,
                        }
                    )
                row["status"] = (
                    "compared"
                    if enough and run["status"] not in ("running", "queued")
                    else "insufficient_evidence"
                )
                if row["status"] == "compared":
                    row["alerts"] = [c for c in row["categories"] if c["alert"]]
                row["reason"] = (
                    f"Alerts flag drops of at least {cutoff:g} percentage points on shared cases; they are not a statistical significance claim."
                )
        rows.append(row)
    return rows
