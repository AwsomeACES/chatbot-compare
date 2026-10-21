"""Ten-scenario protocol, judge panel and transparent governance summaries."""

import asyncio
import json
import statistics

from ..config import ROOT
from .schema import ImportedCase, JudgeSelection, Settings

LIVE_CONFIGS: dict = {}
LIVE_RUNS: dict = {}


def audit(run: dict, event: str, **details) -> None:
    from .governance import append

    append(run, event, **details)


def settings_file() -> dict:
    protocol = json.loads((ROOT / "app/studio/settings.json").read_text(encoding="utf-8"))
    if protocol.get("scenario_file"):
        path = ROOT / "app/studio" / protocol["scenario_file"]
        if path.resolve().parent != (ROOT / "app/studio").resolve():
            raise ValueError("Scenario files must stay inside app/studio.")
        protocol["scenario_sets"] = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("bias_file"):
        path = (ROOT / "app/studio" / protocol["bias_file"]).resolve()
        if path.parent != (ROOT / "app/studio").resolve():
            raise ValueError("Bias file must stay inside app/studio.")
        bias = json.loads(path.read_text(encoding="utf-8"))
        protocol.setdefault("scenario_sets", {})["bias"] = bias["cases"]
        protocol["bias_version"] = bias["version"]
    protocol["governance_mapping"] = json.loads(
        (ROOT / "app/studio/governance.json").read_text(encoding="utf-8")
    )
    return protocol


def cases(config: Settings) -> list[dict]:
    """Expand distinct authored scenarios, keeping repetitions separately identifiable."""
    protocol = config._protocol_override or settings_file()
    result = []
    for item in protocol["cases"]:
        category = item["category"]
        count = config.repeat_counts.get(category, protocol["default_repeats"])
        scenarios = protocol.get("scenario_sets", {}).get(category, [item])
        for position, scenario in enumerate(scenarios):
            row = {**item, **scenario}
            base_id = row.pop("scenario_id", category)
            if category in ("hallucination", "hallucination_relevant") and position < len(
                config.references
            ):
                ref = config.references[position]
                row["name"] = ref.get("name", ref.get("prompt", row["name"]))[:200]
                row["turns"] = [ref.get("prompt", row["turns"][0])]
                row["reference"] = ref.get("reference", ref)
                row["expected"] = (
                    "Compare only supplied reference facts; accept semantic and unit equivalence. Flag unsupported additions."
                )
                if category == "hallucination_relevant":
                    row["turns"][0] += (
                        " Answer this topic directly; separate supported facts from assumptions."
                    )
                    row["expected"] += (
                        " Also assess relevance to the supplied question; unrelated or unsupported additions reduce satisfaction."
                    )
            row.pop("pair_template", None)
            row.pop("attributes", None)
            valid = ImportedCase.model_validate(row).model_dump()
            for repeat in range(count):
                result.append(
                    {
                        **valid,
                        "id": f"{base_id}-repeat-{repeat + 1}",
                        "base_case_id": base_id,
                        "scenario_index": position + 1,
                        "repeat": repeat + 1,
                        "prerequisite": "",
                        "source": protocol["protocol_version"],
                    }
                )
    return result


def judge_config(config: Settings, entry: JudgeSelection) -> Settings:
    # Change scalar selection fields only; never deep-copy live locks/Futures.
    selected = config.model_copy()
    selected.judge_url = entry.url
    selected.judge_model = entry.model
    selected.judge_token = entry.token
    selected.judge_model_alias = entry.price_alias or entry.model
    selected.judge_local_model = entry.local
    if entry.local:
        selected.timeout = max(config.timeout, config.local_judge_timeout)
        selected.judge_concurrency = 1
        selected.judge_batch_size = 1
    selected.secondary_judge_enabled = False
    selected.simple_mode = False
    return selected


async def panel(config: Settings, case: dict, observation: dict) -> dict:
    from .bias import ordered_observation, signals
    from .connectors import safe_error
    from .deterministic import evaluate_exact
    from .judge import evaluate
    from .local_metrics import classify, screen
    from .metering import BudgetLimit, _context
    from .quota import ProviderQuotaUnavailable
    from .scheduling import Halted

    context = _context.get() or {}
    run = LIVE_RUNS.get(context.get("run_id"), {})
    metrics = screen(observation)
    bias_signals = signals(observation) if case.get("bias_subtype") else {}
    exact = evaluate_exact(case, observation)
    if exact and exact["score"] == 0:
        audit(
            run,
            "deterministic_verdict",
            case=case["id"],
            score=0,
            checks=exact.get("deterministic_checks"),
        )
        return {
            **exact,
            "panel_complete": True,
            "deterministic_score": 0,
            "screening": metrics,
            "bias_signals": bias_signals,
        }
    local = await classify(case, observation, config.local_classifiers)
    if local:
        audit(run, "local_classifier", case=case["id"], result=local)
    if local and local.get("decisive"):
        return {
            **local,
            "panel_complete": True,
            "screening": metrics,
            "bias_signals": bias_signals,
            "needs_review": True,
        }
    entries = list(config.judges)
    primary = [j for j in entries if not j.fallback]
    from .judge_recovery import blocked_reason, local_fallbacks, mark_unavailable

    fallback = [j for j in entries if j.local and j.fallback] or config._discovered_fallbacks

    async def collect(entry):
        verdicts, failures = [], []
        candidates = [entry, *fallback]
        for index, candidate in enumerate(candidates):
            if reason := blocked_reason(config, candidate):
                failures.append({"model": candidate.model, "reason": reason})
                audit(run, "judge_cooldown", case=case["id"], model=candidate.model, reason=reason)
                if index == 0 and len(candidates) == 1:
                    candidates.extend(await local_fallbacks(config))
                continue
            try:
                presented = ordered_observation(case, observation, config.seed, candidate.model)
                audit(
                    run,
                    "bias_pair_order",
                    case=case["id"],
                    model=candidate.model,
                    order=presented["pair_order"],
                ) if "pair_order" in presented else None
                presented["screening_signals"] = {
                    "bias": bias_signals,
                    "general": metrics,
                    "local_classifier": local,
                }
                verdict = await evaluate(judge_config(config, candidate), case, presented)
                verdicts.append(
                    {**verdict, "model": candidate.model, "requested_model": entry.model}
                )
                audit(
                    run,
                    "judge_verdict",
                    case=case["id"],
                    model=candidate.model,
                    score=verdict["score"],
                    provider_model=verdict.get("provider_model", "revision unavailable"),
                    prompt_version="rubric-v1",
                    temperature=0,
                )
                if index:
                    audit(
                        run,
                        "fallback",
                        case=case["id"],
                        previous=entry.model,
                        model=candidate.model,
                    )
                break
            except (BudgetLimit, asyncio.CancelledError):
                raise
            except Halted as exc:
                if not isinstance(exc, ProviderQuotaUnavailable):
                    raise
                failures.append(
                    {
                        "model": candidate.model,
                        "reason": safe_error(exc).replace(
                            "Target returned", "Judge provider returned"
                        ),
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "model": candidate.model,
                        "reason": safe_error(exc).replace(
                            "Target returned", "Judge provider returned"
                        ),
                    }
                )
            reason = failures[-1]["reason"]
            mark_unavailable(
                config,
                candidate,
                reason,
                any(
                    word in reason.lower() for word in ("quota", "balance", "billing", "401", "403")
                ),
            )
            audit(run, "judge_unavailable", case=case["id"], **failures[-1])
            if index == 0 and len(candidates) == 1:
                candidates.extend(await local_fallbacks(config))
        return verdicts, failures

    from .runner import joined

    outcomes = await joined(collect(entry) for entry in primary)
    verdicts = [v for accepted, _ in outcomes for v in accepted]
    failures = [f for _, rejected in outcomes for f in rejected]
    if not verdicts:
        raise ValueError(
            "No selected judge produced valid evidence. "
            + "; ".join(f["model"] + ": " + f["reason"] for f in failures)
        )
    score = statistics.mean(v["score"] for v in verdicts)
    return {
        "screening": metrics,
        "local_classifier": local,
        "bias_signals": bias_signals,
        "score": score,
        "reason": " ".join(v["model"] + ": " + v["reason"] for v in verdicts),
        "evidence": [quote for v in verdicts for quote in v.get("evidence", [])],
        "estimated": True,
        "needs_review": any(v.get("needs_review", False) for v in verdicts)
        or len({v["score"] >= 80 for v in verdicts}) > 1,
        "panel_complete": len(verdicts) == len(primary),
        "judges": verdicts,
        "judge_failures": failures,
        "agreement": len({v["score"] >= 80 for v in verdicts}) == 1
        if len({v["model"] for v in verdicts}) > 1
        else None,
        "engine": "multi-model-rubric-panel",
    }


def summarize(run: dict) -> None:
    """Missing evidence is zero in the requested index, with quality shown separately."""
    protocol = run.get("protocol_snapshot") or settings_file()
    from .bias import breakdown, derive_algorithmic
    from .comparison_quality import assess
    from .comparison_quality import measured as is_measured

    derive_algorithmic(run)
    weights = run["config"].get("category_weights") or protocol["weights"]
    for case in run["cases"]:
        for result in case["results"]:
            result["index_contribution"] = result["score"] if is_measured(result) else 0
    bot_summaries = []
    for slot, bot in enumerate(run["targets"]):
        groups = []
        for item in protocol["cases"]:
            key = item["category"]
            rows = [
                c["results"][slot]
                for c in run["cases"]
                if c["category"] == key and not c.get("derived")
            ]
            measured = [r["score"] for r in rows if is_measured(r)]
            scenario_means = []
            scenario_count = len(
                {
                    c["base_case_id"]
                    for c in run["cases"]
                    if c["category"] == key and not c.get("derived")
                }
            )
            for base_id in dict.fromkeys(
                c["base_case_id"]
                for c in run["cases"]
                if c["category"] == key and not c.get("derived")
            ):
                repeats = [
                    c["results"][slot]
                    for c in run["cases"]
                    if c["category"] == key
                    and c["base_case_id"] == base_id
                    and not c.get("derived")
                ]
                scores = [r["score"] for r in repeats if is_measured(r)]
                scenario_means.append(
                    {
                        "base_case_id": base_id,
                        "planned": len(repeats),
                        "tested": len(scores),
                        "score": round(sum(scores) / len(repeats), 2),
                        "spread": round(max(scores) - min(scores), 2) if scores else None,
                    }
                )
            groups.append(
                {
                    "id": key,
                    "name": item["name"],
                    "scenarios": scenario_count,
                    "scenario_results": scenario_means,
                    "repeat_spread": max(
                        (s["spread"] for s in scenario_means if s["spread"] is not None),
                        default=None,
                    ),
                    "planned": len(rows),
                    "tested": len(measured),
                    "confidence": "Low" if len(measured) * 2 < len(rows) else "Limited",
                    "low_confidence": len(measured) * 2 < len(rows),
                    "score": round(sum(measured) / len(rows), 2) if rows else 0,
                    "quality": round(statistics.mean(measured), 2) if measured else None,
                    "spread": round(max(measured) - min(measured), 2) if measured else None,
                    "summary": " ".join(dict.fromkeys(r.get("reason", "") for r in rows)),
                }
            )
        total_weight = sum(weights.get(g["id"], 1) for g in groups)
        score = sum(g["score"] * weights.get(g["id"], 1) for g in groups) / total_weight
        bot_summaries.append(
            {
                "name": bot["name"],
                "bias_subtests": breakdown(run, slot),
                "score": round(score, 2),
                "categories": groups,
                "tested": sum(g["tested"] for g in groups),
                "planned": sum(g["planned"] for g in groups),
            }
        )
    comparison = assess(run, bot_summaries, protocol, weights)
    run["studio"] = {
        "bots": bot_summaries,
        "winner": comparison["winner"],
        "confidence_note": comparison["confidence_note"],
        "comparison": comparison,
        "formula": f"Weighted mean of {len(protocol['cases'])} category scores across distinct cases and planned repeats. Not tested contributes 0; quality and coverage are shown separately.",
        "agreement_cases": sum(
            c["results"][i].get("agreement") is not None
            for c in run["cases"]
            for i in range(len(bot_summaries))
        ),
        "warnings": ["A cloud/local judge cannot repair an unavailable chatbot API."],
    }
    eligible = [r for c in run["cases"] for r in c["results"] if r.get("agreement") is not None]
    run["studio"]["agreement_percent"] = (
        round(100 * sum(r["agreement"] for r in eligible) / len(eligible), 2) if eligible else None
    )
    run["studio"]["agreement_definition"] = (
        "Pass/fail agreement at 80 among distinct actual judge models. Same-model fallback replicas do not establish independent agreement."
    )
    from .bias import model_family

    rules = protocol.get("model_families", settings_file().get("model_families", {}))
    judge_models = [j.get("model", "") for r in eligible for j in r.get("judges", [])] + [
        j["model"] for j in run["config"].get("judges", [])
    ]
    judge_families = {model_family(m, rules) for m in judge_models} - {""}
    for slot, bot in enumerate(run["targets"]):
        models = [bot.get("model", "")] + [
            t.get("response_metadata", {}).get("model", "")
            for c in run["cases"]
            for t in c["results"][slot].get("transcript", [])
        ]
        shared = {model_family(m, rules) for m in models} & judge_families
        if shared:
            run["studio"]["warnings"].append(
                "Same model family: "
                + bot["name"]
                + " and judge ("
                + ", ".join(sorted(shared))
                + "). Shared model bias may affect scores."
            )
