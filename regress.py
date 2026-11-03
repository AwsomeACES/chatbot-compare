"""Regression alerts from the command line: run the suite, compare each bot with its baseline run, and say what broke.

Usage:
  .venv/bin/python regress.py run [--bots a,b] [--cases c1,c2] [--suite store_support] [--repeats N] [--no-judge] [--no-compare]
                                  [--rewordings | --no-rewordings] [--no-second-judge] [--no-confirm]
      Runs the suite (default: every bot that has a baseline) and checks it. Each bot is first asked one real question
      from the suite (a "Hi" can pass without the bot's LLM, e.g. with its quota gone); if one is
      down or out of quota the run is skipped and reported (exit 3), rather than scored as a wall of failures.
      Rewordings are used when the bots' baseline runs used them, unless --rewordings / --no-rewordings says.
  .venv/bin/python regress.py resume <run_id>     Resumes an interrupted, cancelled or failed run in this process
      (asks only what's missing), then checks it. A run started or resumed here isn't tied to the dashboard server,
      so restarting the server doesn't cut it off; the dashboard shows its progress. `run --bots a,b --no-confirm`
      likewise starts any comparison outside the server.
  .venv/bin/python regress.py check <run_id>      Checks a saved run against the baselines.
  .venv/bin/python regress.py baseline <run_id>   Makes a finished run the baseline for its bots.

A critical break in a run asked once is re-tested before it is reported: the broken cases are asked CONFIRM_REPEATS
more times (default 3). A case that passes most of them is reported as a flaky warning, not critical, so one unlucky
LLM answer doesn't page anyone (--no-confirm turns this off). The second judge (llm.SECOND_JUDGE) grades the run
whenever one is configured (--no-second-judge turns it off).

Exit code: 0 no regressions, 1 warnings only, 2 critical (a safety, hallucination or bias case broke), 3 error.
The report ends with the release gate (compliance.py) for each bot; it doesn't change the exit code.
Set REGRESSION_WEBHOOK to a Slack-style incoming-webhook URL to also post the report there when something regressed
(add --always-notify to post every time).
"""

import json
import os
import re
import sys
import time
import urllib.request

import compliance
import evaluator
from adapters import BotError, open_conversation
from app import load_bots

POLL_S = 5
CONFIRM_REPEATS = int(os.environ.get("CONFIRM_REPEATS", "3"))


def notify(text):
    url = os.environ.get("REGRESSION_WEBHOOK")
    if not url:
        return
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except OSError as e:
        print(f"Could not post to REGRESSION_WEBHOOK: {e}", file=sys.stderr)


def wait(run):
    while run["status"] == "running":
        time.sleep(POLL_S)
        print(f"  {run['progress']['done']}/{run['progress']['total']}", end="\r", flush=True)
    print()


def confirm(run, rep, bots):
    """Re-ask each critical break CONFIRM_REPEATS times; one that passes in most of them becomes a "flaky" warning."""
    by_id = {b["id"]: b for b in bots}
    for entry in rep["bots"]:
        broken = [x["case_id"] for x in entry["broken"] if x.get("critical")]
        if not broken or entry["id"] not in by_id:
            continue
        print(f"Re-testing {len(broken)} critical case(s) for {entry['label']}: {', '.join(broken)}")
        again = evaluator.start_run([by_id[entry["id"]]], run["suite"], bool(run.get("judge")), repeats=CONFIRM_REPEATS,
                                    comparative=False, rewordings=run.get("rewordings"), case_ids=broken,
                                    second_judge=bool(run.get("second_judge_model")), timing=False)
        wait(again)
        shares, _ = evaluator._case_outcomes(again, entry["id"])
        for a in entry["alerts"]:
            case = a["text"].split(" ", 1)[0]
            if a["level"] == "critical" and case in shares and shares[case] >= 0.5:
                a["level"] = "warning"
                a["text"] += f" (flaky: passed {round(100 * shares[case])}% of {CONFIRM_REPEATS} re-tests, run {again['id']})"
            elif a["level"] == "critical" and case in shares:
                a["text"] += f" (confirmed: re-test run {again['id']})"
    rep["critical"] = sum(a["level"] == "critical" for e in rep["bots"] for a in e["alerts"])
    rep["warnings"] = sum(a["level"] == "warning" for e in rep["bots"] for a in e["alerts"])
    return rep


def report(run, always_notify=False, bots=None):
    rep = evaluator.regressions(run)
    if bots and rep["critical"] and run.get("repeats", 1) < CONFIRM_REPEATS:
        rep = confirm(run, rep, bots)
    text = evaluator.regression_text(run, rep)
    try:
        text += "\n" + compliance.gate_text(compliance.gate(run))
    except Exception as e:  # the regression report must still go out
        print(f"Could not evaluate the release gate: {type(e).__name__}: {e}", file=sys.stderr)
    print(text)
    if rep["critical"] or rep["warnings"] or always_notify:
        notify(text)
    return 2 if rep["critical"] else 1 if rep["warnings"] else 0


def option(args, name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def preflight(bots, suite=None):
    """Bots that can't answer right now: [(label, error)]. With a suite, each bot is asked a real question from it
    (filled in with its own facts) rather than "Hi": some bots answer a greeting without calling their LLM, so a
    "Hi" passes even when the LLM's quota is gone."""
    down = []
    for b in bots:
        conv = None
        try:
            question = (evaluator.timing_prompts(suite, b, 1) or ["Hi"])[0] if suite else "Hi"
        except ValueError:  # no matching profile: the run itself will say so
            question = "Hi"
        try:
            conv = open_conversation(b)
            conv.send(question)
        except BotError as e:
            down.append((b["label"], str(e)[:200]))
        finally:
            if conv is not None:
                try:
                    conv.close()
                except Exception:
                    pass
    return down


def judge_preflight(second=False):
    """Judges that can't grade right now: [(model, error)]. A retired model (HTTP 404 / 410) or a missing key would
    otherwise turn every verdict of the night into a "judge error"."""
    down = []
    for endpoint in [evaluator.llm.JUDGE] + ([evaluator.llm.SECOND_JUDGE] if second else []):
        try:
            endpoint.structured("Answer in JSON.", "Is 7 a prime number?",
                                {"type": "object", "properties": {"prime": {"type": "boolean"}}, "required": ["prime"]},
                                "preflight")
        except BotError as e:
            down.append((endpoint.model, str(e)[:200]))
    return down


RETIRED = re.compile(r"HTTP (404|410)\b")


def judge_alert(judges_down):
    """The nightly alert for judges that failed the pre-flight. A retired or unserved model (HTTP 404 / 410) won't come
    back by itself, unlike a quota or an outage, so it gets its own headline saying what to change (AIRM-124, -165)."""
    retired = [(m, e) for m, e in judges_down if RETIRED.search(e)]
    other = [(m, e) for m, e in judges_down if not RETIRED.search(e)]
    parts = []
    if retired:
        parts.append("Chatbot Compare nightly run skipped, judge model retired or not served to this account. "
                     "It won't come back: set JUDGE_MODEL (or SECOND_JUDGE_MODEL) in .env to a model that answers, "
                     "or change the default in llm.py:\n" + "\n".join(f"- {m}: {e}" for m, e in retired))
    if other:
        parts.append("Chatbot Compare nightly run skipped, judge(s) not answering:\n"
                     + "\n".join(f"- {m}: {e}" for m, e in other))
    return "\n\n".join(parts)


def baseline_used_rewordings(ids):
    baselines = evaluator.load_baselines()
    return any((evaluator.get_run(baselines[i]) or {}).get("rewordings") for i in ids if i in baselines)


def cmd_run(args):
    enabled = {b["id"]: b for b in load_bots()}
    ids = option(args, "--bots")
    if ids:
        ids = ids.split(",")
    else:  # every bot with a baseline, except ones since removed or disabled in bots.json
        ids = sorted(evaluator.load_baselines())
        gone = [i for i in ids if i not in enabled]
        if gone:
            print(f"Skipping baselined bot(s) not enabled in bots.json: {', '.join(gone)}", file=sys.stderr)
        ids = [i for i in ids if i in enabled]
    missing = [i for i in ids if i not in enabled]
    if not ids or missing:
        print(f"Unknown or disabled bot(s): {', '.join(missing)}" if missing
              else "No bots given and no baselines set. Use --bots, or set a baseline first.", file=sys.stderr)
        return 3
    bots = [enabled[i] for i in ids]
    down = preflight(bots, evaluator.load_suite(option(args, "--suite", "store_support")))
    if down:
        text = "Chatbot Compare nightly run skipped, bot(s) not answering:\n" + "\n".join(f"- {l}: {e}" for l, e in down)
        print(text)
        notify(text)
        return 3
    second_judge = bool(evaluator.llm.SECOND_JUDGE) and "--no-second-judge" not in args
    judges_down = judge_preflight(second_judge) if "--no-judge" not in args else []
    if judges_down:
        text = judge_alert(judges_down)
        print(text)
        notify(text)
        return 3
    rewordings = ("--rewordings" in args or baseline_used_rewordings(ids)) and "--no-rewordings" not in args
    run = evaluator.start_run(bots, option(args, "--suite", "store_support"),
                              "--no-judge" not in args, repeats=int(option(args, "--repeats", "1")),
                              comparative="--no-compare" not in args, rewordings=rewordings,
                              second_judge=second_judge,
                              case_ids=option(args, "--cases", "").split(",") if option(args, "--cases") else None)
    print(f"Run {run['id']}: {', '.join(ids)}" + (" (with rewordings)" if run.get("rewordings") else ""))
    wait(run)
    if run["status"] != "done":
        text = f"Chatbot Compare run {run['id']} {run['status']}: {run.get('failure', '')}"
        print(text)
        notify(text)
        return 3
    return report(run, "--always-notify" in args, None if "--no-confirm" in args else bots)


def cmd_resume(run):
    enabled = {b["id"]: b for b in load_bots()}
    missing = [b["id"] for b in run["bots"] if b["id"] not in enabled]
    if missing:
        print(f"Unknown or disabled bot(s): {', '.join(missing)}", file=sys.stderr)
        return 3
    bots = [enabled[b["id"]] for b in run["bots"]]
    try:
        evaluator.resume_run(run["id"], bots)
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 3
    print(f"Resuming run {run['id']}: {run['progress']['done']}/{run['progress']['total']} done")
    wait(run)
    if run["status"] != "done":
        print(f"Run {run['id']} {run['status']}: {run.get('failure', '')}")
        return 3
    return report(run, bots=bots)  # critical breaks are re-tested, as after "run"


def main(args):
    if len(args) < 1 or args[0] not in ("run", "check", "baseline", "resume") or (args[0] != "run" and len(args) < 2):
        print(__doc__)
        return 3
    evaluator.load_runs()
    if args[0] == "run":
        return cmd_run(args[1:])
    run = evaluator.get_run(args[1])
    if run is None:
        print(f"No such run: {args[1]}", file=sys.stderr)
        return 3
    if args[0] == "check":
        return report(run, "--always-notify" in args)
    if args[0] == "resume":
        return cmd_resume(run)
    try:
        print(f"Baseline for: {', '.join(evaluator.set_baseline(args[1]))}")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
