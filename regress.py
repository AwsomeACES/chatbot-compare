"""Regression alerts from the command line: run the suite, compare each bot with its baseline run, and say what broke.

Usage:
  .venv/bin/python regress.py run [--bots a,b] [--cases c1,c2] [--suite store_support] [--repeats N] [--no-judge] [--no-compare]
                                  [--rewordings | --no-rewordings] [--second-judge]
      Runs the suite (default: every bot that has a baseline) and checks it. Each bot is sent "Hi" first; if one is
      down or out of quota the run is skipped and reported (exit 3), rather than scored as a wall of failures.
      Rewordings are used when the bots' baseline runs used them, unless --rewordings / --no-rewordings says.
  .venv/bin/python regress.py check <run_id>      Checks a saved run against the baselines.
  .venv/bin/python regress.py baseline <run_id>   Makes a finished run the baseline for its bots.

Exit code: 0 no regressions, 1 warnings only, 2 critical (a safety, hallucination or bias case broke), 3 error.
The report ends with the release gate (compliance.py) for each bot; it doesn't change the exit code.
Set REGRESSION_WEBHOOK to a Slack-style incoming-webhook URL to also post the report there when something regressed
(add --always-notify to post every time).
"""

import json
import os
import sys
import time
import urllib.request

import compliance
import evaluator
from adapters import BotError, open_conversation
from app import load_bots

POLL_S = 5


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


def report(run, always_notify=False):
    rep = evaluator.regressions(run)
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


def preflight(bots):
    """Bots that can't answer a "Hi" right now: [(label, error)]."""
    down = []
    for b in bots:
        conv = None
        try:
            conv = open_conversation(b)
            conv.send("Hi")
        except BotError as e:
            down.append((b["label"], str(e)[:200]))
        finally:
            if conv is not None:
                try:
                    conv.close()
                except Exception:
                    pass
    return down


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
    down = preflight(bots)
    if down:
        text = "Chatbot Compare nightly run skipped, bot(s) not answering:\n" + "\n".join(f"- {l}: {e}" for l, e in down)
        print(text)
        notify(text)
        return 3
    rewordings = ("--rewordings" in args or baseline_used_rewordings(ids)) and "--no-rewordings" not in args
    run = evaluator.start_run(bots, option(args, "--suite", "store_support"),
                              "--no-judge" not in args, repeats=int(option(args, "--repeats", "1")),
                              comparative="--no-compare" not in args, rewordings=rewordings,
                              second_judge="--second-judge" in args,
                              case_ids=option(args, "--cases", "").split(",") if option(args, "--cases") else None)
    print(f"Run {run['id']}: {', '.join(ids)}" + (" (with rewordings)" if run.get("rewordings") else ""))
    while run["status"] == "running":
        time.sleep(POLL_S)
        print(f"  {run['progress']['done']}/{run['progress']['total']}", end="\r", flush=True)
    print()
    if run["status"] != "done":
        text = f"Chatbot Compare run {run['id']} {run['status']}: {run.get('failure', '')}"
        print(text)
        notify(text)
        return 3
    return report(run, "--always-notify" in args)


def main(args):
    if len(args) < 1 or args[0] not in ("run", "check", "baseline") or (args[0] != "run" and len(args) < 2):
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
    try:
        print(f"Baseline for: {', '.join(evaluator.set_baseline(args[1]))}")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
