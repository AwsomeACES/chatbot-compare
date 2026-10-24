"""Who actually evaluated each Case (T-036 provenance).

Read-only: it derives everything from a saved Run and never calls a provider, rescores a Case or
writes a record. Saved Runs from before provenance recording lack the metadata, and those report
`available: False` with an explicit note rather than a reconstructed guess.
"""

#: Verdicts carrying this key were recorded with evaluator provenance.
MARKER = "provenance_version"

UNKNOWN = "Not recorded"
REVISION_NOTE = (
    "Provider-returned model names are not guaranteed immutable revisions, so a silent "
    "upstream change is not detected."
)
MIXED_NOTE = (
    "Different Cases in this Run were scored by different evaluators. Scores are not "
    "interchangeable across evaluators, and a comparison across a mixed panel is not a "
    "confident result."
)
UNAVAILABLE_NOTE = (
    "This Run was saved before evaluator provenance was recorded. The actual evaluator, "
    "provider, fallback history and returned model identifier are unavailable and have not "
    "been reconstructed."
)

#: Engines that are not an LLM Judge at all. Kept distinct from any Judge identity.
NON_JUDGE = {
    "deterministic-text": "Deterministic rule, no Judge",
    "measured-latency": "Measured latency, no Judge",
}


def verdicts(run: dict):
    """Yield every recorded per-model verdict with its Case and bot slot."""
    for case in run.get("cases") or []:
        for slot, result in enumerate(case.get("results") or []):
            if not isinstance(result, dict):
                continue
            for verdict in result.get("judges") or []:
                if isinstance(verdict, dict):
                    yield case, slot, result, verdict


def requested_judges(run: dict) -> list[dict]:
    """The Judges the owner asked for, from the saved configuration."""
    config = run.get("config") or {}
    rows = [
        {
            "model": judge.get("model", ""),
            "endpoint": judge.get("url", ""),
            "local": bool(judge.get("local")),
            "fallback_choice": bool(judge.get("fallback")),
        }
        for judge in config.get("judges") or []
        if judge.get("model")
    ]
    if not rows and config.get("judge_model"):
        rows = [
            {
                "model": config["judge_model"],
                "endpoint": config.get("judge_url", ""),
                "local": bool(config.get("judge_local_model")),
                "fallback_choice": False,
            }
        ]
    return rows


def non_judge_engines(run: dict) -> dict[str, int]:
    """Count results produced without an LLM Judge, so they are never read as a Judge verdict."""
    counts: dict[str, int] = {}
    for case in run.get("cases") or []:
        for result in case.get("results") or []:
            if not isinstance(result, dict):
                continue
            engine = result.get("engine") or ""
            if result.get("judges"):
                continue
            label = NON_JUDGE.get(engine)
            if label is None and engine:
                label = (
                    "Local classifier, no Judge"
                    if result.get("local_classifier") or "classifier" in engine
                    else f"{engine}, no Judge"
                )
            if label:
                counts[label] = counts.get(label, 0) + 1
    return counts


def calibration_for(model: str, endpoint: str, run: dict) -> dict | None:
    """Human-label alignment of one evaluator. Diagnostic; never changes a score."""
    from .judge_calibration import resolve_compatibility

    config = run.get("config") or {}
    try:
        return resolve_compatibility(model, endpoint, config.get("policy"), config.get("scope"))
    except Exception:  # noqa: BLE001 - a diagnostic read must never break the Results view
        return None


def family_of(model: str) -> str:
    from .bias import model_family
    from .studio_engine import settings_file

    return model_family(model, settings_file().get("model_families", {})) or "unclassified"


def family_warnings(run: dict) -> list[str]:
    """Shared bot/Judge model families only, separate from calibration and model agreement."""
    stored = (run.get("studio") or {}).get("family_warnings")
    if stored is not None:
        return list(stored)
    # Older saved Runs kept these inside the general warning list.
    return [w for w in (run.get("studio") or {}).get("warnings", []) if w.startswith("Same model")]


def describe(run: dict) -> dict:
    """Per-evaluator provenance for one saved Run."""
    rows: dict[tuple[str, str], dict] = {}
    recorded = missing = 0
    for _case, _slot, _result, verdict in verdicts(run):
        model = verdict.get("model") or UNKNOWN
        endpoint = verdict.get("endpoint") or UNKNOWN
        has_metadata = MARKER in verdict
        recorded += has_metadata
        missing += not has_metadata
        key = (model, endpoint)
        row = rows.setdefault(
            key,
            {
                "actual_model": model,
                "endpoint": endpoint if has_metadata else UNKNOWN,
                "provider": verdict.get("provider", UNKNOWN) if has_metadata else UNKNOWN,
                "local": verdict.get("local") if has_metadata else None,
                "family": verdict.get("family") or (family_of(model) if model != UNKNOWN else ""),
                "requested_models": [],
                "returned_models": [],
                "engines": [],
                "cases": 0,
                "fallback_cases": 0,
                "fallback_reasons": [],
                "provenance_recorded": has_metadata,
                "revision_note": REVISION_NOTE,
            },
        )
        row["cases"] += 1
        row["provenance_recorded"] = row["provenance_recorded"] and has_metadata
        for field, source in (
            ("requested_models", verdict.get("requested_model")),
            ("returned_models", verdict.get("provider_model")),
            ("engines", verdict.get("engine")),
        ):
            if source and source not in row[field]:
                row[field].append(source)
        if verdict.get("fallback"):
            row["fallback_cases"] += 1
            for reason in verdict.get("fallback_reasons") or []:
                text = f"{reason.get('model', UNKNOWN)}: {reason.get('reason', UNKNOWN)}"
                if text not in row["fallback_reasons"]:
                    row["fallback_reasons"].append(text)

    evaluators = []
    for row in sorted(rows.values(), key=lambda r: (r["actual_model"], r["endpoint"])):
        row["returned_models"] = row["returned_models"] or ["Not supplied by provider"]
        row["calibration"] = (
            calibration_for(row["actual_model"], row["endpoint"], run)
            if row["actual_model"] != UNKNOWN
            else None
        )
        evaluators.append(row)

    requested = requested_judges(run)
    return {
        "available": bool(recorded),
        "partially_available": bool(recorded and missing),
        "unavailable_note": UNAVAILABLE_NOTE if missing else "",
        "verdicts_with_metadata": recorded,
        "verdicts_without_metadata": missing,
        "requested": requested,
        "evaluators": evaluators,
        "non_judge_engines": non_judge_engines(run),
        "mixed_judges": len(evaluators) > 1,
        "mixed_note": MIXED_NOTE if len(evaluators) > 1 else "",
        "family_warnings": family_warnings(run),
        "revision_note": REVISION_NOTE,
        "calibration_note": (
            "Human-label alignment is diagnostic and separate from both the same-family warning "
            "and model-to-model Judge agreement."
        ),
    }
