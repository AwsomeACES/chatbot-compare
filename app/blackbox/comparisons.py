"""Paired, category-stratified bootstrap. Missing evidence is not a tie."""

import itertools
import random
import statistics
from functools import lru_cache

from .schema import CATEGORIES


@lru_cache(maxsize=128)
def bootstrap(groups, seed, pair_count):
    n = sum(len(g) for g in groups)
    if n < 10 or not groups:
        return {
            "samples": n,
            "low": None,
            "high": None,
            "level": 1 - 0.05 / pair_count,
            "reason": "At least 10 distinct paired scenarios are needed.",
        }
    rng = random.Random(seed)
    means = []
    for _ in range(2000):
        means.append(statistics.mean(sum(rng.choices(g, k=len(g))) / len(g) for g in groups))
    means.sort()
    tail = 0.025 / pair_count
    return {
        "samples": n,
        "low": means[int(tail * len(means))],
        "high": means[min(len(means) - 1, int((1 - tail) * len(means)))],
        "level": 1 - 0.05 / pair_count,
        "reason": (
            "Paired bootstrap of net wins, stratified equally by category; 2,000 "
            "resamples. Family-wise 95% confidence uses Bonferroni adjustment across "
            "pairs. Legacy wording variants are clustered by "
            "topic."
        ),
    }


def pair_record(case, a, b):
    return case.get("pairs", {}).get(f"{a}:{b}", case.get("pair", {}) if (a, b) == (0, 1) else {})


def compare(run, scored):
    n = len(run["targets"])
    threshold = run.get("config", {}).get("min_coverage", 0.8)
    pairs = []
    pair_count = n * (n - 1) // 2
    for a, b in itertools.combinations(range(n), 2):
        cats = []
        groups = []
        latency = []
        for category in run["categories"]:
            planned = [c for c in run["cases"] if c["category"] == category]
            joint = [c for c in planned if scored(c["results"][a]) and scored(c["results"][b])]
            valid = [
                c
                for c in joint
                if pair_record(c, a, b).get("status") == "judged"
                and pair_record(c, a, b).get("winner") in (0, 1, "tie")
            ]
            records = [pair_record(c, a, b) for c in valid]
            count = len(valid)
            coverage = count / len(planned) if planned else 0
            clusters = {}
            for c in valid:
                value = (
                    1
                    if pair_record(c, a, b)["winner"] == 0
                    else -1
                    if pair_record(c, a, b)["winner"] == 1
                    else 0
                )
                cluster = (
                    (int(c["id"].rsplit("-", 1)[-1]) - 1) % 10
                    if c.get("source") == "legacy_template"
                    else c["id"]
                )
                clusters.setdefault(cluster, []).append(value)
                if all(c["results"][i].get("seconds") is not None for i in (a, b)):
                    latency.append(c["results"][a]["seconds"] - c["results"][b]["seconds"])
            if clusters:
                groups.append(tuple(statistics.mean(v) for v in clusters.values()))
            cats.append(
                {
                    "category": category,
                    "name": CATEGORIES[category],
                    "a_wins": sum(p["winner"] == 0 for p in records),
                    "b_wins": sum(p["winner"] == 1 for p in records),
                    "ties": sum(p["winner"] == "tie" for p in records),
                    "not_judged": len(planned) - count,
                    "jointly_tested": len(joint),
                    "judged": count,
                    "total": len(planned),
                    "coverage": round(coverage * 100, 2),
                    "rankable": count > 0 and coverage >= threshold,
                    "a_score": round(statistics.mean(c["results"][a]["score"] for c in valid), 2)
                    if valid
                    else None,
                    "b_score": round(statistics.mean(c["results"][b]["score"] for c in valid), 2)
                    if valid
                    else None,
                    "order_sensitive": sum(
                        pair_record(c, a, b).get("status") == "order_sensitive" for c in joint
                    ),
                }
            )
        eligible = all(c["rankable"] for c in cats)
        terminal = run["status"] not in ("queued", "running")
        ci = (
            bootstrap(tuple(groups), run.get("config", {}).get("seed", 42), pair_count)
            if terminal and eligible
            else {
                "samples": sum(len(g) for g in groups),
                "low": None,
                "high": None,
                "level": 1 - 0.05 / pair_count,
                "reason": "Await completed run and sufficient shared coverage.",
            }
        )
        winner = (
            a
            if eligible and ci["low"] is not None and ci["low"] > 0
            else b
            if eligible and ci["high"] is not None and ci["high"] < 0
            else None
        )
        verdict = (
            "confident_winner"
            if winner is not None
            else "too_close_to_call"
            if eligible and ci["low"] is not None
            else "insufficient_evidence"
        )
        pairs.append(
            {
                "a": a,
                "b": b,
                "categories": cats,
                "rankable": eligible,
                "winner": "ABCD"[winner] if winner is not None else None,
                "winner_index": winner,
                "verdict": verdict,
                "confidence": ci,
                "coverage": round(100 * sum(c["judged"] for c in cats) / len(run["cases"]), 2)
                if run["cases"]
                else 0,
                "min_coverage": threshold * 100,
                "latency_difference_seconds": round(statistics.mean(latency), 3)
                if latency
                else None,
                "cost_difference": None,
                "reason": (
                    "Confident winner on shared evaluated cases."
                    if winner is not None
                    else "Too close to call; confidence interval includes zero."
                    if verdict == "too_close_to_call"
                    else "No winner: insufficient shared coverage, sample size or incomplete run."
                ),
            }
        )
    overall = next(
        (
            i
            for i in range(n)
            if all(p["winner_index"] == i for p in pairs if i in (p["a"], p["b"]))
        ),
        None,
    )
    result = {
        "pairs": pairs,
        "matrix": [
            [
                None if i == j else next(p for p in pairs if {p["a"], p["b"]} == {i, j})["winner"]
                for j in range(n)
            ]
            for i in range(n)
        ],
        "winner": "ABCD"[overall] if overall is not None else None,
        "rankable": all(p["rankable"] for p in pairs),
        "reason": (
            "Overall winner beats every opponent with sufficient coverage and a "
            "confidence interval excluding "
            "zero."
        )
        if overall is not None
        else "No overall winner: at least one matchup is too close or lacks sufficient evidence.",
        "categories": pairs[0]["categories"] if n == 2 else [],
        "coverage": min(p["coverage"] for p in pairs),
        "min_coverage": threshold * 100,
        "latency_difference_seconds": pairs[0]["latency_difference_seconds"] if n == 2 else None,
        "cost_difference": None,
    }
    if n == 2:
        result.update(confidence=pairs[0]["confidence"], verdict=pairs[0]["verdict"])
    return result
