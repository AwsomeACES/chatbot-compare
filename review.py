"""Human spot-checks of the AI judge: a review queue and how far the judge can be trusted.

The queue holds judged conversations from finished runs, in this order (with labeled ones listed first when asked
for, most recent first):
  judges  the main and second judge disagree (pass/fail or invented facts)
  evidence  none of the main judge's quotes is in the bot's replies (an "unverified" verdict)
  checks  the exact checks and the main judge disagree on pass/fail
  spot    a fixed random sample of the rest (SPOT_SAMPLE), where nothing disagrees
A reviewer reads the conversation and records the right answer: should it pass, and did the bot invent a fact. Each
label keeps the verdicts it was compared with, so the stats survive a later re-grade of the run.

Stats: how often each grader (main judge, second judge, exact checks) matched the human, with a 95% Wilson interval.
On the disagreements this shows who to believe when graders conflict; on the random spot-checks it estimates the
judge's accuracy on all conversations, since that sample isn't picked for being hard.
"""

import hashlib
import json
import math
import os
import threading
import time

import evaluator
import governance

LABELS_FILE = os.path.join(evaluator.RUNS_DIR, "judge_labels.json")
SPOT_SAMPLE = float(os.environ.get("REVIEW_SPOT_SAMPLE", "0.1"))
TARGET = 50  # labels after which the agreement figures are worth quoting
KINDS = ("judges", "evidence", "checks", "spot")
_lock = threading.Lock()


def item_id(run_id, r):
    case, repeat, wording = evaluator.sample_key(r)
    return f"{run_id}|{r['bot_id']}|{case}|{repeat}|{wording}"


def load_labels():
    try:
        with open(LABELS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_labels(data):
    tmp = LABELS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, LABELS_FILE)


def _spot(iid):
    return int(hashlib.sha256(iid.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < SPOT_SAMPLE


def kind_of(r, iid):
    """Why a result is in the queue, or None. Needs a main-judge verdict and a conversation."""
    j = r.get("judge")
    if not j or r.get("error") or not r.get("turns"):
        return None
    j2 = r.get("judge2")
    if j2 and (j2["passed"] != j["passed"] or j2["hallucinated"] != j["hallucinated"]):
        return "judges"
    if j.get("unverified"):
        return "evidence"
    if r.get("checks") is not None and r["checks"] != j["passed"]:
        return "checks"
    return "spot" if _spot(iid) else None


def verdicts(r):
    """The graders' answers on one result, as saved with a label."""
    out = {"judge": {"passed": r["judge"]["passed"], "hallucinated": r["judge"]["hallucinated"]}}
    if r.get("judge2"):
        out["judge2"] = {"passed": r["judge2"]["passed"], "hallucinated": r["judge2"]["hallucinated"]}
    if r.get("checks") is not None:
        out["checks"] = {"passed": r["checks"]}
    return out


def _context(run, bot_id):
    """The store facts the judge was shown for this bot (the profile's summary, without the full data files)."""
    cfg = next((b for b in run.get("bot_configs", []) if b["id"] == bot_id), {})
    try:
        profile = evaluator.load_suite(run["suite"]).get("profiles", {}).get(cfg.get("profile"), {})
    except (OSError, ValueError):
        return ""
    return profile.get("context", "")


def queue(run_id=None, include_labeled=False, limit=100):
    """Items to review (unlabeled first, by kind, newest run first) and how many of each kind are waiting."""
    labels = load_labels()
    evaluator.list_runs()  # pick up runs saved by other processes
    runs = [evaluator.get_run(run_id)] if run_id else [evaluator.get_run(r["id"]) for r in evaluator.list_runs()]
    items, waiting = [], dict.fromkeys(KINDS, 0)
    for run in runs:
        if not run or run["status"] != "done" or not run.get("judge"):
            continue
        labels_of = {b["id"]: b["label"] for b in run["bots"]}
        contexts = {}
        for r in run["results"]:
            iid = item_id(run["id"], r)
            kind = kind_of(r, iid)
            if kind is None:
                continue
            labeled = iid in labels
            waiting[kind] += not labeled
            if labeled and not include_labeled:
                continue
            if r["bot_id"] not in contexts:
                contexts[r["bot_id"]] = _context(run, r["bot_id"])
            items.append({"id": iid, "kind": kind, "run_id": run["id"], "run_created": run["created_at"],
                          "bot_id": r["bot_id"], "bot_label": labels_of.get(r["bot_id"], r["bot_id"]),
                          "case_id": r["case_id"], "category": r["category"], "repeat": r.get("repeat", 0),
                          "wording": r.get("wording", 0), "rubric": r.get("rubric"), "turns": r["turns"],
                          "context": contexts[r["bot_id"]], "judge": r["judge"], "judge2": r.get("judge2"),
                          "checks": r.get("checks"), "check_failures": r.get("check_failures", []),
                          "label": labels.get(iid)})
    items.sort(key=lambda x: x["run_created"], reverse=True)  # newest run first within each group (stable sort)
    items.sort(key=lambda x: (x["label"] is not None, KINDS.index(x["kind"])))
    if include_labeled:  # the reviewer wants to see their labels: most recent first, then the queue
        items.sort(key=lambda x: (x["label"] or {}).get("labeled_at", ""), reverse=True)
    return {"items": items[:limit], "total": len(items), "waiting": waiting, "stats": stats(labels)}


def _find(iid):
    run_id = iid.split("|", 1)[0]
    run = evaluator.get_run(run_id)
    if run is None:
        raise KeyError(iid)
    for r in run["results"]:
        if item_id(run_id, r) == iid:
            return run, r
    raise KeyError(iid)


def label(iid, passed, hallucinated, note=""):
    """Record the human answer for one queued conversation."""
    run, r = _find(iid)
    kind = kind_of(r, iid)
    if kind is None:
        raise ValueError("This conversation has no judge verdict to check")
    entry = {"passed": bool(passed), "hallucinated": bool(hallucinated), "note": note.strip()[:1000],
             "kind": kind, "category": r["category"], "bot_id": r["bot_id"], "case_id": r["case_id"],
             "judge_model": run.get("judge_model"), "second_judge_model": run.get("second_judge_model"),
             "judge_prompt_version": run.get("judge_prompt_version"),
             "verdicts": verdicts(r), "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _lock:
        data = load_labels()
        data[iid] = entry
        _save_labels(data)
    governance.record("review.label", iid, passed=entry["passed"], hallucinated=entry["hallucinated"],
                      judge=entry["verdicts"]["judge"], note=entry["note"])
    return entry


def unlabel(iid):
    with _lock:
        data = load_labels()
        if data.pop(iid, None) is not None:
            _save_labels(data)
            governance.record("review.unlabel", iid)


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n, as percentages."""
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)]


def _agreement(labels, grader, field):
    pairs = [(v["verdicts"][grader][field], v[field]) for v in labels
             if grader in v["verdicts"] and field in v["verdicts"][grader]]
    if not pairs:
        return None
    k = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "agree": k, "pct": round(100 * k / len(pairs), 1), "range": wilson(k, len(pairs)),
            # the grader said pass / invented, the human said the opposite
            "false_yes": sum(a and not b for a, b in pairs), "false_no": sum(b and not a for a, b in pairs)}


def stats(labels=None):
    labels = load_labels() if labels is None else labels
    rows = list(labels.values())
    groups = {"all": rows, "disagreements": [v for v in rows if v["kind"] != "spot"],
              "spot": [v for v in rows if v["kind"] == "spot"]}
    out = {"labels": len(rows), "target": TARGET, "by_kind": {k: sum(v["kind"] == k for v in rows) for k in KINDS}}
    for name, vs in groups.items():
        out[name] = {"n": len(vs), **{
            f"{g}_{f}": _agreement(vs, g, f)
            for g, fields in (("judge", ("passed", "hallucinated")), ("judge2", ("passed", "hallucinated")),
                              ("checks", ("passed",)))
            for f in fields}}
    # On judge-vs-judge disagreements about pass/fail exactly one of them matches the human.
    split = [v for v in rows if v["kind"] == "judges" and "judge2" in v["verdicts"]
             and v["verdicts"]["judge"]["passed"] != v["verdicts"]["judge2"]["passed"]]
    out["judges_split"] = {"n": len(split),
                           "main_right": sum(v["verdicts"]["judge"]["passed"] == v["passed"] for v in split),
                           "second_right": sum(v["verdicts"]["judge2"]["passed"] == v["passed"] for v in split)}
    return out
