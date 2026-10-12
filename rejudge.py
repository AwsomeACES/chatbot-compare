"""Re-grade a saved run with the AI judge and recompute its scores, without asking the bots again.

Useful when the judge failed or was off during the run, or after changing the scoring rules.
Usage: .venv/bin/python rejudge.py <run_id> [--all | --checks-only] [--compare] [--category c1,c2]
  --all          also re-grade answers that already have a verdict
  --category     only re-grade these skills (e.g. bias after a change to how fairness is judged)
  --checks-only  only re-apply the exact checks and recompute scores (no judge calls)
  --compare      also (re)run the comparative judge, which ranks the bots' answers to each case side by side
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import evaluator
import governance
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
    for b in run.get("bot_configs", []):  # a bot since removed from bots.json: use the run's own snapshot
        bots.setdefault(b["id"], b)
    unknown = sorted({r["bot_id"] for r in run["results"]} - set(bots))
    if unknown:
        print(f"Skipping results of bots no longer in bots.json: {', '.join(unknown)}")
    results = [r for r in run["results"] if r["bot_id"] in bots]
    only = sys.argv[sys.argv.index("--category") + 1].split(",") if "--category" in sys.argv else None

    for r in results:  # apply the current "blocked" rule and checks to old results
        if r["error"]:
            r["blocked"] = bool(evaluator.BLOCKED_ERRORS.search(r["error"]))
        evaluator.recheck(suite, bots[r["bot_id"]], r)

    if "--checks-only" in sys.argv:
        todo = []
    else:
        todo = [r for r in results
                if r["turns"] and not r["error"] and not r.get("unsupported") and (regrade_all or not r.get("judge"))
                and (only is None or r["category"] in only)]
    print(f"Grading {len(todo)} conversations with {evaluator.JUDGE_MODEL}...")

    def grade(r):
        profile = evaluator.profile_for(suite, bots[r["bot_id"]])
        old = r.get("judge")
        try:
            r["judge"] = evaluator.judge(profile.get("context"), r.get("rubric"), r["turns"])
            r.pop("judge_error", None)
            evaluator.keep_spent(r, [evaluator.verdict_spent(old)], "judge", "replaced")  # still paid for
        except BotError as e:
            r["judge_error"] = str(e)
            evaluator.keep_spent(r, evaluator.llm.spent_from(e), "judge", "rejected")
        return r

    with ThreadPoolExecutor(evaluator.CONCURRENCY) as pool:
        for i, r in enumerate(pool.map(grade, todo), 1):
            mark = "pass" if (r.get("judge") or {}).get("passed") else "FAIL" if r.get("judge") else "judge error"
            print(f"  {i:3}/{len(todo)}  {r['bot_id']:18} {r['case_id']:20} {mark}")

    if todo:
        run["judge"] = True
        run["judge_model"] = evaluator.JUDGE_MODEL
        run["judge_prompt_version"] = evaluator.JUDGE_PROMPT_VERSION
    if "--compare" in sys.argv:
        run_bots = [bots[b["id"]] for b in run["bots"] if b["id"] in bots]
        print(f"Comparing answers side by side with {evaluator.JUDGE_MODEL}...")
        evaluator.retire_judging(run, comparisons=run.get("comparisons") or [])
        run["comparisons"] = evaluator.run_comparisons({**run, "results": results}, suite, run_bots)
        run["comparative"] = True
        failed = sum(1 for c in run["comparisons"] if c.get("error"))
        print(f"  {len(run['comparisons'])} cases compared" + (f", {failed} failed" if failed else ""))
    run["summary"] = evaluator.summarise(run, suite)
    ju = run["summary"].get("judge_usage")
    if ju:
        cost = "no price" if ju["cost"] is None else f"${ju['cost']:,.4f}"
        print(f"AI judge, whole run: {ju['total_tokens']:,} tokens in {ju['usage_calls']} calls, estimated {cost}"
              + (f" ({ju['unpriced_calls']} calls unpriced)" if ju["cost"] is not None and ju["unpriced_calls"] else ""))
    evaluator.save_run_file(run, path)  # atomic; the server picks up the change on the next view
    governance.record("run.rejudge", run_id, results_sha256=governance.seal(run), regraded=len(todo),
                      judge_model=run.get("judge_model"), compare="--compare" in sys.argv,
                      checks_only="--checks-only" in sys.argv)
    for b in sorted(run["summary"]["bots"], key=lambda b: b["rank"] or 99):
        print(f"#{b['rank'] or '-'} {b['label']}: overall {b['overall']}, accuracy {b['accuracy']}%, "
              f"no hallucination {b['hallucination']}%, fairness {b['bias']}%, pass rate {b['pass_rate']}%, "
              f"judge quality {b['quality']}, median {b['latency_p50']} ms, scored cases {b['cases']}, blocked {len(b['blocked'])}")


if __name__ == "__main__":
    main()
