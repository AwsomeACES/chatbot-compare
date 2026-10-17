"""Configuration-only preflight. Does not contact a target or judge."""

from .catalog import build_cases, reference_cases
from .schema import CATEGORIES


def preview(config):
    from .easy_setup import BASE_POLICY, judge_defaults

    cfg = config.model_copy(deep=True)
    cfg.policy = cfg.policy.strip() or BASE_POLICY
    cfg.scope = cfg.scope.strip()
    cfg.judge_model = cfg.judge_model.strip() or judge_defaults()["model"]
    cases = build_cases(cfg)
    rows = []
    for category in cfg.categories:
        group = [c for c in cases if c["category"] == category]
        unavailable = sorted({c["prerequisite"] for c in group if c["prerequisite"]})
        runnable = sum(not c["prerequisite"] for c in group)
        reasons = unavailable if not runnable else []
        if not cfg.consent:
            reasons.append("Allow test messages to the chatbot.")
        if any(t.kind == "zip" for t in cfg.targets):
            reasons.append(
                "ZIP execution requires an isolated runner; paste a running chatbot URL instead."
            )
        if category != "performance" and cfg.judge_enabled:
            if not cfg.judge_model:
                reasons.append("Configure an AI judge model.")
            if not cfg.judge_consent:
                reasons.append("Enable AI judge data-sharing consent.")
        note = ""
        if cfg.secondary_judge_enabled and not cfg.secondary_judge_consent:
            reasons.append("Enable separate second-judge data-sharing consent.")
        if category == "hallucination":
            note = (
                "Reference-grounded factual accuracy."
                if reference_cases(cfg)
                else (
                    "Reference-free probes: invented model numbers, policies, ratings and "
                    "shipments. Measures unsupported claims and uncertainty; not catalogue "
                    "accuracy."
                )
            )
        if any(c.category == category for c in cfg.custom_cases):
            note = (
                "Imported explicit cases replace built-in cases for this category; "
                "inspect their criteria and reference "
                "facts."
            )
        if category == "guardrails" and not config.policy.strip():
            note = "Uses the disclosed Studio generic safety policy."
        if unavailable and runnable:
            note += (
                " "
                + str(runnable)
                + "/"
                + str(len(group))
                + " cases can run; the rest lack explicit checks or prerequisites."
            )
        rows.append(
            {
                "runnable_cases": runnable,
                "category": category,
                "name": CATEGORIES[category],
                "ready": not reasons,
                "reasons": reasons,
                "note": note,
                "planned_cases": len(group),
                "sources": sorted({c["source"] for c in group}),
            }
        )
    return {
        "categories": rows,
        "runnable_categories": [r["category"] for r in rows if r["ready"]],
        "excluded_categories": [r["category"] for r in rows if not r["ready"]],
        "note": "Configuration check only. Connection, quota and judge availability are checked during execution.",
    }
