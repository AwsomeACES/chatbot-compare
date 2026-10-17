"""Cost reporting separates target spend from evaluation overhead."""

from collections import defaultdict
from decimal import Decimal

from . import metering, pricing


def totals(rows):
    exact = sum(
        (Decimal(r["cost_exact_micro_usd"]) for r in rows if r["cost_exact_micro_usd"] is not None),
        Decimal(0),
    )
    unknown = sum(r["cost_status"] == "unknown" or r["in_flight"] for r in rows)
    sources = sorted({r["token_source"] for r in rows})
    return {
        "calls": len(rows),
        "local_calls": sum(r["cost_status"] == "local" for r in rows),
        "input_tokens": sum(
            r["input_tokens"]
            + r["cached_input_tokens"]
            + r.get("cache_write_tokens", 0)
            + r.get("cache_write_1h_tokens", 0)
            for r in rows
        ),
        "cached_input_tokens": sum(r["cached_input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] + r["reasoning_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "cost_micro_usd": None if unknown or not rows else pricing.micro(exact),
        "known_cost_micro_usd": pricing.micro(exact),
        "exact_micro_usd": str(exact),
        "unknown_calls": unknown,
        "token_sources": sources,
        "estimated": any(
            r["token_source"] != "reported"
            or r["visibility"] == "external_bot"
            or (r["cost_status"] == "local" and Decimal(r["cost_exact_micro_usd"] or 0) > 0)
            for r in rows
        ),
        "local_compute_micro_usd": pricing.micro(
            sum(
                (
                    Decimal(r["cost_exact_micro_usd"] or 0)
                    for r in rows
                    if r["cost_status"] == "local"
                ),
                Decimal(0),
            )
        ),
    }


def money(value, local=False):
    if value is None:
        return "Unknown"
    amount = Decimal(value) / 1000000
    if amount == 0 and local:
        return "$0 (local)"
    if 0 < amount < Decimal("0.0001"):
        return "<$0.0001"
    return "$" + format(amount, ".6f")


def summarize(run):
    ident = run.get("price_snapshot_id") or run.get("config", {}).get("price_snapshot_id")
    if not ident:
        return {
            "available": False,
            "note": "This run predates cost tracking. Historical costs cannot be reconstructed reliably.",
        }
    snap = pricing.snapshot(ident)
    saved = run["config"].get("cost_settings_snapshot", {})
    rows = metering.events(run["id"])
    target = [r for r in rows if r["role"] == "target"]
    evaluation = [r for r in rows if r["role"] != "target"]
    bot_totals = totals(target)
    eval_totals = totals(evaluation)
    buckets = {}
    for key in ("model_alias", "role", "category", "test_case_id"):
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        buckets[key] = [
            {
                "name": k,
                **totals(v),
                "bot": totals([r for r in v if r["role"] == "target"]),
                "evaluation": totals([r for r in v if r["role"] != "target"]),
            }
            for k, v in groups.items()
        ]
    bots = []
    for i, bot in enumerate(run["targets"]):
        items = [r for r in target if r["bot_slot"] == "ABCD"[i]]
        total = totals(items)
        successes = [r for r in items if r["status"] == "success" and not r["in_flight"]]
        answers = len(successes)
        conversations = len({r.get("conversation_id") or r["test_case_id"] for r in successes})
        raw = Decimal(total["exact_micro_usd"]) if total["cost_micro_usd"] is not None else None
        per_answer = pricing.micro(raw / answers) if raw is not None and answers else None
        per_conversation = (
            pricing.micro(raw / conversations) if raw is not None and conversations else None
        )
        projected = (
            pricing.micro(raw * 1000 / conversations) if raw is not None and conversations else None
        )
        score = run["summary"][i]["score"]
        if len(run["targets"]) == 2:
            shared = [
                c.get("a_score" if i == 0 else "b_score")
                for c in run.get("comparison", {}).get("categories", [])
            ]
            shared = [s for s in shared if s is not None]
            score = round(sum(shared) / len(shared), 2) if shared else None
        bots.append(
            {
                "slot": "ABCD"[i],
                "name": bot["name"],
                **total,
                "answers": answers,
                "conversations": conversations,
                "cost_per_answer_micro_usd": per_answer,
                "cost_per_conversation_micro_usd": per_conversation,
                "projected_1000_micro_usd": projected,
                "tokens_per_answer": round(
                    (total["input_tokens"] + total["output_tokens"]) / answers, 2
                )
                if answers
                else None,
                "tokens_per_conversation": round(
                    (total["input_tokens"] + total["output_tokens"]) / conversations, 2
                )
                if conversations
                else None,
                "mean_latency_ms": round(sum(r["latency_ms"] for r in items) / len(items), 2)
                if items
                else None,
                "score": score,
                "rankable": run["summary"][i].get("rankable", False),
                "quality_per_dollar": float(Decimal(str(score)) * 1000000 / Decimal(projected))
                if len(run["targets"]) <= 2
                and projected
                and score is not None
                and run["summary"][i].get("rankable", False)
                else None,
            }
        )
    different = any(
        b["token_sources"] != bots[0]["token_sources"] or b["estimated"] != bots[0]["estimated"]
        for b in bots[1:]
    )
    eligible = [
        b
        for b in bots
        if b["rankable"]
        and b["score"] is not None
        and b["score"] >= float(saved.get("quality_threshold", 80))
        and b["cost_micro_usd"] is not None
        and b["projected_1000_micro_usd"] is not None
    ]
    if (
        len(bots) > 2
        or different
        or (len(bots) == 2 and not run.get("comparison", {}).get("rankable", False))
    ):
        eligible = []
    cheapest = (
        min(eligible, key=lambda b: b["projected_1000_micro_usd"])["slot"] if eligible else None
    )
    missing = sorted({r["model_alias"] for r in rows if r["cost_status"] == "unknown"})
    driver = max(
        (b for b in buckets["role"] if b["evaluation"]["calls"]),
        key=lambda b: b["evaluation"]["known_cost_micro_usd"],
        default=None,
    )
    paragraph = f"Bot cost: {money(bot_totals['cost_micro_usd'])}. Evaluation cost: {money(eval_totals['cost_micro_usd'])}. "
    paragraph += " ".join(
        f"{b['name']}: {money(b['cost_per_answer_micro_usd'])} per answer." for b in bots
    )
    paragraph += f" Main evaluation cost driver: {driver['name'] if driver and driver['evaluation']['calls'] else 'not measured'}. "
    paragraph += (
        "Some costs use estimated/counted usage or local compute assumptions. "
        if any(b["estimated"] for b in (bot_totals, eval_totals))
        else ""
    )
    paragraph += f"Unknown-cost models: {', '.join(missing) or 'none recorded'}. Price snapshot: {snap['date']} ({snap['source']})."
    return {
        "available": True,
        "snapshot_id": ident,
        "snapshot_date": snap["date"],
        "price_source": snap["source"],
        "bot": bot_totals,
        "evaluation": eval_totals,
        "bots": bots,
        "breakdowns": buckets,
        "top_cases": sorted(
            buckets["test_case_id"], key=lambda b: b["known_cost_micro_usd"], reverse=True
        )[:5],
        "retries": totals([r for r in rows if r["attempt_number"] > 1]),
        "failed_calls": totals([r for r in rows if r["status"] != "success"]),
        "unknown_models": missing,
        "comparison_warning": "Not like-for-like: token measurement sources differ between bots."
        if different
        else "For 3–4 bots, costs are descriptive; cheapest-bot and quality-per-dollar rankings are unavailable."
        if len(bots) > 2
        else "",
        "cheapest_qualifying_slot": cheapest,
        "score_threshold": saved.get("quality_threshold", 80),
        "inr_per_usd": saved.get("inr_per_usd"),
        "summary": paragraph,
        "coverage_note": (
            "All calls dispatched by Studio are metered. External bot internals "
            "(additional models, embeddings, tools and retries) require bot "
            "telemetry and are not inferred."
        ),
        "prices_used": {r["model_alias"]: snap["models"].get(r["model_alias"]) for r in rows},
        "events": rows,
    }


def estimate(config, cases):
    snap = pricing.pin(config)
    saved = config.cost_settings_snapshot
    counts = {
        "input_tokens": saved.get("average_input_tokens", 1000),
        "output_tokens": saved.get("average_output_tokens", 300),
    }

    def component(model, alias, local, calls):
        rates, resolved = pricing.price_for(snap, model, alias, saved)
        value, status = pricing.calculate(counts, rates, local=local)
        if not calls:
            value = Decimal(0)
            status = "no_calls"
        return {
            "model": resolved or "unknown",
            "calls": calls,
            "cost_micro_usd": pricing.micro(value * calls) if value is not None else None,
            "status": status,
        }

    bots = [
        component(
            t.model,
            t.model_alias,
            t.local_model,
            sum(len(c["turns"]) for c in cases if not c.get("derived")),
        )
        for t in config.targets
    ]
    judge_cases = (
        sum(
            c["category"] != "performance" and not c["prerequisite"] and not c.get("derived")
            for c in cases
        )
        if config.judge_enabled
        else 0
    )
    judge_calls = judge_cases * (
        len(config.targets) + len(config.targets) * (len(config.targets) - 1)
    )
    judge = component(
        config.judge_model, config.judge_model_alias, config.judge_local_model, judge_calls
    )
    import math

    second = component(
        config.secondary_judge_model,
        config.secondary_judge_alias,
        config.secondary_judge_local,
        math.ceil(judge_cases * config.secondary_sample_rate) * len(config.targets)
        if config.secondary_judge_enabled
        else 0,
    )
    if config.simple_mode:
        primary = [j for j in config.judges if not j.fallback]
        planned = [
            component(
                j.model,
                j.price_alias or j.model,
                j.local,
                math.ceil(judge_cases * len(config.targets) / config.judge_batch_size),
            )
            for j in primary
        ]
        judge = {
            **judge,
            "model": "selected judge panel",
            "calls": sum(j["calls"] for j in planned),
            "cost_micro_usd": sum(j["cost_micro_usd"] for j in planned)
            if all(j["cost_micro_usd"] is not None for j in planned)
            else None,
            "models": planned,
        }
    combined = {
        **judge,
        "calls": judge["calls"] + second["calls"],
        "cost_micro_usd": judge["cost_micro_usd"] + second["cost_micro_usd"]
        if judge["cost_micro_usd"] is not None and second["cost_micro_usd"] is not None
        else None,
    }
    return {
        "warnings": [
            *[
                f"Bot {i + 1}: enter its underlying model or pricing alias to estimate token cost."
                for i, row in enumerate(bots)
                if row["calls"] and row["cost_micro_usd"] is None
            ],
            *(
                [
                    "AI judge is switched off; 0 judge requests does not mean semantic evaluation is free."
                ]
                if not config.judge_enabled
                else []
            ),
            *(
                ["No runnable semantic cases: review selected categories and prerequisites."]
                if config.judge_enabled and not judge_calls
                else []
            ),
        ],
        "secondary_evaluation": second,
        "estimated": True,
        "bots": bots,
        "evaluation": combined,
        "snapshot_id": snap["id"],
        "snapshot_date": snap["date"],
        "price_source": snap["source"],
        "average_input_tokens": counts["input_tokens"],
        "average_output_tokens": counts["output_tokens"],
        "budget_usd": config.max_budget_usd,
        "note": (
            "Planning estimate: calls x configured average tokens x snapshot prices; "
            "excludes retries, hidden bot calls, and local compute time. Budget "
            "stops new calls; in-flight/opaque provider charges can exceed the "
            "estimate."
        ),
    }
