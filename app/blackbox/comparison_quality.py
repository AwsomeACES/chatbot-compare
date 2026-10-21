"""Paired scenario evidence and conservative, snapshot-bound comparison decisions."""

import itertools
import math
import random
import statistics
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ComparisonPolicy(BaseModel):
    """Defaults keep historical snapshots readable; new runs save these settings."""

    model_config = ConfigDict(extra="forbid")
    method: Literal["paired-scenario-stratified-v1"] = "paired-scenario-stratified-v1"
    resamples: int = Field(default=2000, ge=1000, le=20000)
    confidence: float = Field(default=0.95, ge=0.9, le=0.99)
    min_scenarios: int = Field(default=10, ge=2, le=1000)
    min_scenarios_per_category: int = Field(default=2, ge=2, le=100)
    quality_threshold: float = Field(default=80, ge=0, le=100)


def measured(result: dict) -> bool:
    """Only finite, in-range, evidence-bearing verdicts count as measured."""
    score = result.get("score")
    return (
        result.get("status") in ("passed", "failed")
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
        and 0 <= score <= 100
    )


def panel_signature(result: dict) -> tuple:
    """Compare actual model assignments, retaining duplicate panel entries."""
    return (
        result.get("engine", "legacy-unspecified"),
        tuple(sorted(j.get("model", "") for j in result.get("judges", []))),
    )


@lru_cache(maxsize=128)
def _interval(
    groups: tuple[tuple[float, ...], ...],
    weights: tuple[float, ...],
    seed: int,
    resamples: int,
    confidence: float,
    pair_count: int,
) -> tuple[float, float]:
    """Resample paired scenario means within fixed category strata, never repeats."""
    rng = random.Random(seed)
    total = sum(weights)
    draws = sorted(
        sum(statistics.mean(rng.choices(g, k=len(g))) * w for g, w in zip(groups, weights)) / total
        for _ in range(resamples)
    )
    tail = (1 - confidence) / (2 * pair_count)
    return draws[int(tail * resamples)], draws[min(resamples - 1, int((1 - tail) * resamples))]


def _pair(
    run: dict, a: int, b: int, categories: list[str], weights: dict, policy: ComparisonPolicy
) -> dict:
    groups, details = [], []
    comparable = True
    needs_review = False
    for category in categories:
        rows = [c for c in run["cases"] if c["category"] == category and not c.get("derived")]
        clusters: dict[str, list[float]] = {}
        paired = 0
        for case in rows:
            left, right = case["results"][a], case["results"][b]
            valid = all(measured(r) and r.get("panel_complete", True) for r in (left, right))
            same_panel = panel_signature(left) == panel_signature(right)
            comparable = comparable and same_panel
            needs_review = needs_review or any(r.get("needs_review") for r in (left, right))
            if valid and same_panel:
                paired += 1
                clusters.setdefault(case.get("base_case_id", case["id"]), []).append(
                    left["score"] - right["score"]
                )
        groups.append(tuple(statistics.mean(v) for v in clusters.values()))
        details.append(
            {
                "category": category,
                "planned": len(rows),
                "paired": paired,
                "scenarios": len(clusters),
            }
        )
    complete = all(c["planned"] > 0 and c["paired"] == c["planned"] for c in details)
    samples = sum(len(g) for g in groups)
    enough = samples >= policy.min_scenarios and all(
        len(g) >= policy.min_scenarios_per_category for g in groups
    )
    reason = (
        "Run is not completed."
        if run.get("status") != "completed"
        else "Judge assignments differ on paired cases."
        if not comparable
        else "Some paired evidence or selected judge verdicts are missing."
        if not complete
        else "Paired outcomes have unresolved evidence or judge disagreements."
        if needs_review
        else "Insufficient distinct scenarios; repeats do not increase independent coverage."
        if not enough
        else ""
    )
    low = high = difference = None
    if complete:
        category_weights = tuple(weights.get(c, 1) for c in categories)
        difference = sum(statistics.mean(g) * w for g, w in zip(groups, category_weights)) / sum(
            category_weights
        )
        if not reason:
            n = len(run["targets"])
            low, high = _interval(
                tuple(groups),
                category_weights,
                run["config"].get("seed", 42),
                policy.resamples,
                policy.confidence,
                n * (n - 1) // 2,
            )
    margin = run["protocol_snapshot"].get("tie_margin", 2)
    winner = (
        a
        if low is not None and low > margin
        else b
        if high is not None and high < -margin
        else None
    )
    return {
        "a": a,
        "b": b,
        "winner": winner,
        "scenarios": samples,
        "categories": details,
        "difference": round(difference, 3) if difference is not None else None,
        "low": round(low, 3) if low is not None else None,
        "high": round(high, 3) if high is not None else None,
        "reason": reason
        or (
            "Difference exceeds the saved tie margin."
            if winner is not None
            else "Too close to call."
        ),
    }


def assess(run: dict, bots: list[dict], protocol: dict, weights: dict) -> dict:
    """Return transparent comparison and review gates without changing stored verdicts."""
    policy = ComparisonPolicy.model_validate(protocol.get("comparison", {}))
    categories = [c["category"] for c in protocol["cases"]]
    # A fallback protocol is explicit in the result and never read from mutable UI settings.
    run_view = {**run, "protocol_snapshot": protocol}
    pairs = [
        _pair(run_view, a, b, categories, weights, policy)
        for a, b in itertools.combinations(range(len(bots)), 2)
    ]
    winner = next(
        (
            i
            for i in range(len(bots))
            if pairs and all(p["winner"] == i for p in pairs if i in (p["a"], p["b"]))
        ),
        None,
    )
    category_results = {}
    for category in categories:
        rows = [c for c in run["cases"] if c["category"] == category and not c.get("derived")]
        complete = bool(rows) and all(
            measured(r) and r.get("panel_complete", True) and not r.get("needs_review")
            for c in rows
            for r in c["results"]
        )
        comparable = all(len({panel_signature(r) for r in c["results"]}) <= 1 for c in rows)
        scores = [
            next(g["score"] for g in bot["categories"] if g["id"] == category) for bot in bots
        ]
        leaders = [
            i for i, score in enumerate(scores) if max(scores) - score <= protocol["tie_margin"]
        ]
        category_results[category] = {
            "leaders": leaders
            if complete and comparable and run.get("status") == "completed"
            else [],
            "reason": "Incomplete evidence"
            if not complete
            else "Different judge panels"
            if not comparable
            else "Await completed run"
            if run.get("status") != "completed"
            else "Descriptive category result; no separate significance claim",
        }
    readiness = []
    for i, bot in enumerate(bots):
        rows = [c["results"][i] for c in run["cases"] if not c.get("derived")]
        review_count = sum(
            bool(r.get("needs_review") or r.get("panel_complete") is False) for r in rows
        )
        reasons = []
        if run.get("status") != "completed":
            reasons.append("Run has not completed.")
        if (
            not rows
            or any(not measured(r) for r in rows)
            or any(not g["planned"] for g in bot["categories"])
        ):
            reasons.append("Missing measured evidence.")
        if review_count:
            reasons.append(
                f"{review_count} outcomes need review or have an incomplete judge panel."
            )
        if any(g["score"] < policy.quality_threshold for g in bot["categories"]):
            reasons.append(f"At least one category is below {policy.quality_threshold:g}.")
        readiness.append(
            {
                "bot": i,
                "meets_checks": not reasons,
                "review_count": review_count,
                "reasons": reasons,
            }
        )
    if len(bots) == 1:
        note = "Single bot evaluation."
    elif winner is not None:
        note = "Winner supported by paired scenario intervals against every other bot."
    elif any(p["low"] is None for p in pairs):
        note = "Winner withheld. " + " ".join(
            dict.fromkeys(p["reason"] for p in pairs if p["low"] is None)
        )
    else:
        note = "Too close to call: no bot beats every opponent beyond the saved tie margin."
    note += " Repeats are averaged within each scenario; intervals are conditional on this authored suite, not proof of production quality."
    return {
        "winner": winner,
        "confidence_note": note,
        "pairs": pairs,
        "policy": policy.model_dump(),
        "tie_margin": protocol["tie_margin"],
        "family_pair_count": len(pairs),
        "category_results": category_results,
        "readiness": readiness,
        "method_note": "Paired scenario-mean bootstrap within fixed categories; configured category weights; Bonferroni adjustment across all bot pairs. Percentile intervals are approximate.",
    }
