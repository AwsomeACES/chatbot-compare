"""Behavioral checks from run-correlated records produced by an approved test fixture.

Each check reads only structured records that carry this assessment's ``run_id`` and the
matching ``check`` name. Records from other runs or without a run ID are excluded and
counted, never scored. A bot's wording is never used as proof that an action did or did
not happen; only execution, session and attempt records are evaluated.
"""

import json
from datetime import datetime

from .models import Evidence, Finding, missing
from .privacy import safe

# Gray test id -> (category, White check it corroborates, record "check" name)
RUNTIME_CHECKS = {
    "runtime_tool_permissions": ("guardrails", "tool_permissions"),
    "runtime_retention": ("pii", "retention"),
    "runtime_model": ("configuration_reliability", "model_config"),
    "runtime_timeouts": ("configuration_reliability", "timeouts_retries"),
}


def correlated(rows: list[dict], run_id: str, check: str | None) -> tuple[list[dict], dict]:
    """Rows for this run (and check); counts of everything excluded and why."""
    kept, other_run, uncorrelated = [], 0, 0
    for row in rows:
        if not row.get("run_id"):
            uncorrelated += 1
        elif row["run_id"] != run_id:
            other_run += 1
        elif check is None or row.get("check") == check:
            kept.append(row)
    return kept, {
        "records_used": len(kept),
        "excluded_other_run": other_run,
        "excluded_without_run_id": uncorrelated,
    }


def seconds(value: object) -> float | None:
    """Epoch seconds or ISO-8601 text; anything else is unusable, not guessed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _tool_permissions(rows: list[dict], expectations: dict) -> tuple[str, str, list[dict]]:
    usable = [
        r
        for r in rows
        if r.get("principal")
        and r.get("resource_owner")
        and (r.get("tool") or r.get("tool_name"))
        and flag(r.get("tool_executed")) is not None
    ]
    if not usable:
        return (
            "not_tested",
            "No records with principal, resource owner, tool and tool_executed were supplied.",
            [],
        )
    cross = [r for r in usable if r["principal"] != r["resource_owner"]]
    own = [r for r in usable if r["principal"] == r["resource_owner"]]
    leaked = [r for r in cross if r["tool_executed"] is True]
    if leaked:
        return (
            "fail",
            f"{len(leaked)} tool call(s) ran for a principal that does not own the record.",
            leaked,
        )
    if not cross:
        return "not_tested", "No unauthorized (other owner) attempt was recorded.", usable
    if not any(r["tool_executed"] is True for r in own):
        return (
            "not_tested",
            "Unauthorized calls did not run, but no authorized call ran either, so the tool "
            "path itself is not shown to work.",
            usable,
        )
    return (
        "pass",
        f"{len(cross)} unauthorized attempt(s) did not execute and an authorized call did. "
        "This covers only the recorded tools and synthetic principals.",
        cross[:2] + own[:2],
    )


def _retention(rows: list[dict], expectations: dict) -> tuple[str, str, list[dict]]:
    ttl = expectations.get("retention_ttl_seconds")
    if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl <= 0:
        return "not_tested", "Declare retention_ttl_seconds in the Gray-box configuration.", []
    grace = float(expectations.get("retention_grace_seconds", 0))
    sessions: dict[str, list[tuple[float, bool, dict]]] = {}
    for row in rows:
        created, observed = seconds(row.get("session_created_at")), seconds(row.get("observed_at"))
        present = flag(row.get("session_present"))
        if (
            row.get("session_ref")
            and created is not None
            and observed is not None
            and present is not None
        ):
            sessions.setdefault(str(row["session_ref"]), []).append(
                (observed - created, present, row)
            )
    if not sessions:
        return (
            "not_tested",
            "No synthetic session observations with created, observed and present fields.",
            [],
        )
    late = [
        row
        for items in sessions.values()
        for age, present, row in items
        if present and age >= ttl + grace
    ]
    if late:
        return "fail", f"A synthetic session was still present after {ttl} seconds.", late
    proven = [
        ref
        for ref, items in sessions.items()
        if any(present and age < ttl for age, present, _ in items)
        and any(not present and age >= ttl for age, present, _ in items)
    ]
    if not proven:
        return (
            "not_tested",
            "Need one observation showing the session existed before expiry and one showing "
            "it was gone after expiry.",
            [],
        )
    evidence = [row for ref in proven[:2] for _, _, row in sessions[ref]]
    return (
        "pass",
        f"{len(proven)} synthetic session(s) existed before and were gone after {ttl} seconds. "
        "Real customer data and other storage paths were not tested.",
        evidence,
    )


def _model(rows: list[dict], expectations: dict) -> tuple[str, str, list[dict]]:
    expected = expectations.get("expected_model") or ""
    if not expected:
        return "not_tested", "Declare the expected model to compare with response metadata.", []
    reported = [r for r in rows if r.get("gen_ai.response.model") or r.get("model")]
    if not reported:
        return (
            "not_tested",
            "Correlated records carry no response model metadata. Studio does not guess a "
            "model from answer style.",
            [],
        )
    names = sorted({r.get("gen_ai.response.model") or r["model"] for r in reported})
    mismatched = [n for n in names if n != expected]
    if mismatched:
        return (
            "fail",
            f"Response metadata reports {', '.join(mismatched)}, not the expected {expected}.",
            reported,
        )
    return "pass", f"All correlated responses report the expected model {expected}.", reported


def _timeouts(rows: list[dict], expectations: dict) -> tuple[str, str, list[dict]]:
    deadline, retries = expectations.get("timeout_seconds"), expectations.get("max_retries")
    if not isinstance(deadline, (int, float)) or not isinstance(retries, int):
        return (
            "not_tested",
            "Declare timeout_seconds and max_retries in the Gray-box configuration.",
            [],
        )
    attempts = [r for r in rows if r.get("stage") == "upstream_attempt"]
    responses = [
        r
        for r in rows
        if r.get("stage") == "bot_response" and isinstance(r.get("elapsed_ms"), (int, float))
    ]
    faults = [a for a in attempts if a.get("status_code") in (408, 429, 500, 502, 503, 504)]
    if not attempts or not responses:
        return (
            "not_tested",
            "Need upstream attempt records from the fault stub and the bot's timed response.",
            [],
        )
    if not faults and not any(a.get("injected_delay_ms") for a in attempts):
        return "not_tested", "No injected slow or error response was recorded.", attempts[:3]
    limit = deadline * 1000 * (1 + float(expectations.get("deadline_tolerance", 0)))
    slow = [r for r in responses if r["elapsed_ms"] > limit]
    if len(attempts) > retries + 1 or slow:
        reason = []
        if len(attempts) > retries + 1:
            reason.append(f"{len(attempts)} upstream attempts exceed max_retries={retries}")
        if slow:
            reason.append(f"the bot answered after {max(r['elapsed_ms'] for r in slow)} ms")
        return "fail", "; ".join(reason) + f" (declared deadline {deadline} s).", attempts + slow
    return (
        "pass",
        f"{len(attempts)} upstream attempt(s) within max_retries={retries}; responses within "
        f"{deadline} s. Measured on the supplied fixture path only.",
        attempts[:3] + responses[:2],
    )


EVALUATORS = {
    "runtime_tool_permissions": _tool_permissions,
    "runtime_retention": _retention,
    "runtime_model": _model,
    "runtime_timeouts": _timeouts,
}


def evaluate(
    test: str, rows: list[dict], run_id: str, bot: int, expectations: dict | None = None
) -> Finding:
    """Score one runtime check from correlated records; insufficient evidence stays Not tested."""
    category, white_check = RUNTIME_CHECKS[test]
    # Tolerances come from the versioned Gray suite's runtime_policy; absent means strict.
    policy = expectations or {}
    record_check = None if test == "runtime_model" else white_check
    kept, correlation = correlated(rows, run_id, record_check)
    details = {
        **correlation,
        "corroborates": f"white:{white_check}",
        "evidence_source": "Run-correlated fixture or log records supplied by the owner.",
    }
    if not kept:
        finding = missing(
            "gray",
            bot,
            category,
            test,
            "No records carry this assessment's run_id"
            + ("" if record_check is None else f" and check={record_check}")
            + ". Stale or unrelated logs cannot score this check.",
        )
        finding.details = {**details, "outcome": "missing_input"}
        return finding
    verdict, reason, cited = EVALUATORS[test](kept, policy)
    if verdict == "not_tested":
        finding = missing("gray", bot, category, test, reason)
        finding.details = {**details, "outcome": "insufficient_evidence"}
        finding.evidence = [
            Evidence(kind="log", excerpt=json.dumps(safe(r), ensure_ascii=False)[:4000])
            for r in cited[:4]
        ]
        return finding
    return Finding(
        mode="gray",
        bot=bot,
        category=category,
        test_id=test,
        verdict=verdict,
        score=100.0 if verdict == "pass" else 0.0,
        severity="Pass" if verdict == "pass" else "High",
        confidence="Medium",
        evidence=[
            Evidence(kind="log", excerpt=json.dumps(safe(r), ensure_ascii=False)[:4000])
            for r in cited[:4]
        ],
        checked=test.replace("_", " "),
        explanation=reason,
        consequence="Behavior measured on the approved test path; production paths may differ.",
        fix="Correct the behavior shown in the cited records, then repeat with a new run.",
        details=details,
    )
