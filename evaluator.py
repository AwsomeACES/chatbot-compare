"""Runs a test suite against several bots, scores every reply, and summarises who won.

Scoring for each (bot, test case):
  checks  deterministic rules on the final reply (contains_any, contains_all, not_contains, regex)
  judge   Claude on Bedrock grades the whole conversation against the case's rubric, without
          knowing which bot wrote it (correctness, helpfulness, tone: 1-5, plus pass/fail)
  latency time per bot turn
"""

import json
import os
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import anthropic
from pydantic import BaseModel, Field

from adapters import BotError, bedrock_client, open_conversation

ROOT = os.path.dirname(__file__)
RUNS_DIR = os.path.join(ROOT, "runs")
SUITES_DIR = os.path.join(ROOT, "suites")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "anthropic.claude-opus-5")
CONCURRENCY = int(os.environ.get("EVAL_CONCURRENCY", "4"))
BLOCKED_ERRORS = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|quota|rate limit|no credits|HTTP 402", re.I)

# Overall score weights (0-100 scale). Speed is relative to the fastest bot in the run.
WEIGHTS_WITH_JUDGE = {"accuracy": 0.45, "quality": 0.40, "speed": 0.15}
WEIGHTS_NO_JUDGE = {"accuracy": 0.80, "speed": 0.20}


# ---------- Suites ----------

def list_suites():
    suites = []
    for name in sorted(os.listdir(SUITES_DIR)):
        if name.endswith(".json"):
            s = load_suite(name[:-5])
            suites.append({"id": name[:-5], "name": s["name"], "description": s.get("description", ""),
                           "cases": len(s["cases"]),
                           "profiles": {k: v.get("name", k) for k, v in s.get("profiles", {}).items()},
                           "categories": sorted({c.get("category", "general") for c in s["cases"]})})
    return suites


def load_suite(suite_id):
    if not re.fullmatch(r"[\w-]+", suite_id):
        raise ValueError("Bad suite id")
    with open(os.path.join(SUITES_DIR, f"{suite_id}.json")) as f:
        return json.load(f)


# ---------- Templates: each bot gets the same case filled in with its own store facts ----------

def render(value, variables):
    """Fill {name} placeholders from a profile's vars. A string that is exactly "{name}" becomes the
    var itself (so a list var can feed contains_any); lists are flattened."""
    if isinstance(value, str):
        m = re.fullmatch(r"\{(\w+)\}", value)
        if m and m.group(1) in variables:
            return variables[m.group(1)]
        def sub(m):
            v = variables.get(m.group(1))
            if v is None:
                return m.group(0)
            return v[0] if isinstance(v, list) else str(v)
        return re.sub(r"\{(\w+)\}", sub, value)
    if isinstance(value, list):
        out = []
        for v in value:
            r = render(v, variables)
            out.extend(r if isinstance(r, list) else [r])
        return out
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    return value


def profile_for(suite, bot):
    profiles = suite.get("profiles")
    if not profiles:
        return {"context": suite.get("context", ""), "vars": {}, "capabilities": None}
    if bot.get("profile") not in profiles:
        raise ValueError(f"Bot '{bot['id']}' needs a \"profile\" matching one of: {', '.join(profiles)}")
    profile = dict(profiles[bot["profile"]])
    # The judge sees the bot's full data files, so details the bot really has aren't mistaken for inventions.
    for path in profile.get("data_files", []):
        with open(os.path.expanduser(path), encoding="utf-8-sig") as f:
            profile["context"] = (profile.get("context", "") + f"\n\nFULL STORE DATA ({os.path.basename(path)}), "
                                  "everything the bot legitimately knows:\n" + f.read())
    return profile


# ---------- Checks ----------

def _norm(s):
    # "Rs 29,990" and "29990" should match each other.
    s = re.sub(r"(?<=\d),(?=\d)", "", s.lower())
    return re.sub(r"\b(month|year|day)s\b", r"\1", s.replace("-", " "))


def run_checks(expect, reply):
    """Returns (passed, [failure messages]) or (None, []) when the case has no checks."""
    if not expect:
        return None, []
    text, failures = _norm(reply), []
    if isinstance(expect.get("contains_any"), str):
        expect = {**expect, "contains_any": [expect["contains_any"]]}
    if "contains_any" in expect and not any(_norm(x) in text for x in expect["contains_any"]):
        failures.append(f"should mention one of: {', '.join(expect['contains_any'])}")
    for x in expect.get("contains_all", []):
        if _norm(x) not in text:
            failures.append(f"should mention: {x}")
    for x in expect.get("not_contains", []):
        if _norm(x) in text:
            failures.append(f"should not mention: {x}")
    if "regex" in expect and not re.search(expect["regex"], reply, re.I):
        failures.append(f"should match /{expect['regex']}/")
    return not failures, failures


# ---------- LLM judge ----------

class Verdict(BaseModel):
    correctness: int = Field(description="1-5: are the facts right and consistent with the expected behaviour?")
    helpfulness: int = Field(description="1-5: does it fully resolve what the customer asked?")
    tone: int = Field(description="1-5: clear, concise, polite, well formatted for a chat window")
    passed: bool = Field(description="true if a careful reviewer would accept this conversation as a good answer")
    reason: str = Field(description="One or two sentences explaining the scores, naming any specific error")


JUDGE_SYSTEM = """You grade chatbot conversations for a comparison study. You are shown one conversation and
the behaviour the chatbot was expected to show. Grade only what the chatbot said. Be strict about facts:
a wrong price, a made-up policy, or leaking data it should protect means correctness 1 or 2 and passed=false.
Do not reward length; a short correct answer beats a long one. Scores are integers from 1 to 5."""

JUDGE_TOOL = {
    "name": "submit_verdict",
    "description": "Record the grade for this conversation.",
    "input_schema": {**Verdict.model_json_schema(), "additionalProperties": False},
}


def judge(context, rubric, turns):
    transcript = "\n\n".join(f"CUSTOMER: {t['user']}\nCHATBOT: {t['bot']}" for t in turns)
    prompt = (f"<chatbot_context>\n{context or 'A customer support chatbot.'}\n</chatbot_context>\n\n"
              f"<conversation>\n{transcript}\n</conversation>\n\n"
              f"<expected_behaviour>\n{rubric or 'A correct, helpful, polite answer.'}\n</expected_behaviour>")
    # Bedrock rejects output_config.format, so the verdict comes back as a tool call instead.
    response = bedrock_client().messages.create(
        model=JUDGE_MODEL,
        max_tokens=16000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt + "\n\nRecord your grade by calling submit_verdict."}],
        tools=[JUDGE_TOOL],
        output_config={"effort": "medium"},
    )
    call = next((b for b in response.content if b.type == "tool_use" and b.name == "submit_verdict"), None)
    if response.stop_reason == "refusal" or call is None:
        raise BotError("Judge did not return a verdict")
    try:
        v = Verdict.model_validate(call.input)
    except ValueError as e:
        raise BotError(f"Judge returned an invalid verdict: {e}") from e
    clamp = lambda n: max(1, min(5, n))
    return {"correctness": clamp(v.correctness), "helpfulness": clamp(v.helpfulness), "tone": clamp(v.tone),
            "passed": v.passed, "reason": v.reason}


def recheck(suite, bot, result):
    """Re-apply the (current) checks to a saved result's final reply."""
    if result.get("unsupported") or result["error"] or not result["turns"]:
        return
    case = next(c for c in suite["cases"] if c["id"] == result["case_id"])
    expect = render(case.get("expect"), profile_for(suite, bot)["vars"])
    result["checks"], result["check_failures"] = run_checks(expect, result["turns"][-1]["bot"])


# ---------- Runs ----------

_runs: dict[str, dict] = {}
_lock = threading.Lock()


def _save(run):
    with _lock:
        data = json.dumps(run, indent=1)
    tmp = os.path.join(RUNS_DIR, f".{run['id']}.tmp")
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, os.path.join(RUNS_DIR, f"{run['id']}.json"))


def load_runs():
    for name in os.listdir(RUNS_DIR):
        if name.endswith(".json"):
            with open(os.path.join(RUNS_DIR, name)) as f:
                run = json.load(f)
            if run["status"] == "running":  # server stopped mid-run
                run["status"] = "interrupted"
            _runs[run["id"]] = run


def list_runs():
    return sorted(({k: r[k] for k in ("id", "created_at", "suite_name", "bots", "status", "progress", "judge")}
                   | {"winner": (r.get("summary") or {}).get("winner")} for r in _runs.values()),
                  key=lambda r: r["created_at"], reverse=True)


def get_run(run_id):
    return _runs.get(run_id)


def delete_run(run_id):
    if _runs.pop(run_id, None):
        os.remove(os.path.join(RUNS_DIR, f"{run_id}.json"))


def start_run(bots, suite_id, use_judge):
    suite = load_suite(suite_id)
    for b in bots:
        profile_for(suite, b)  # fail fast if a bot has no matching profile
    run = {
        "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "suite": suite_id, "suite_name": suite["name"],
        "bots": [{"id": b["id"], "label": b["label"]} for b in bots],
        "judge": use_judge, "judge_model": JUDGE_MODEL if use_judge else None,
        "status": "running", "progress": {"done": 0, "total": len(bots) * len(suite["cases"])},
        "results": [], "summary": None,
    }
    _runs[run["id"]] = run
    _save(run)
    threading.Thread(target=_execute, args=(run, bots, suite), daemon=True).start()
    return run


def _run_case(suite, case, bot, use_judge):
    profile = profile_for(suite, bot)
    case = {**case, **render({k: case[k] for k in ("turns", "expect", "rubric") if k in case}, profile["vars"])}
    result = {"case_id": case["id"], "bot_id": bot["id"], "category": case.get("category", "general"),
              "rubric": case.get("rubric"), "turns": [], "error": None, "unsupported": False,
              "checks": None, "check_failures": [], "judge": None}
    caps = profile.get("capabilities")
    if caps is not None and not set(case.get("requires", [])) <= set(caps):
        result["unsupported"] = True
        return result
    conv = open_conversation(bot)
    try:
        for msg in case["turns"]:
            reply = conv.send(msg)
            result["turns"].append({"user": msg, "bot": reply.text, "latency_ms": reply.latency_ms})
    except BotError as e:
        result["error"] = str(e)
        # Quota / rate-limit / billing errors are the account's fault, not the bot's: shown, but not scored.
        result["blocked"] = bool(BLOCKED_ERRORS.search(str(e)))
    finally:
        conv.close()

    if result["error"]:
        result["checks"] = False if case.get("expect") else None
        return result
    result["checks"], result["check_failures"] = run_checks(case.get("expect"), result["turns"][-1]["bot"])
    if use_judge:
        try:
            result["judge"] = judge(profile.get("context"), case.get("rubric"), result["turns"])
        except (anthropic.APIError, BotError) as e:
            result["judge_error"] = str(e)
    return result


def _execute(run, bots, suite):
    jobs = [(case, bot) for case in suite["cases"] for bot in bots]
    try:
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            futures = [pool.submit(_run_case, suite, case, bot, run["judge"]) for case, bot in jobs]
            for fut in futures:
                res = fut.result()
                with _lock:
                    run["results"].append(res)
                    run["progress"]["done"] += 1
                _save(run)
        run["summary"] = summarise(run, suite)
        run["status"] = "done"
    except Exception as e:  # keep the partial results visible in the UI
        run["status"] = "failed"
        run["failure"] = f"{type(e).__name__}: {e}"
    _save(run)


# ---------- Summary ----------

def _pct(values):
    values = [v for v in values if v is not None]
    return round(100 * sum(values) / len(values), 1) if values else None


def _percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def _category_score(rs, category):
    """Share of a category's cases that passed: the checks and (when judged) the judge must both pass."""
    rs = [r for r in rs if r["category"] == category]
    return _pct([_case_passed(r) for r in rs])


def _case_passed(r):
    if r["error"]:
        return False
    verdicts = [v for v in (r["checks"], (r["judge"] or {}).get("passed")) if v is not None]
    return all(verdicts) if verdicts else None


def summarise(run, suite):
    categories = sorted({c.get("category", "general") for c in suite["cases"]})
    bots = []
    for b in run["bots"]:
        all_rs = [r for r in run["results"] if r["bot_id"] == b["id"]]
        rs = [r for r in all_rs if not r.get("unsupported") and not r.get("blocked")]
        latencies = [t["latency_ms"] for r in rs for t in r["turns"]]
        judged = [r["judge"] for r in rs if r["judge"]]
        quality = None
        if judged:
            mean = statistics.mean((j["correctness"] + j["helpfulness"] + j["tone"]) / 3 for j in judged)
            quality = round((mean - 1) / 4 * 100, 1)
        bots.append({
            "id": b["id"], "label": b["label"], "cases": len(rs),
            "accuracy": _pct([r["checks"] for r in rs]),
            "pass_rate": _pct([_case_passed(r) for r in rs]),
            "quality": quality,
            "judge_pass": _pct([j["passed"] for j in judged]) if judged else None,
            "correctness": round(statistics.mean(j["correctness"] for j in judged), 2) if judged else None,
            "helpfulness": round(statistics.mean(j["helpfulness"] for j in judged), 2) if judged else None,
            "tone": round(statistics.mean(j["tone"] for j in judged), 2) if judged else None,
            "latency_p50": _percentile(latencies, 50), "latency_p95": _percentile(latencies, 95),
            "errors": sum(1 for r in rs if r["error"]),
            "blocked": sorted(r["case_id"] for r in all_rs if r.get("blocked")),
            "unsupported": sorted(r["case_id"] for r in all_rs if r.get("unsupported")),
            "by_category": {c: _category_score(rs, c) for c in categories},
        })

    fastest = min((b["latency_p50"] for b in bots if b["latency_p50"]), default=None)
    weights = WEIGHTS_WITH_JUDGE if run["judge"] and any(b["quality"] is not None for b in bots) else WEIGHTS_NO_JUDGE
    for b in bots:
        b["speed"] = round(100 * fastest / b["latency_p50"], 1) if fastest and b["latency_p50"] else 0
        b["overall"] = round(sum(w * (b[k] or 0) for k, w in weights.items()), 1)

    ranked = sorted(bots, key=lambda b: b["overall"], reverse=True)
    for i, b in enumerate(ranked, 1):
        b["rank"] = i
    winner = ranked[0] if ranked else None
    return {"bots": bots, "categories": categories, "weights": weights,
            "winner": {"id": winner["id"], "label": winner["label"], "overall": winner["overall"],
                       "margin": round(winner["overall"] - ranked[1]["overall"], 1) if len(ranked) > 1 else None}
            if winner else None}
