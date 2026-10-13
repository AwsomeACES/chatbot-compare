"""AI governance on top of the results: release gate, human sign-off, risk register, model cards and retention.

  gate        checks a run against governance.json's release_gate, per bot: pass, warn (passes, with warnings)
              or fail (blocked). Block rules: run finished with the AI judge, results unchanged since the run was
              sealed, minimum scores, zero-tolerance skills, no critical regressions, approved models only. Warn
              rules: personal data in replies, too few human judge-review labels, judge spot-check accuracy.
  sign-off    a named reviewer approves or rejects a bot for release from a given run. Approving a bot the gate
              blocked needs an explicit override with a written justification. Saved in runs/signoffs.json with the
              gate result, the policy hash and the run's results hash, and written to the audit log.
  risks       the risk register in governance.json, with each risk's live status per bot from its latest run
  model cards per bot: intended use, model, data, evaluation results, limitations, oversight, release status
  retention   deletes runs older than data.retention_days, except baselines and runs with a sign-off (evidence)

Usage:
  .venv/bin/python compliance.py gate <run_id>                     exit 0 pass, 1 warnings, 2 blocked, 3 error
  .venv/bin/python compliance.py signoff <run_id> <bot_id> approve|reject --reviewer NAME [--note TEXT] [--override]
  .venv/bin/python compliance.py report [-o FILE]                  model cards + risk register as Markdown
  .venv/bin/python compliance.py audit [--limit N] [--head SEQ:HASH]  verify the audit log (and against a head
                                                                   published off this machine), show recent entries
  .venv/bin/python compliance.py anchor [--reason TEXT]            publish the log's head (webhook and/or S3)
  .venv/bin/python compliance.py purge [--dry-run]                 apply the retention policy
  .venv/bin/python compliance.py scan                              personal data in suites and store data files
  .venv/bin/python compliance.py review-profile <suite> <profile> --reviewer NAME
      the bot's owner confirms its store profile: the facts its cases are filled with, the store data the judge
      sees and which skills count as "not supported". Saved in the suite with a hash of what was reviewed; the
      release gate warns about a bot whose profile nobody but the test author has checked, or that changed since
"""

import fnmatch
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import evaluator
import governance
import review

SIGNOFFS_FILE = os.path.join(evaluator.RUNS_DIR, "signoffs.json")
BOTS_FILE = os.path.join(evaluator.ROOT, "bots.json")
DECISIONS = ("approve", "reject")
MIN_OVERRIDE_NOTE = 20  # characters of justification needed to approve a blocked bot
_lock = threading.Lock()


def allowed(name, patterns):
    return bool(name) and any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns)


def configured_bots():
    """The enabled bots in bots.json (without validating them; the server does that)."""
    with open(BOTS_FILE) as f:
        return [b for b in json.load(f)["bots"] if b.get("enabled", True)]


# ---------- Release gate ----------

def _failed_cases(run, bot_id, category):
    """Cases of a skill with at least one scored sample that failed (strict: one bad repeat is enough)."""
    return sorted({r["case_id"] for r in run["results"]
                   if r["bot_id"] == bot_id and r["category"] == category and not r.get("unsupported")
                   and not r.get("blocked") and evaluator._case_passed(r) is False})


def judge_models(run, bot_id=None):
    """The models that actually graded this run (or this bot's results); older runs: the configured list."""
    used = {v["model"] for r in run["results"] if bot_id is None or r["bot_id"] == bot_id
            for v in (r.get("judge"), r.get("judge2")) if v and v.get("model")}
    used |= {c["model"] for c in run.get("comparisons") or [] if c.get("model")}
    if not used:
        used = {m.strip() for m in (run.get("judge_model") or "").split(",") if m.strip()}
        if run.get("second_judge_model"):
            used.add(run["second_judge_model"])
    return sorted(used)


def _rule(rules, rule_id, level, ok, text, value=None):
    """ok: True passed, False failed, None not applicable (doesn't count either way)."""
    rules.append({"id": rule_id, "level": level, "ok": ok, "text": text, "value": value})


def _model_rules(rules, run, cfg, bot_id, policy):
    models = policy.get("models") or {}
    llm_name = cfg.get("llm")
    _rule(rules, "approved_bot_llm", "block", allowed(llm_name, models.get("bot_llms", [])),
          f"bot LLM {llm_name or '(not declared in bots.json)'} "
          + ("is in the approved inventory" if allowed(llm_name, models.get("bot_llms", [])) else "is not approved"))
    used = judge_models(run, bot_id)
    bad = [m for m in used if not allowed(m, models.get("judges", []))]
    _rule(rules, "approved_judges", "block", not bad if run.get("judge") else None,
          (f"unapproved judge model(s): {', '.join(bad)}" if bad else f"judges approved ({', '.join(used)})")
          if run.get("judge") else "no AI judge in this run")


def gate(run, policy=None, review_stats=None, baselines=None):
    """The release gate for every bot in a run. See the module docstring."""
    policy = policy or governance.load_policy()
    g = policy.get("release_gate") or {}
    warn = g.get("warn") or {}
    summary = {b["id"]: b for b in (run.get("summary") or {}).get("bots", [])}
    configs = {b["id"]: b for b in run.get("bot_configs", [])}
    done = run.get("status") == "done" and bool(run.get("summary"))
    integrity = governance.integrity(run) if done else None
    reg = {b["id"]: b for b in evaluator.regressions(run, baselines)["bots"]} if done else {}
    stats = review_stats if review_stats is not None else review.stats()
    out = []
    for bot in run["bots"]:
        b, rules = summary.get(bot["id"], {}), []
        _rule(rules, "finished", "block", done, "run finished" if done else f"run is {run.get('status')}")
        if g.get("require_judge"):
            _rule(rules, "judge", "block", bool(run.get("judge")),
                  "graded by the AI judge" if run.get("judge") else "run without the AI judge (exact checks only)")
        _rule(rules, "integrity", "block" if integrity == "modified" else "warn",
              None if integrity is None else integrity == "intact",
              {"intact": "results unchanged since the run was recorded",
               "modified": "results were changed after the run was recorded in the audit log",
               "unsealed": "run predates the audit log, so its results can't be verified"}.get(integrity, "not checked"))
        for k, minimum in (g.get("min_scores") or {}).items():
            v = b.get(k)
            _rule(rules, f"min_{k}", "block", None if not done else v is not None and v >= minimum,
                  f"{k} {'not measured' if v is None else v} (minimum {minimum})")
        for cat, most in (g.get("max_failed_cases") or {}).items():
            failed = _failed_cases(run, bot["id"], cat) if done else []
            _rule(rules, f"max_failed_{cat}", "block", None if not done else len(failed) <= most,
                  f"{len(failed)} {cat} case(s) failed (at most {most})" + (f": {', '.join(failed)}" if failed else ""))
        if "max_critical_regressions" in g:
            r = reg.get(bot["id"], {})
            crit = [a["text"] for a in r.get("alerts", []) if a["level"] == "critical"]
            compared = r.get("status") == "compared"
            _rule(rules, "critical_regressions", "block", len(crit) <= g["max_critical_regressions"] if compared else None,
                  (f"{len(crit)} critical regression(s) against the baseline" + (f": {'; '.join(crit)}" if crit else ""))
                  if compared else "no baseline to compare with", len(crit) if compared else None)
        if g.get("approved_models_only"):
            _model_rules(rules, run, configs.get(bot["id"], {}), bot["id"], policy)
        if run.get("judge") and done:
            overlap = b.get("label") in ((run.get("summary") or {}).get("judge_overlap") or [])
            _rule(rules, "judge_independence", "warn", not overlap,
                  "the main judge is the same model family as this bot's LLM and no second judge from another family "
                  "checked it" if overlap else "graded by a judge from another model family, or checked by one")
        profile_id = configs.get(bot["id"], {}).get("profile")
        try:
            status, rv = profile_review(evaluator.load_suite(run["suite"]), profile_id) if profile_id else (None, None)
        except (OSError, ValueError):
            status, rv = None, None
        if status:
            _rule(rules, "profile_reviewed", "warn", status == "reviewed",
                  f"store profile '{profile_id}' reviewed by {rv['by']} on {rv['at'][:10]}" if status == "reviewed" else
                  f"store profile '{profile_id}' changed since {rv['by']} reviewed it" if status == "changed" else
                  f"store profile '{profile_id}' (its facts and which skills count as not supported) hasn't been "
                  "reviewed by the bot's owner: compliance.py review-profile")
        if "max_unknown_pii" in warn:
            pii = b.get("unknown_pii")
            n = sum(pii.values()) if pii is not None else None
            _rule(rules, "unknown_pii", "warn", None if n is None else n <= warn["max_unknown_pii"],
                  "personal data in replies not measured (older run)" if n is None else
                  f"{n} piece(s) of personal data in replies that aren't in the test data"
                  + (f" ({', '.join(f'{k} {c}' for k, c in pii.items())}; cases: {', '.join(b.get('pii_cases', []))})"
                     if n else ""))
        if "min_review_labels" in warn:
            _rule(rules, "review_labels", "warn", stats["labels"] >= warn["min_review_labels"],
                  f"{stats['labels']} human judge-review labels (want {warn['min_review_labels']})")
        if "min_judge_spot_accuracy" in warn:
            acc = (stats.get("spot") or {}).get("judge_passed")
            _rule(rules, "judge_accuracy", "warn", acc is not None and acc["pct"] >= warn["min_judge_spot_accuracy"],
                  f"judge matched humans on {acc['pct']}% of {acc['n']} random spot-checks "
                  f"(want {warn['min_judge_spot_accuracy']}%)" if acc else "no random spot-check labels yet")
        failed = [r for r in rules if r["ok"] is False]
        verdict = ("fail" if any(r["level"] == "block" for r in failed) else "warn" if failed else "pass")
        out.append({"id": bot["id"], "label": bot["label"], "verdict": verdict, "rules": rules})
    return {"run_id": run["id"], "policy_version": policy.get("version"),
            "policy_sha256": governance.file_sha256(governance.POLICY_FILE), "integrity": integrity, "bots": out}


def gate_text(result):
    lines = [f"Release gate for run {result['run_id']} (policy v{result['policy_version']}):"]
    for b in result["bots"]:
        lines.append(f"- {b['label']}: {b['verdict'].upper()}")
        lines += [f"    {'BLOCK' if r['level'] == 'block' else 'WARN'}: {r['text']}"
                  for r in b["rules"] if r["ok"] is False]
    return "\n".join(lines)


# ---------- Store profile review ----------
# Whoever writes the suite also writes every bot's profile, including the capabilities that decide which cases count
# for that bot. When that person owns one of the bots, the other bots' owners should confirm their profiles.

def profile_digest(profile):
    """Hash of what a profile review covers: the profile (without its review) and its data files' contents."""
    files = {p: governance.file_sha256(os.path.expanduser(p)) for p in profile.get("data_files", [])}
    return governance.sha256({"profile": {k: v for k, v in profile.items() if k != "review"}, "files": files})


def profile_review(suite, profile_id):
    """("reviewed" | "changed" | "unreviewed", the review or None) for one of a suite's profiles."""
    profile = (suite.get("profiles") or {}).get(profile_id)
    if profile is None:
        return None, None
    review = profile.get("review")
    if not review:
        return "unreviewed", None
    return ("reviewed" if review.get("sha256") == profile_digest(profile) else "changed"), review


def review_profile(suite_id, profile_id, reviewer):
    path = os.path.join(evaluator.SUITES_DIR, f"{evaluator.load_suite(suite_id) and suite_id}.json")
    with open(path, encoding="utf-8") as f:
        suite = json.load(f)
    if profile_id not in (suite.get("profiles") or {}):
        raise KeyError(profile_id)
    reviewer = (reviewer or "").strip()[:100]
    if not reviewer:
        raise ValueError("Name the reviewer (the bot's owner)")
    profile = suite["profiles"][profile_id]
    profile["review"] = {"by": reviewer, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sha256": profile_digest(profile)}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(suite, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    governance.record("profile.review", f"{suite_id}/{profile_id}", reviewer=reviewer, sha256=profile["review"]["sha256"])
    return profile["review"]


# ---------- Sign-off ----------

def load_signoffs():
    try:
        with open(SIGNOFFS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _save_signoffs(data):
    tmp = SIGNOFFS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, SIGNOFFS_FILE)


def signoff(run_id, bot_id, decision, reviewer, note="", override=False):
    """Record a release decision for one bot from one run. Raises KeyError (no such run / bot) or ValueError."""
    run = evaluator.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    if bot_id not in {b["id"] for b in run["bots"]}:
        raise KeyError(bot_id)
    reviewer, note = (reviewer or "").strip()[:100], (note or "").strip()[:2000]
    if decision not in DECISIONS:
        raise ValueError("decision must be approve or reject")
    if not reviewer:
        raise ValueError("Name the reviewer")
    if run["status"] != "done":
        raise ValueError("Only a finished run can be signed off")
    result = gate(run)
    g = next(b for b in result["bots"] if b["id"] == bot_id)
    if decision == "approve":
        if result["integrity"] == "modified":
            raise ValueError("This run's results were changed after it was recorded; it can't be approved")
        if g["verdict"] == "fail" and not override:
            raise ValueError("The release gate blocks this bot: " + "; ".join(
                r["text"] for r in g["rules"] if r["ok"] is False and r["level"] == "block")
                + ". Approving it anyway needs an override with a justification.")
        if g["verdict"] == "fail" and len(note) < MIN_OVERRIDE_NOTE:
            raise ValueError(f"An override needs a justification of at least {MIN_OVERRIDE_NOTE} characters in the note")
    entry = {"run_id": run_id, "bot_id": bot_id, "label": g["label"], "decision": decision, "reviewer": reviewer,
             "note": note, "override": bool(decision == "approve" and g["verdict"] == "fail"),
             "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "actor": governance.current_actor(),
             "gate_verdict": g["verdict"], "failed_rules": [r["id"] for r in g["rules"] if r["ok"] is False],
             "policy_version": result["policy_version"], "policy_sha256": result["policy_sha256"],
             "results_sha256": governance.seal(run),
             "llm": next((c.get("llm") for c in run.get("bot_configs", []) if c["id"] == bot_id), None)}
    with _lock:
        data = load_signoffs()
        data.append(entry)
        _save_signoffs(data)
    governance.record("signoff", run_id, bot=bot_id, decision=decision, reviewer=reviewer, override=entry["override"],
                      gate_verdict=g["verdict"], failed_rules=entry["failed_rules"], note=note)
    entry["anchor"] = governance.anchor(f"sign-off: {g['label']} {decision}d from run {run_id}")
    return entry


def release_status(signoffs=None):
    """{bot_id: its latest sign-off}, flagged when the policy changed since."""
    current = governance.file_sha256(governance.POLICY_FILE)
    out = {}
    for s in sorted(signoffs if signoffs is not None else load_signoffs(), key=lambda s: s["at"]):
        out[s["bot_id"]] = {**s, "policy_changed": s.get("policy_sha256") != current}
    return out


def signoffs_for(run_id):
    return [s for s in load_signoffs() if s["run_id"] == run_id]


# ---------- Retention ----------

def purge(dry_run=False, now=None):
    """Runs past data.retention_days, except baselines, runs with a sign-off and runs still going."""
    days = (governance.load_policy().get("data") or {}).get("retention_days")
    if not days:
        return {"retention_days": None, "runs": [], "kept": 0}
    cutoff = ((now or datetime.now()) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    evaluator.load_runs(only_new=True)
    keep = set(evaluator.load_baselines().values()) | {s["run_id"] for s in load_signoffs()}
    old = [r for r in evaluator.list_runs() if r["created_at"] < cutoff and r["status"] != "running"]
    gone = sorted(r["id"] for r in old if r["id"] not in keep)
    if not dry_run and gone:
        for run_id in gone:
            evaluator.delete_run(run_id, reason=f"retention ({days} days)")
        governance.record("retention.purge", None, retention_days=days, runs=gone)
    return {"retention_days": days, "cutoff": cutoff, "runs": gone, "kept": len(old) - len(gone)}


# ---------- Risk register and model cards ----------

def latest_runs():
    """{bot_id: its most recent finished run in which it was scored}."""
    out = {}
    for row in evaluator.list_runs():  # newest first
        if row["status"] != "done":
            continue
        run = evaluator.get_run(row["id"])
        for b in (run.get("summary") or {}).get("bots", []):
            if b["cases"] and b["id"] not in out:
                out[b["id"]] = run
    return out


def _risk_status(risk, bot_id, run, policy, stats, gate_bot, audit_ok):
    metric = risk.get("metric", "manual")
    kind, _, key = metric.partition(":")
    if kind == "manual":
        return {"status": "manual", "value": None}
    if kind == "policy" and key == "pii_redact":
        mode = governance.pii_mode(policy)
        return {"status": "ok" if mode == "redact" else "breach", "value": mode}
    if kind == "review":
        acc = (stats.get("spot") or {}).get("judge_passed")
        value = acc["pct"] if acc else None
    elif run is None:
        return {"status": "no data", "value": None}
    elif kind == "policy" and key == "approved_models":
        rules = [r for r in gate_bot["rules"] if r["id"] in ("approved_bot_llm", "approved_judges")]
        bad = [r["text"] for r in rules if r["ok"] is False]
        return {"status": "breach" if bad else "ok", "value": "; ".join(bad) or "approved"}
    elif kind == "audit":
        state = governance.integrity(run)
        if audit_ok and state == "unsealed":  # run predates the audit log
            return {"status": "no data", "value": state}
        return {"status": "ok" if audit_ok and state == "intact" else "breach", "value": state}
    elif kind == "regressions":
        r = next((x for x in gate_bot["rules"] if x["id"] == "critical_regressions"), None)
        if not r or r["ok"] is None:
            return {"status": "no data", "value": None}
        value = r["value"]
    else:
        b = next((x for x in run["summary"]["bots"] if x["id"] == bot_id), {})
        value = (b.get("by_category") or {}).get(key) if kind == "category" else b.get(key)
    if value is None:
        return {"status": "no data", "value": None}
    ok = ("min" not in risk or value >= risk["min"]) and ("max" not in risk or value <= risk["max"])
    return {"status": "ok" if ok else "breach", "value": value}


def overview():
    """Everything the Governance tab shows."""
    policy = governance.load_policy()
    stats = review.stats()
    audit = governance.verify_log()
    runs = latest_runs()
    status = release_status()
    gates, bots = {}, []
    for cfg in configured_bots():
        run = runs.get(cfg["id"])
        if run is not None and run["id"] not in gates:
            gates[run["id"]] = {b["id"]: b for b in gate(run, policy, stats)["bots"]}
        g = gates[run["id"]].get(cfg["id"]) if run is not None else None
        b = next((x for x in run["summary"]["bots"] if x["id"] == cfg["id"]), None) if run else None
        bots.append({"id": cfg["id"], "label": cfg["label"], "llm": cfg.get("llm"), "app": evaluator.app_of(cfg),
                     "run": {"id": run["id"], "created_at": run["created_at"], "integrity": governance.integrity(run),
                             "judge_model": run.get("judge_model"), "provenance": run.get("provenance")} if run else None,
                     "gate": g, "signoff": status.get(cfg["id"]), "card": model_card(cfg, policy, run, b, stats)})
    risks = [{**risk, "status": {b["id"]: _risk_status(risk, b["id"], runs.get(b["id"]), policy, stats, b["gate"],
                                                       audit["ok"])
                                 for b in bots}} for risk in policy.get("risks", [])]
    return {"policy": {k: policy.get(k) for k in ("version", "owners", "release_gate", "models", "data")}
            | {"sha256": governance.file_sha256(governance.POLICY_FILE)},
            "bots": bots, "risks": risks, "audit": audit, "retention": purge(dry_run=True),
            "review": {"labels": stats["labels"], "spot": (stats.get("spot") or {}).get("judge_passed")},
            "signoffs": sorted(load_signoffs(), key=lambda s: s["at"], reverse=True)[:50]}


def model_card(cfg, policy, run, b, stats):
    """A model card for one bot, from bots.json, governance.json and its latest scored run."""
    app = evaluator.app_of(cfg)
    system = (policy.get("systems") or {}).get(app, {})
    owners = policy.get("owners") or {}
    card = {"name": system.get("name") or cfg["label"], "owner": owners.get(app) or owners.get("policy"),
            "intended_use": system.get("intended_use") or cfg.get("description"),
            "users": system.get("users"), "out_of_scope": system.get("out_of_scope"),
            "risk_class": system.get("eu_ai_act"),
            "model": {"llm": cfg.get("llm"), "model_id": cfg.get("model"), "adapter": cfg.get("type"),
                      "paid": bool(cfg.get("pricing") and any(v for k, v in cfg["pricing"].items() if k != "source")),
                      "approved": allowed(cfg.get("llm"), (policy.get("models") or {}).get("bot_llms", []))},
            "data": {"profile": cfg.get("profile"), "trace": bool(cfg.get("trace"))},
            "evaluation": None, "limitations": [], "oversight": {
                "human_review_labels": stats["labels"],
                "judge_spot_accuracy": ((stats.get("spot") or {}).get("judge_passed") or {}).get("pct")}}
    if run is None or b is None:
        return card
    card["evaluation"] = {
        "run_id": run["id"], "date": run["created_at"], "suite": run.get("suite_name"),
        "judge_model": ", ".join(judge_models(run, cfg["id"])) or None, "repeats": run.get("repeats", 1),
        "rewordings": run.get("rewordings"),
        "scores": {k: b.get(k) for k in ("overall", "accuracy", "safety", "hallucination", "bias", "quality", "speed",
                                         "coverage", "robustness", "grounded")},
        "overall_range": b.get("overall_range"), "by_category": b.get("by_category"),
        "latency_p50_ms": b.get("latency_p50"), "cost_per_100": (b.get("cost") or {}).get("cost_per_100"),
        "provenance": run.get("provenance")}
    lim = card["limitations"]
    for key, what in (("unsafe_cases", "Failed safety cases"), ("hallucinated_cases", "Invented facts in"),
                      ("biased_cases", "Unequal treatment in"), ("brittle_cases", "Passes only the original wording of"),
                      ("unsupported", "Not designed for"), ("pii_cases", "Personal data not in its test data in")):
        if b.get(key):
            lim.append(f"{what}: {', '.join(b[key])}")
    return card


# ---------- Markdown report ----------

def _cell(v):
    return "—" if v is None else str(v).replace("|", "\\|")


def report_markdown(ov=None):
    ov = ov or overview()
    p = ov["policy"]
    out = [f"# AI governance report", "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M')} by Chatbot Compare from governance.json v{p['version']} "
           f"(sha256 {(p['sha256'] or '')[:12]}). Framework references are indicative mappings to help an assessor, "
           "not a certification.", "", "## Release status", "",
           "| Bot | LLM | Latest run | Gate | Sign-off |", "|---|---|---|---|---|"]
    for b in ov["bots"]:
        s = b["signoff"]
        out.append(f"| {_cell(b['label'])} | {_cell(b['llm'])} | {_cell(b['run'] and b['run']['created_at'])} | "
                   f"{_cell(b['gate'] and b['gate']['verdict'].upper())} | "
                   + (f"{s['decision']}d by {_cell(s['reviewer'])} on {s['at'][:10]}"
                      + (" (override)" if s.get("override") else "") + (" — policy changed since" if s["policy_changed"] else "")
                      if s else "none") + " |")
    out += ["", "## Risk register", "", "| ID | Risk | Severity | Target | Frameworks | Status |", "|---|---|---|---|---|---|"]
    for r in ov["risks"]:
        target = (f"≥ {r['min']}" if "min" in r else f"≤ {r['max']}" if "max" in r else "control")
        status = "; ".join(f"{bid}: {st['status']}" + (f" ({st['value']})" if st["value"] not in (None, "") else "")
                           for bid, st in r["status"].items())
        out.append(f"| {r['id']} | {_cell(r['title'])} | {r.get('severity', '')} | {_cell(r.get('metric'))} {target} | "
                   f"{_cell('; '.join(r.get('frameworks', [])))} | {_cell(status)} |")
    out += ["", "Mitigations:", ""] + [f"- **{r['id']}** {r.get('mitigation', '')}" for r in ov["risks"]]
    out += ["", "## Model cards"]
    for b in ov["bots"]:
        c = b["card"]
        out += ["", f"### {b['label']}", "", f"- **System:** {_cell(c['name'])} · owner: {_cell(c['owner'])}",
                f"- **Intended use:** {_cell(c['intended_use'])}", f"- **Users:** {_cell(c['users'])}",
                f"- **Out of scope:** {_cell(c['out_of_scope'])}", f"- **Risk class:** {_cell(c['risk_class'])}",
                f"- **Model:** {_cell(c['model']['llm'])} ({_cell(c['model']['model_id'])}, adapter "
                f"{_cell(c['model']['adapter'])}; {'paid' if c['model']['paid'] else 'free'}; "
                f"{'approved' if c['model']['approved'] else 'NOT in the approved inventory'})",
                f"- **Data:** store profile `{_cell(c['data']['profile'])}`; debug trace "
                f"{'on' if c['data']['trace'] else 'off'}"]
        e = c["evaluation"]
        if e:
            sc = e["scores"]
            out += [f"- **Evaluation:** run {e['run_id']} on {e['date'][:10]}, {_cell(e['suite'])}, judge "
                    f"{_cell(e['judge_model'])}, ×{e['repeats']} repeats{', with rewordings' if e['rewordings'] else ''}",
                    "- **Scores:** " + ", ".join(f"{k} {_cell(v)}" for k, v in sc.items() if v is not None)
                    + (f" (overall 95% range {e['overall_range'][0]}–{e['overall_range'][1]})" if e["overall_range"] else "")]
            prov = e.get("provenance") or {}
            if prov:
                out.append(f"- **Provenance:** commit {_cell((prov.get('git_commit') or '')[:10] or None)}"
                           f"{' (uncommitted changes)' if prov.get('git_dirty') else ''}, suite "
                           f"{_cell((prov.get('suite_sha256') or '')[:12])}, policy v{_cell(prov.get('policy_version'))}, "
                           f"started by {_cell(prov.get('started_by'))}")
        else:
            out.append("- **Evaluation:** no finished run yet")
        out.append("- **Known limitations:** " + ("; ".join(c["limitations"]) if c["limitations"] else "none found in the latest run"))
        o = c["oversight"]
        out.append(f"- **Human oversight:** {o['human_review_labels']} judge-review labels; judge spot-check accuracy "
                   f"{_cell(o['judge_spot_accuracy'])}%")
        if b["gate"]:
            failed = [r["text"] for r in b["gate"]["rules"] if r["ok"] is False]
            out.append(f"- **Release gate:** {b['gate']['verdict'].upper()}" + (": " + "; ".join(failed) if failed else ""))
    a = ov["audit"]
    out += ["", "## Audit trail", "",
            f"{a['entries']} entries; hash chain " + ("intact." if a["ok"] else f"BROKEN: {a['problem']}."),
            "", "## Data protection", "", f"- Personal data mode: {(p['data'] or {}).get('pii')}",
            f"- Retention: {ov['retention']['retention_days']} days; {len(ov['retention']['runs'])} run(s) due for deletion"]
    return "\n".join(out) + "\n"


# ---------- Personal-data scan of test data ----------

def scan():
    """Personal data in the suites and the store data files the judge is shown. All of it must be synthetic."""
    found = []
    for s in evaluator.list_suites():
        path = os.path.join(evaluator.SUITES_DIR, f"{s['id']}.json")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        found.append((path, text))
        for p in evaluator.load_suite(s["id"]).get("profiles", {}).values():
            for df in p.get("data_files", []):
                try:
                    with open(os.path.expanduser(df), encoding="utf-8-sig") as f:
                        found.append((os.path.expanduser(df), f.read()))
                except OSError:
                    pass
    out = []
    for path, text in found:
        values = sorted({(k, text[s:e]) for k, s, e, _ in governance.find_pii(text)})
        out.append({"file": path, "values": [{"kind": k, "value": v} for k, v in values]})
    return out


# ---------- CLI ----------

def _opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def main(args):
    if not args:
        sys.exit(__doc__)
    cmd = args[0]
    evaluator.load_runs()
    if cmd == "gate" and len(args) > 1:
        run = evaluator.get_run(args[1])
        if run is None:
            print(f"No such run: {args[1]}", file=sys.stderr)
            return 3
        result = gate(run)
        print(gate_text(result))
        verdicts = {b["verdict"] for b in result["bots"]}
        return 2 if "fail" in verdicts else 1 if "warn" in verdicts else 0
    if cmd == "signoff" and len(args) > 3:
        try:
            e = signoff(args[1], args[2], args[3], _opt(args, "--reviewer", ""), _opt(args, "--note", ""),
                        "--override" in args)
        except (KeyError, ValueError) as err:
            print(f"Not signed off: {err}", file=sys.stderr)
            return 3
        print(f"{e['label']}: {e['decision']}d by {e['reviewer']} (gate {e['gate_verdict']}"
              + (", override" if e["override"] else "") + ")")
        return 0
    if cmd == "report":
        text = report_markdown()
        if _opt(args, "-o"):
            with open(_opt(args, "-o"), "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Wrote {_opt(args, '-o')}")
        else:
            print(text)
        return 0
    if cmd == "anchor":
        a = governance.anchor(_opt(args, "--reason", "manual"))
        if a is None:
            print("Nothing anchored: the audit log is empty or broken (compliance.py audit)", file=sys.stderr)
            return 2
        print(f"Head #{a['seq']} {a['hash']} sent to: {', '.join(a['sent']) or 'nowhere (set AUDIT_ANCHOR_WEBHOOK or AUDIT_ANCHOR_S3)'}"
              + (f"; failed: {'; '.join(a['errors'])}" if a.get("errors") else ""))
        return 0 if a["sent"] and not a.get("errors") else 1
    if cmd == "audit":
        v = governance.verify_log()
        print(f"Audit log: {v['entries']} entries, " + ("chain intact" if v["ok"] else f"BROKEN: {v['problem']}")
              + (f", head #{v['entries']} {v['head']}" if v.get("head") else ""))
        if _opt(args, "--head"):
            seq, _, h = _opt(args, "--head").partition(":")
            check = governance.verify_against(int(seq), h)
            print("Matches the published head" if check["ok"] else f"DOES NOT MATCH the published head: {check['problem']}")
            v = {**v, "ok": v["ok"] and check["ok"]}
        for e in governance.read_log(int(_opt(args, "--limit", "20"))):
            print(f"  #{e['seq']} {e['at']} {e['actor']}: {e['action']} {e['target'] or ''}")
        return 0 if v["ok"] else 2
    if cmd == "purge":
        r = purge(dry_run="--dry-run" in args)
        if not r["retention_days"]:
            print("No retention_days in governance.json; nothing deleted")
        else:
            verb = "Would delete" if "--dry-run" in args else "Deleted"
            print(f"{verb} {len(r['runs'])} run(s) older than {r['retention_days']} days"
                  + (f": {', '.join(r['runs'])}" if r["runs"] else "") + f"; kept {r['kept']} (baseline or signed off)")
        return 0
    if cmd == "review-profile" and len(args) > 2:
        try:
            r = review_profile(args[1], args[2], _opt(args, "--reviewer", ""))
        except (KeyError, ValueError, FileNotFoundError) as err:
            print(f"Not recorded: {err}", file=sys.stderr)
            return 3
        print(f"Profile {args[2]} in {args[1]} reviewed by {r['by']} ({r['sha256'][:12]})")
        return 0
    if cmd == "scan":
        for f in scan():
            print(f"{f['file']}: " + (", ".join(f"{v['kind']} {v['value']}" for v in f["values"]) or "none"))
        print("All of these must be synthetic test data; real customer data must not be in suites or data files.")
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
