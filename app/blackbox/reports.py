"""Render saved evaluation evidence and cost provenance into PDF reports."""

import json
from html import escape
from pathlib import Path

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from ..config import RUNTIME
from . import judge_consistency, judge_provenance


def score_text(value):
    return "Not scored" if value is None else f"{value:.1f}%"


def generate_pdf(run):
    path = RUNTIME / "reports" / f"blackbox-{run['id']}.pdf"
    styles = getSampleStyleSheet()
    font = Path("C:/Windows/Fonts/arial.ttf")
    if font.exists():
        if "StudioArial" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("StudioArial", str(font)))
        for s in styles.byName.values():
            s.fontName = "StudioArial"
    styles["BodyText"].leading = 15
    styles["BodyText"].wordWrap = "CJK"
    story = []

    def paragraph(text, style="BodyText"):
        story.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style]))
        spacer = Spacer(1, 7)
        spacer.keepWithNext = style.startswith("Heading")
        story.append(spacer)

    paragraph("AI Agent Studio — black-box evaluation", "Title")
    paragraph("Run " + run["id"])
    if run.get("studio"):
        paragraph(
            f"{len(run.get('protocol_snapshot', {}).get('cases', [])) or len(run['studio']['bots'][0]['categories'])}-check evaluation index",
            "Heading1",
        )
        paragraph(run["studio"]["formula"])
        paragraph(run["studio"]["confidence_note"])
        comparison = run["studio"].get("comparison")
        if comparison:
            paragraph("Comparison evidence and review checks", "Heading2")
            paragraph(comparison["method_note"])
            paragraph(
                f"Saved tie margin: {comparison['tie_margin']} points; "
                f"family-wise confidence target: {comparison['policy']['confidence']:.0%}. "
                "Intervals are conditional on the authored suite."
            )
            for pair in comparison["pairs"]:
                paragraph(
                    f"{run['targets'][pair['a']]['name']} vs {run['targets'][pair['b']]['name']}: "
                    f"{pair['scenarios']} paired scenarios; difference {pair['difference']}; "
                    + (
                        f"interval {pair['low']} to {pair['high']} points. "
                        if pair["low"] is not None
                        else "Interval unavailable. "
                    )
                    + pair["reason"]
                )
            for check in comparison["readiness"]:
                paragraph(
                    run["targets"][check["bot"]]["name"]
                    + (
                        ": Meets configured checks. "
                        if check["meets_checks"]
                        else ": Review required. "
                    )
                    + " ".join(check["reasons"])
                )
            paragraph(
                "These checks support human review; they do not certify production readiness."
            )
        for bot in run["studio"]["bots"]:
            paragraph(
                f"{bot['name']}: {bot['score']}%; {bot['tested']}/{bot['planned']} scored",
                "Heading2",
            )
            for category in bot["categories"]:
                paragraph(
                    f"{category['name']}: index {category['score']}%; tested quality {category['quality']}; {category['tested']}/{category['planned']} scored; repeat spread {category['spread']} points; {'Low confidence' if category.get('low_confidence') else 'Limited-sample estimate'}"
                )
        provenance = run.get("judge_provenance") or judge_provenance.describe(run)
        paragraph("Which judge scored each case", "Heading2")
        if provenance["mixed_note"]:
            paragraph(provenance["mixed_note"])
        if provenance["unavailable_note"]:
            paragraph(provenance["unavailable_note"])
        for evaluator in provenance["evaluators"]:
            requested = ", ".join(evaluator["requested_models"]) or "Not recorded"
            calibration = evaluator.get("calibration") or {}
            paragraph(
                f"Actual evaluator {evaluator['actual_model']} "
                f"(requested {requested}); provider {evaluator['provider']}"
                + (" (local)" if evaluator["local"] is True else "")
                + f"; returned identifier {', '.join(evaluator['returned_models'])}"
                + f"; family {evaluator['family'] or 'unclassified'}"
                + f"; {evaluator['cases']} case verdict(s)"
                + (
                    f"; fallback on {evaluator['fallback_cases']} case(s): "
                    + "; ".join(evaluator["fallback_reasons"] or ["reason not recorded"])
                    if evaluator["fallback_cases"]
                    else "; no fallback"
                )
                + "; human calibration "
                + (calibration.get("state", "unavailable") if calibration else "unavailable")
                + "."
            )
        if not provenance["evaluators"]:
            paragraph("No LLM judge verdict is recorded for this run.")
        for label, count in provenance["non_judge_engines"].items():
            paragraph(f"{label}: {count} result(s)")
        for warning in provenance["family_warnings"]:
            paragraph(warning)
        paragraph(provenance["revision_note"] + " " + provenance["calibration_note"])
        review = run.get("verdict_consistency") or judge_consistency.review(run)
        paragraph("Saved verdict consistency", "Heading2")
        if review["contradictions"]:
            for row in review["contradictions"]:
                paragraph(
                    f"{row['case']} (bot {row['bot']}, judge {row['model']}, saved score "
                    f"{row['score']}): {row['detail']}"
                )
        else:
            paragraph("No saved verdict contradicts its own explanation.")
        paragraph(review["note"] + " " + review["coverage_note"])
        inputs = run.get("reference_inputs")
        if inputs:
            paragraph("Reference inputs and judge policy", "Heading2")
            profile = inputs["profile"]
            paragraph(
                f"Claim rules {inputs['claim_rules_version']}; declared general facts "
                f"{profile['general_facts']}; declared capabilities {profile['capabilities']}."
            )
            paragraph(profile.get("note", ""))
            if profile.get("provenance"):
                paragraph("Declaration provenance: " + json.dumps(profile["provenance"]))
        policy = run.get("judge_policy")
        if policy:
            requested = ", ".join(j["model"] for j in policy["requested_judges"]) or "none recorded"
            fallbacks = ", ".join(j["model"] for j in policy["declared_fallbacks"]) or "none"
            paragraph(f"Requested judges: {requested}. Declared fallbacks: {fallbacks}.")
            for rule in policy["rules"]:
                paragraph(rule)
            paragraph(policy["discovery_note"])
        paragraph("Audit log", "Heading2")
        paragraph(json.dumps(run.get("audit", []), ensure_ascii=False))
        paragraph(
            "Existing measured-quality statistics below exclude missing evidence; the configured index above applies the requested zero contribution."
        )
    if run.get("governance"):
        paragraph("Governance and run integrity", "Heading1")
        paragraph(json.dumps(run["governance"], ensure_ascii=False))
        paragraph(run.get("export_privacy", {}).get("note", ""))
    for bot in run.get("studio", {}).get("bots", []):
        for sub in bot.get("bias_subtests", []):
            paragraph(
                f"{bot['name']} — Bias: {sub['subtype']} / {sub['status']} / severity {sub['severity']}",
                "Heading2",
            )
            paragraph(sub["reason"])
            for evidence in sub["evidence"]:
                paragraph(evidence["prompt"] + "\n" + evidence["excerpt"])
    paragraph(run["score_formula"])
    for note in run.get("setup_notes", []):
        paragraph(note)
    cost = run.get("costs", {})
    if cost.get("available"):
        from .cost_summary import money

        paragraph("Cost and token usage", "Heading1")
        paragraph(cost["summary"])
        paragraph(cost["coverage_note"])
        paragraph(
            "Pinned price snapshot: "
            + cost["snapshot_id"]
            + "; model rates in USD per 1 million tokens: "
            + json.dumps(cost["prices_used"])
        )
        for key in ("bot", "evaluation"):
            total = cost[key]
            paragraph(
                key.title()
                + (
                    f": {total['input_tokens']} input / {total['output_tokens']} output tokens; "
                    f"cached input {total['cached_input_tokens']}; "
                    f"reasoning output {total['reasoning_tokens']}; local compute estimate "
                )
                + money(total["local_compute_micro_usd"])
                + " (local API cost is zero). Unknown calls: "
                + str(total["unknown_calls"])
            )
        paragraph(
            "Manual INR/USD rate: "
            + str(cost["inr_per_usd"] or "not configured")
            + "; qualifying score threshold: "
            + str(cost["score_threshold"])
            + "; cheapest qualifying slot: "
            + str(cost["cheapest_qualifying_slot"] or "not established")
        )
        if cost["comparison_warning"]:
            paragraph(cost["comparison_warning"])
        for bot in cost["bots"]:
            paragraph(
                bot["name"]
                + ": target total "
                + money(bot["cost_micro_usd"])
                + "; per answer "
                + money(bot["cost_per_answer_micro_usd"])
                + "; per conversation "
                + money(bot["cost_per_conversation_micro_usd"])
                + "; per 1,000 "
                + money(bot["projected_1000_micro_usd"])
            )
            paragraph(
                f"Tokens per answer: {bot['tokens_per_answer']}; "
                f"tokens per conversation: {bot['tokens_per_conversation']}; "
                f"mean latency ms: {bot['mean_latency_ms']}; "
                f"quality per dollar: {bot['quality_per_dollar']}; measurement sources: "
                + ", ".join(bot["token_sources"])
            )
        for key, rows in cost["breakdowns"].items():
            paragraph("Cost by " + key.replace("_", " "), "Heading2")
            for row in rows:
                paragraph(
                    str(row["name"])
                    + ": bot "
                    + money(row["bot"]["cost_micro_usd"])
                    + "; evaluation "
                    + money(row["evaluation"]["cost_micro_usd"])
                    + f"; tokens {row['input_tokens']} in / {row['output_tokens']} out; sources "
                    + ", ".join(row["token_sources"])
                )
        paragraph(
            "Retries: "
            + money(cost["retries"]["cost_micro_usd"])
            + "; failed calls: "
            + money(cost["failed_calls"]["cost_micro_usd"])
            + ". Included in totals; overlapping groups are not added again."
        )
        paragraph("Usage ledger (counts only)", "Heading2")
        for event in cost["events"]:
            paragraph(json.dumps(event, ensure_ascii=False))
    else:
        paragraph("Cost: Unknown. This historical run has no usage ledger.")

    for index, s in enumerate(run["summary"]):
        paragraph(s["name"] + f" — {score_text(s['score'])}", "Heading1")
        paragraph(s["verdict"])
        paragraph(f"Coverage: {s['coverage']}%; ranking eligible: {s['rankable']}")
        for c in s["categories"]:
            paragraph(
                f"{c['name']}: {score_text(c['score'])} | {c['tested']}/{c['total']} tested | {c['not_tested']} Not tested"
            )
        if s.get("sequential_speed"):
            paragraph("Sequential speed metrics: " + json.dumps(s["sequential_speed"]))
        paragraph("Top risks", "Heading2")
        for c in s["risks"]:
            paragraph(
                f"{c['name']} ({score_text(c['score'])}): inspect the linked case evidence; "
                "resolve missing configuration before treating the score as behavior quality."
            )
        paragraph("Strengths on tested criteria", "Heading2")
        for c in s["strengths"]:
            paragraph(f"{c['name']}: {score_text(c['score'])}")
        if not s["strengths"]:
            paragraph("No high-scoring tested categories established.")
        paragraph("Failing examples", "Heading2")
        for ident in s["examples"]:
            c = next(c for c in run["cases"] if c["id"] == ident)
            r = c["results"][index]
            paragraph(c["id"] + ": " + r["reason"])
            for turn in r["transcript"]:
                paragraph("Customer: " + turn["input"])
                paragraph("Bot: " + str(turn.get("output") or turn.get("error")))
    legacy_comparison = run.get("comparison", {}) if not run.get("studio") else {}
    if legacy_comparison:
        paragraph(
            "Comparison: "
            + str(legacy_comparison.get("winner") or "No overall winner")
            + ". "
            + legacy_comparison["reason"],
            "Heading2",
        )
    for pair in legacy_comparison.get("pairs", []):
        paragraph(
            f"Bots {'ABCD'[pair['a']]} vs {'ABCD'[pair['b']]}: "
            + pair["verdict"]
            + "; shared coverage "
            + str(pair["coverage"])
            + "%; confidence "
            + json.dumps(pair["confidence"])
        )
    for row in run.get("judge_agreement", []):
        paragraph(
            row["target"]
            + " second-judge agreement: "
            + str(row["agreement_percent"])
            + f"%; {row['judged']}/{row['sampled']} samples judged. "
            + row["definition"]
        )
    for row in run.get("regressions", []):
        paragraph(
            row["target"]
            + " regression status: "
            + row["status"]
            + "; "
            + row.get("reason", "No baseline saved.")
        )
        for c in row["categories"]:
            paragraph(
                c["category"]
                + ": "
                + str(c["change_points"])
                + " points; "
                + ("REGRESSION ALERT" if row["status"] == "compared" and c["alert"] else "no alert")
            )
    paragraph("Limitations", "Heading2")
    for line in run["limitations"]:
        paragraph(line)
    story.append(PageBreak())
    paragraph("All case evidence", "Heading1")
    for c in run["cases"]:
        paragraph(c["id"] + " — " + c["name"], "Heading2")
        paragraph("Expected: " + c["expected"])
        for i, r in enumerate(c["results"]):
            paragraph(
                run["targets"][i]["name"]
                + f": {score_text(r['score'])} | {r['status']} | "
                + r["reason"]
            )
            for check in r.get("deterministic_checks", []):
                paragraph(
                    "Exact "
                    + check["kind"]
                    + ": "
                    + check["term"]
                    + "; "
                    + ("satisfied" if check["met"] else "failed")
                )
            if r.get("secondary_judge"):
                second = r["secondary_judge"]
                paragraph(
                    "Second judge: " + score_text(second.get("score")) + "; " + second["reason"]
                )
                for quote in second.get("evidence", []):
                    paragraph("Second-judge evidence: " + quote)
            if r.get("needs_review"):
                paragraph(
                    "Evidence needs review: "
                    + r.get("review_reason", "Inspect matched and unmatched quotes.")
                )
            # A score that contradicts its own explanation is unreliable evidence for either
            # outcome. It is named here for the same reason it is named on the screen.
            if r.get("consistency_status") in ("contradictory", "mixed"):
                paragraph(
                    "Judge self-consistency: "
                    + r["consistency_status"]
                    + ". "
                    + "; ".join(
                        f"{row.get('model', 'judge')}: {row.get('detail', '')}"
                        for row in r.get("contradictions", [])
                    )
                    + " The saved score is retained; a contradiction is not evidence of the"
                    + " opposite verdict."
                )
            for verdict in r.get("judges", []):
                state = (verdict.get("consistency") or {}).get("status")
                if state and state != "consistent":
                    paragraph(
                        f"Judge {verdict.get('model', 'not recorded')} consistency: {state}. "
                        + (verdict["consistency"].get("detail") or "")
                    )
            for t in r["transcript"]:
                paragraph("Customer: " + t["input"])
                paragraph("Bot: " + str(t.get("output") or t.get("error")))
        if c.get("evidence_sha256"):
            paragraph("Evidence digest: " + c["evidence_sha256"])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(553, 22, "Page " + str(doc.page))
        canvas.restoreState()

    SimpleDocTemplate(
        str(path),
        title="AI Agent Studio black-box report",
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=42,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return path


NL = chr(10)


def _rate_text(rate: dict) -> str:
    """A rate always shows its denominator, and an empty denominator says so."""
    if rate.get("percent") is None:
        return f"unavailable (0/{rate.get('denominator', 0)})"
    return f"{rate['percent']}% ({rate['numerator']}/{rate['denominator']})"


def calibration_markdown(export: dict) -> str:
    """Readable calibration summary. Reads an already-redacted export; never mutates a report."""
    evaluation = export["evaluation"]
    summary = evaluation.get("summary")
    lines = [
        f"# Judge calibration {evaluation['id']}",
        "",
        f"- Judge requested: {export['evaluator']['requested_model']} at {export['evaluator']['endpoint']}",
        f"- Evaluator fingerprint: {export['evaluator']['id']}",
        f"- Status: {evaluation['status']} (set version {evaluation['set_version']}, "
        f"hash {evaluation['set_version_hash']})",
        f"- Pass threshold: {export['policy']['pass_threshold']}; minimum agreement "
        f"{export['policy']['min_agreement_percent']}%",
    ]
    if summary:
        counts = summary["counts"]
        agreement = summary["agreement"]["percent"]
        lines += [
            f"- State: {summary['state']}",
            "- Agreement: "
            + ("unavailable" if agreement is None else f"{agreement}%")
            + f" ({summary['agreement']['numerator']}/{summary['agreement']['denominator']})",
            "- Counts: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()),
        ]
        matrix = summary["confusion"]
        lines += [
            "",
            "## Confusion matrix",
            "",
            "| | Judge pass | Judge fail |",
            "| --- | --- | --- |",
            f"| Human pass | {matrix['human_pass_judge_pass']} | {matrix['human_pass_judge_fail']} |",
            f"| Human fail | {matrix['human_fail_judge_pass']} | {matrix['human_fail_judge_fail']} |",
            "",
            f"- False acceptance (human fail, Judge pass): {_rate_text(summary['false_acceptance'])}",
            f"- False rejection (human pass, Judge fail): {_rate_text(summary['false_rejection'])}",
            f"- Distinct scenarios: {summary['sufficiency']['distinct_scenarios']} "
            f"({summary['sufficiency']['repeated_scenarios']} with repeats, which do not count "
            "as distinct)",
            "",
            *[f"> {w}" for w in summary["warnings"]],
        ]
        folds = evaluation.get("by_fold") or {}
        if folds:
            lines += [
                "",
                "## Development and held-out folds",
                "",
                "| Fold | Judged | Agreement | Scenarios | State |",
                "| --- | --- | --- | --- | --- |",
                *[
                    f"| {name} | {entry['counts']['validly_judged']} | "
                    f"{_rate_text(entry['agreement'])} | "
                    f"{entry['sufficiency']['distinct_scenarios']} | {entry['state']} |"
                    for name, entry in sorted(folds.items())
                ],
                "",
                "Each fold carries its own denominators and is smaller than the whole sample, "
                "so a fold is descriptive rather than a stronger result.",
            ]
    else:
        lines.append("- Source evidence was deleted; this calibration is invalidated.")
    lines += ["", "## Limitations", *[f"- {item}" for item in export["limitations"]]]
    return NL.join(lines) + NL
