"""Exports of a run: a CSV with one row per conversation, and a printable HTML report (the browser's "Save as PDF"
turns it into a PDF with every script, Hindi, Tamil and Telugu included, rendered correctly).

Each row / report entry holds: when it ran, the bot and its model, the case and skill, the prompt, the expected
behaviour, the actual response, how it was evaluated (exact checks, AI judge or both), the outcome, the scores and
the failure reason.
"""

import csv
import io
from html import escape

import compliance
import evaluator

OUTCOMES = evaluator.OUTCOMES
COLUMNS = ["executed_at", "bot_id", "bot", "llm", "model_id", "case_id", "category", "repeat", "wording", "outcome",
           "prompt", "expected", "actual_response", "evaluation_method", "exact_checks", "judge_passed",
           "correctness", "helpfulness", "tone", "invented_facts", "fair", "judge_model", "latency_ms",
           "failure_reason", "personal_data_in_reply", "bot_input_tokens", "bot_output_tokens", "bot_total_tokens",
           "bot_cost_usd_estimate", "bot_pricing_source", "judge_tokens", "judge_cost_usd_estimate", "judge_pricing_source"]


outcome = evaluator.outcome


def counts(results):
    return evaluator.outcome_counts(results)


def _session_text(r, key):
    parts, session = [], None
    for t in r["turns"]:
        if t.get("variant") and t["variant"] != session:
            session = t["variant"]
            parts.append(f"[{session}]")
        parts.append(t[key])
    return "\n".join(parts)


def _prompt(case, r):
    if r["turns"]:
        return _session_text(r, "user")
    sessions = (case or {}).get("variants") or [{"turns": (case or {}).get("turns", [])}]
    return "\n".join(t for s in sessions for t in s["turns"])


def _failure(r, verdict):
    if r.get("unsupported"):
        return "skill not supported by this bot's design"
    if r.get("error"):
        return r["error"]
    reasons = list(r.get("check_failures") or [])
    if verdict and (verdict.get("passed") is False or verdict.get("fair") is False or verdict.get("hallucinated")):
        reasons.append(f"judge: {verdict.get('reason', '')}")
    if r.get("judge_error"):
        reasons.append(f"judge error: {r['judge_error']}")
    return "; ".join(reasons)


def _usage_cols(run, r, cfg):
    """The bot's and the judges' tokens for one conversation and their estimated cost (USD; empty when unknown)."""
    u = evaluator.result_usage(r)
    price = cfg.get("pricing")
    judged = [v for v in (r.get("judge"), r.get("judge2")) if v and v.get("usage")]
    jprices = [evaluator.price_of(v.get("model"), run.get("judge_pricing")) for v in judged]
    jcosts = [evaluator.chat_cost(v["usage"], p) if p else None for v, p in zip(judged, jprices)]
    money = lambda x: None if x is None else round(x, 6)
    return {"bot_input_tokens": u and u.get("input_tokens", 0), "bot_output_tokens": u and u.get("output_tokens", 0),
            "bot_total_tokens": u and sum(u.values()),
            "bot_cost_usd_estimate": money(evaluator.chat_cost(u, price)) if u and price else None,
            "bot_pricing_source": (price or {}).get("source"),
            "judge_tokens": sum(sum(v["usage"].values()) for v in judged) if judged else None,
            "judge_cost_usd_estimate": money(sum(jcosts)) if judged and None not in jcosts else None,
            "judge_pricing_source": "; ".join(sorted({p["source"] for p in jprices if p and p.get("source")})) or None}


def rows(run):
    configs = {b["id"]: b for b in run.get("bot_configs", [])}
    labels = {b["id"]: b["label"] for b in run["bots"]}
    try:
        cases = {c["id"]: c for c in evaluator.load_suite(run["suite"])["cases"]}
    except (OSError, ValueError):
        cases = {}
    out = []
    for r in sorted(run["results"], key=lambda r: (r["case_id"], r["bot_id"], r.get("repeat", 0), r.get("wording", 0))):
        cfg, j = configs.get(r["bot_id"], {}), r.get("judge") or {}
        method = [m for m, on in (("exact checks", r.get("checks") is not None), ("AI judge", bool(j))) if on]
        latencies = [t["latency_ms"] for t in r["turns"] if t.get("latency_ms") is not None]
        out.append({
            "executed_at": r.get("at") or run["created_at"], "bot_id": r["bot_id"],
            "bot": labels.get(r["bot_id"], r["bot_id"]), "llm": cfg.get("llm"), "model_id": cfg.get("model"),
            "case_id": r["case_id"], "category": r["category"], "repeat": r.get("repeat", 0) + 1,
            "wording": r.get("wording", 0), "outcome": outcome(r), "prompt": _prompt(cases.get(r["case_id"]), r),
            "expected": r.get("rubric") or "", "actual_response": _session_text(r, "bot") if r["turns"] else "",
            "evaluation_method": " + ".join(method) or "none", "exact_checks": r.get("checks"),
            "judge_passed": j.get("passed"), "correctness": j.get("correctness"), "helpfulness": j.get("helpfulness"),
            "tone": j.get("tone"), "invented_facts": j.get("hallucinated"), "fair": j.get("fair"),
            "judge_model": j.get("model") or (run.get("judge_model") if j else None),
            "latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            "failure_reason": _failure(r, j) if outcome(r) != "pass" else "",
            "personal_data_in_reply": ", ".join(f"{k} {n}" for k, n in (r.get("pii") or {}).items()),
            **_usage_cols(run, r, cfg)})
    return out


def csv_text(run):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    for row in rows(run):
        w.writerow({k: "" if v is None else v for k, v in row.items()})
    return "﻿" + buf.getvalue()  # BOM, so Excel opens Hindi / Tamil / Telugu text correctly


# ---------- Printable report ----------

STYLE = """
:root { --ink:#0f172a; --ink-2:#475569; --line:#e3e8f0; --soft:#f4f6fb; --accent:#4f46e5;
        --good:#006300; --bad:#b42323; --warn:#8a5a00; }
* { box-sizing: border-box; }
body { font: 12px/1.45 system-ui, -apple-system, "Segoe UI", "Noto Sans", sans-serif; color: var(--ink); margin: 24px; }
h1 { font-size: 20px; margin: 0 0 4px; } h2 { font-size: 15px; margin: 22px 0 8px; color: var(--accent); }
.meta { color: var(--ink-2); margin: 0 0 4px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 12px; }
th, td { border-bottom: 1px solid var(--line); padding: 5px 6px; text-align: left; vertical-align: top; }
th { background: var(--soft); font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-2); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pass { color: var(--good); font-weight: 700; } .fail, .error { color: var(--bad); font-weight: 700; }
.blocked, .not-supported, .not-graded { color: var(--warn); font-weight: 700; }
.case { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin: 0 0 8px; break-inside: avoid; }
.case h3 { font-size: 12.5px; margin: 0 0 4px; display: flex; justify-content: space-between; gap: 8px; }
.case pre { white-space: pre-wrap; word-break: break-word; margin: 2px 0 6px; font: inherit; background: var(--soft);
            padding: 5px 7px; border-radius: 6px; max-height: none; }
.label { font-weight: 700; color: var(--ink-2); font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; }
.toolbar { margin: 0 0 16px; } .toolbar button { font: inherit; padding: 6px 14px; border-radius: 8px; border: 0;
           background: var(--accent); color: #fff; font-weight: 600; cursor: pointer; }
@media print { body { margin: 0; } .toolbar { display: none; } h2 { break-after: avoid; } }
"""


def _clip(text, n=4000):
    text = text or ""
    return text if len(text) <= n else text[:n] + f"\n… ({len(text) - n} more characters)"


def report_html(run):
    """A standalone report page; Ctrl+P / "Save as PDF" in the browser makes the PDF."""
    e = escape
    summary = run.get("summary") or {}
    data = rows(run)
    by_bot = {b["id"]: [r for r in run["results"] if r["bot_id"] == b["id"]] for b in run["bots"]}
    gate = {b["id"]: b for b in compliance.gate(run)["bots"]} if run.get("status") == "done" else {}
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>Chatbot Compare report {e(run['id'])}</title><style>{STYLE}</style></head><body>",
           "<div class='toolbar'><button onclick='print()'>Save as PDF / print</button></div>",
           f"<h1>{e(' vs '.join(b['label'] for b in run['bots']))}</h1>",
           f"<p class='meta'>Run {e(run['id'])} · {e(run.get('suite_name', ''))} · {e(run['created_at'].replace('T', ' '))} · "
           f"{'AI judge: ' + e(run.get('judge_model') or '') if run.get('judge') else 'exact checks only'}"
           f"{' · ×' + str(run.get('repeats')) + ' repeats' if run.get('repeats', 1) > 1 else ''}</p>"]
    prov = run.get("provenance") or {}
    if prov:
        out.append(f"<p class='meta'>Provenance: commit {e((prov.get('git_commit') or '—')[:10])}"
                   f"{' (uncommitted changes)' if prov.get('git_dirty') else ''} · suite {e((prov.get('suite_sha256') or '')[:12])}"
                   f" · policy v{e(str(prov.get('policy_version')))} · started by {e(prov.get('started_by') or '')}</p>")

    out.append("<h2>Summary</h2><table><thead><tr><th>Bot</th><th>Model</th>"
               + "".join(f"<th class='num'>{e(o)}</th>" for o in OUTCOMES)
               + "<th class='num'>Overall</th><th class='num'>Accuracy</th><th class='num'>Safety</th>"
                 "<th class='num'>No halluc.</th><th class='num'>Fairness</th><th class='num'>Median s</th>"
                 "<th>Release gate</th></tr></thead><tbody>")
    srow = {b["id"]: b for b in summary.get("bots", [])}
    cfg = {b["id"]: b for b in run.get("bot_configs", [])}
    fmt = lambda v: "—" if v is None else f"{v:g}"
    for b in run["bots"]:
        s, c = srow.get(b["id"], {}), counts(by_bot[b["id"]])
        g = gate.get(b["id"])
        out.append(f"<tr><td>{e(b['label'])}</td><td>{e(cfg.get(b['id'], {}).get('llm') or '—')}</td>"
                   + "".join(f"<td class='num'>{c[o]}</td>" for o in OUTCOMES)
                   + "".join(f"<td class='num'>{fmt(s.get(k))}</td>" for k in ("overall", "accuracy", "safety", "hallucination", "bias"))
                   + f"<td class='num'>{fmt(round(s['latency_p50'] / 1000, 1)) if s.get('latency_p50') else '—'}</td>"
                   + f"<td class='{'pass' if g and g['verdict'] == 'pass' else 'fail' if g and g['verdict'] == 'fail' else 'blocked'}'>"
                   + (e(g["verdict"].upper()) if g else "—") + "</td></tr>")
    out.append("</tbody></table>")
    if gate:
        for b in run["bots"]:
            failed = [r for r in gate[b["id"]]["rules"] if r["ok"] is False]
            if failed:
                out.append(f"<p><b>{e(b['label'])}</b>: " + "; ".join(
                    f"{'blocks' if r['level'] == 'block' else 'warning'}: {e(r['text'])}" for r in failed) + "</p>")

    cats = summary.get("categories") or sorted({r["category"] for r in run["results"]})
    out.append("<h2>Pass rate by skill (%)</h2><table><thead><tr><th>Skill</th>"
               + "".join(f"<th class='num'>{e(b['label'])}</th>" for b in run["bots"]) + "</tr></thead><tbody>")
    for cat in cats:
        out.append(f"<tr><td>{e(cat)}</td>" + "".join(
            f"<td class='num'>{fmt((srow.get(b['id'], {}).get('by_category') or {}).get(cat))}</td>" for b in run["bots"]) + "</tr>")
    out.append("</tbody></table>")

    out += _cost_html(run, summary)
    failing = [r for r in data if r["outcome"] != "pass"]
    out.append(f"<h2>Cases that did not pass ({len(failing)})</h2>")
    out += [_case_html(r) for r in failing] or ["<p>Every scored case passed.</p>"]
    passing = [r for r in data if r["outcome"] == "pass"]
    out.append(f"<h2>Cases that passed ({len(passing)})</h2>")
    out += [_case_html(r) for r in passing]
    out.append("</body></html>")
    return "".join(out)


def _case_html(r):
    e = escape
    cls = r["outcome"].replace(" ", "-")
    scores = " · ".join(f"{k} {r[k]}/5" for k in ("correctness", "helpfulness", "tone") if r[k] is not None)
    extra = [f"repeat {r['repeat']}" if r["repeat"] > 1 else "", f"rewording {r['wording']}" if r["wording"] else ""]
    return (f"<div class='case'><h3><span>{e(r['case_id'])} <span class='meta'>· {e(r['category'])} · {e(r['bot'])}"
            f" ({e(r['llm'] or '—')}){''.join(' · ' + x for x in extra if x)}</span></span>"
            f"<span class='{cls}'>{e(r['outcome'].upper())}</span></h3>"
            f"<div class='label'>Prompt</div><pre>{e(_clip(r['prompt'], 1500))}</pre>"
            f"<div class='label'>Expected</div><pre>{e(r['expected'] or '—')}</pre>"
            f"<div class='label'>Actual response</div><pre>{e(_clip(r['actual_response']) or '—')}</pre>"
            f"<div class='meta'><b>Evaluated by:</b> {e(r['evaluation_method'])}"
            f"{' · exact checks ' + ('passed' if r['exact_checks'] else 'failed') if r['exact_checks'] is not None else ''}"
            f"{' · judge ' + ('pass' if r['judge_passed'] else 'fail') if r['judge_passed'] is not None else ''}"
            f"{' · ' + scores if scores else ''}{' · invented facts' if r['invented_facts'] else ''}"
            f"{' · judge model ' + e(r['judge_model']) if r['judge_model'] else ''}"
            f"{' · ' + str(r['latency_ms']) + ' ms' if r['latency_ms'] is not None else ''}"
            f" · {e(r['executed_at'].replace('T', ' '))}</div>"
            + (f"<div class='meta fail'>Why: {e(r['failure_reason'])}</div>" if r["failure_reason"] else "")
            + (f"<div class='meta fail'>Personal data in reply: {e(r['personal_data_in_reply'])}</div>"
               if r["personal_data_in_reply"] else "") + "</div>")


def _cost_html(run, summary):
    """Tokens and estimated cost: each bot side by side, the AI judge apart."""
    e = escape
    bots = [b for b in summary.get("bots", []) if b.get("cost")]
    ju = summary.get("judge_usage")
    if not any(b["cost"].get("usage_results") for b in bots) and not ju:
        return ["<h2>Tokens and estimated cost</h2><p>No bot or judge in this run reported token counts.</p>"]
    money = lambda v: "—" if v is None else f"${v:,.4f}"
    num = lambda v: "—" if v is None else f"{v:,}"
    out = ["<h2>Tokens and estimated cost (estimates, USD)</h2><table><thead><tr><th>Who</th><th class='num'>Reported</th>"
           "<th class='num'>Input</th><th class='num'>Output</th><th class='num'>Total tokens</th>"
           "<th class='num'>Est. cost (run)</th><th class='num'>Per 100 chats</th><th>Pricing source</th></tr></thead><tbody>"]
    for b in bots:
        c, has = b["cost"], b["cost"].get("usage_results")
        out.append(f"<tr><td>{e(b['label'])}</td><td class='num'>{c.get('usage_results', 0)} of {c.get('chats', 0)} chats</td>"
                   f"<td class='num'>{num(c.get('input_tokens') if has else None)}</td>"
                   f"<td class='num'>{num(c.get('output_tokens') if has else None)}</td>"
                   f"<td class='num'>{num(c.get('total_tokens') if has else None)}</td>"
                   f"<td class='num'>{money(c.get('total_cost'))}</td><td class='num'>{money(c.get('cost_per_100'))}</td>"
                   f"<td>{e(c.get('pricing_source') or ('not reported' if not has else 'no price set'))}</td></tr>")
    if ju:
        srcs = "; ".join(f"{m}: {r['pricing_source'] or 'no price set'}" for m, r in ju["by_model"].items())
        out.append(f"<tr><td><b>AI judge</b></td><td class='num'>{ju['usage_calls']} of {ju['calls']} calls</td>"
                   f"<td class='num'>{num(ju['input_tokens'])}</td><td class='num'>{num(ju['output_tokens'])}</td>"
                   f"<td class='num'>{num(ju['total_tokens'])}</td><td class='num'>{money(ju['cost'])}</td><td class='num'>—</td>"
                   f"<td>{e(srcs)}</td></tr>")
    out.append("</tbody></table><p class='meta'>Estimates from the tokens each bot and the judge reported, priced with "
               "bots.json (USD per million tokens). Only conversations whose every reply reported tokens are counted.</p>")
    return out
