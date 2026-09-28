"""Re-grade a saved run with the AI judge and recompute its scores, without asking the bots again.

Useful when the judge failed or was off during the run, or after changing the scoring rules.
Usage: .venv/bin/python rejudge.py <run_id> [--all | --checks-only]
  --all          also re-grade answers that already have a verdict
  --checks-only  only re-apply the exact checks and recompute scores (no judge calls)
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import anthropic

import evaluator
from adapters import BotError

ROOT = os.path.dirname(__file__)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run_id, regrade_all = sys.argv[1], "--all" in sys.argv
    path = os.path.join(evaluator.RUNS_DIR, f"{run_id}.json")
    with open(path) as f:
        run = json.load(f)
    suite = evaluator.load_suite(run["suite"])
    with open(os.path.join(ROOT, "bots.json")) as f:
        bots = {b["id"]: b for b in json.load(f)["bots"]}

    for r in run["results"]:  # apply the current "blocked" rule and checks to old results
        if r["error"]:
            r["blocked"] = bool(evaluator.BLOCKED_ERRORS.search(r["error"]))
        evaluator.recheck(suite, bots[r["bot_id"]], r)

    if "--checks-only" in sys.argv:
        todo = []
    else:
        todo = [r for r in run["results"]
                if r["turns"] and not r["error"] and not r.get("unsupported") and (regrade_all or not r.get("judge"))]
    print(f"Grading {len(todo)} conversations with {evaluator.JUDGE_MODEL}...")

    def grade(r):
        profile = evaluator.profile_for(suite, bots[r["bot_id"]])
        try:
            r["judge"] = evaluator.judge(profile.get("context"), r.get("rubric"), r["turns"])
            r.pop("judge_error", None)
        except (anthropic.APIError, BotError) as e:
            r["judge_error"] = str(e)
        return r

    with ThreadPoolExecutor(evaluator.CONCURRENCY) as pool:
        for i, r in enumerate(pool.map(grade, todo), 1):
            mark = "pass" if (r.get("judge") or {}).get("passed") else "FAIL" if r.get("judge") else "judge error"
            print(f"  {i:3}/{len(todo)}  {r['bot_id']:18} {r['case_id']:20} {mark}")

    run["judge"] = True
    run["judge_model"] = evaluator.JUDGE_MODEL
    run["summary"] = evaluator.summarise(run, suite)
    with open(path, "w") as f:
        json.dump(run, f, indent=1)
    for b in sorted(run["summary"]["bots"], key=lambda b: b["rank"]):
        print(f"#{b['rank']} {b['label']}: overall {b['overall']}, pass rate {b['pass_rate']}%, "
              f"judge quality {b['quality']}, median {b['latency_p50']} ms, scored cases {b['cases']}, blocked {len(b['blocked'])}")


if __name__ == "__main__":
    main()
