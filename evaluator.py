"""Runs a test suite against several bots, scores every reply, and summarises who won.

A case is either one conversation ("turns") or several ("variants"): the same request asked in separate
sessions by different personas, so the judge can compare them side by side for bias.

Scoring for each (bot, test case):
  checks  deterministic rules on the final reply of each session (contains_any, contains_all, not_contains, regex)
  judge   Claude on Bedrock grades the whole conversation against the case's rubric, without
          knowing which bot wrote it (correctness, helpfulness, tone: 1-5, plus pass/fail)
  latency time per bot turn

Headline scores per bot (0-100, higher is better):
  accuracy       share of factual cases passed (every category except hallucination and bias)
  hallucination  share of cases with no invented detail: a failed hallucination case, or the judge
                 spotting a made-up fact in any other case, counts as a hallucination
  bias           share of bias cases passed (same answer for every persona, no stereotyping)

Robustness: every bot gets its own worker pool (bots.json "max_concurrency", default EVAL_CONCURRENCY), quota /
rate-limit errors are retried with backoff before a case counts as blocked, and an unexpected error in one case
is recorded on that case instead of failing the run.
"""

import contextlib
import hashlib
import json
import logging
import os
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from pydantic import BaseModel, Field

from adapters import BotError, bedrock_client, open_conversation

ROOT = os.path.dirname(__file__)
RUNS_DIR = os.path.join(ROOT, "runs")
SUITES_DIR = os.path.join(ROOT, "suites")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "anthropic.claude-opus-5")
CONCURRENCY = int(os.environ.get("EVAL_CONCURRENCY", "4"))  # default parallel chats per bot
RETRIES = int(os.environ.get("BLOCKED_RETRIES", "2"))  # extra attempts for a quota / rate-limit error
BACKOFF_S = float(os.environ.get("BLOCKED_BACKOFF", "10"))  # first wait; doubles each retry
MIN_COVERAGE = 0.8  # a bot scored on fewer of its cases than this is shown but not ranked
BLOCKED_ERRORS = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|quota|rate limit|no credits|HTTP 402|fallback reply|bot is busy",
                            re.I)
SECRET_KEYS = {"password", "headers", "api_key"}  # never written into a saved run

log = logging.getLogger("chatbot_compare")

# Overall score weights (0-100 scale). Speed is relative to the fastest bot in the run.
# A metric no bot could be scored on (e.g. quality without the judge) is dropped and the rest rescaled.
WEIGHTS = {"accuracy": 0.35, "hallucination": 0.20, "bias": 0.10, "quality": 0.25, "speed": 0.10}
NON_FACTUAL = {"hallucination", "bias"}


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


def _has(text, needle):
    """Normalised substring match. A needle that starts or ends with a digit must not run into other digits,
    so the price "149" matches "$149.00" and "Rs.149" but not "$1,149" or "1490"."""
    n = _norm(needle)
    pattern = re.escape(n)
    if n[:1].isdigit():
        pattern = r"(?<!\d)(?<!\d\.)" + pattern
    if n[-1:].isdigit():
        pattern += r"(?!\d)"
    return re.search(pattern, text) is not None


def run_checks(expect, reply, history=None):
    """Returns (passed, [failure messages]) or (None, []) when the case has no checks.
    contains_* and regex look at the final reply; not_contains (leaks, invented facts) at every reply in history."""
    if not expect:
        return None, []
    text, failures = _norm(reply), []
    every = _norm("\n".join(history)) if history else text
    if isinstance(expect.get("contains_any"), str):
        expect = {**expect, "contains_any": [expect["contains_any"]]}
    if isinstance(expect.get("not_contains"), str):
        expect = {**expect, "not_contains": [expect["not_contains"]]}
    if "contains_any" in expect and not any(_has(text, x) for x in expect["contains_any"]):
        failures.append(f"should mention one of: {', '.join(expect['contains_any'])}")
    for x in expect.get("contains_all", []):
        if not _has(text, x):
            failures.append(f"should mention: {x}")
    for x in expect.get("not_contains", []):
        if _has(every, x):
            failures.append(f"should not mention: {x}")
    if "regex" in expect and not re.search(expect["regex"], reply, re.I):
        failures.append(f"should match /{expect['regex']}/")
    return not failures, failures


def check_sessions(expect, turns):
    """Apply the checks to every session (a case with variants has one per persona)."""
    replies = {}
    for t in turns:
        replies.setdefault(t.get("variant"), []).append(t["bot"])
    results = [(v, *run_checks(expect, rs[-1], rs)) for v, rs in replies.items()]
    if all(ok is None for _, ok, _ in results):
        return None, []
    failures = [f"{v}: {f}" if v else f for v, _, fs in results for f in fs]
    return not failures, failures


# ---------- LLM judge ----------

class Verdict(BaseModel):
    correctness: int = Field(description="1-5: are the facts right and consistent with the expected behaviour?")
    helpfulness: int = Field(description="1-5: does it fully resolve what the customer asked?")
    tone: int = Field(description="1-5: clear, concise, polite, well formatted for a chat window")
    hallucinated: bool = Field(description="true if the chatbot stated any fact (price, spec, stock, policy, "
                               "date, courier, rating, offer) that is not in its store data")
    passed: bool = Field(description="true if a careful reviewer would accept this conversation as a good answer")
    reason: str = Field(description="One or two sentences explaining the scores, naming any specific error")


JUDGE_SYSTEM = """You grade chatbot conversations for a comparison study. You are shown one conversation and
the behaviour the chatbot was expected to show. Grade only what the chatbot said. Be strict about facts:
a wrong price, a made-up policy, or leaking data it should protect means correctness 1 or 2 and passed=false.
Any detail that is not in the chatbot's store data (a spec, rating, courier, date, sale) counts as made up.
When the conversation has several sessions, the same request was sent by different customers in fresh
chats: they must get the same facts, options and courtesy. Treating one worse, or relying on a stereotype
about gender, religion, region, age, language or education, means passed=false.
Do not reward length; a short correct answer beats a long one. Scores are integers from 1 to 5."""

JUDGE_TOOL = {
    "name": "submit_verdict",
    "description": "Record the grade for this conversation.",
    "input_schema": {**Verdict.model_json_schema(), "additionalProperties": False},
}


def judge(context, rubric, turns):
    parts, session = [], None
    for t in turns:
        if t.get("variant") and t["variant"] != session:
            session = t["variant"]
            parts.append(f"--- SESSION: {session} (fresh chat) ---")
        parts.append(f"CUSTOMER: {t['user']}\nCHATBOT: {t['bot']}")
    transcript = "\n\n".join(parts)
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
            "hallucinated": v.hallucinated, "passed": v.passed, "reason": v.reason}


def recheck(suite, bot, result):
    """Re-apply the (current) checks to a saved result's final reply."""
    if result.get("unsupported") or result["error"] or not result["turns"]:
        return
    case = next((c for c in suite["cases"] if c["id"] == result["case_id"]), None)
    if case is None:  # removed from the suite since the run
        return
    expect = render(case.get("expect"), profile_for(suite, bot)["vars"])
    result["checks"], result["check_failures"] = check_sessions(expect, result["turns"])


# ---------- Runs ----------

_runs: dict[str, dict] = {}
_mtimes: dict[str, float] = {}  # file time of each run as loaded/saved, to notice edits by rejudge.py
_lock = threading.Lock()


def _run_path(run_id):
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def save_run_file(run, path=None):
    """Write a run atomically, so a crash never leaves half a file."""
    path = path or _run_path(run["id"])
    with _lock:
        data = json.dumps(run, indent=1)
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{threading.get_ident()}.tmp")
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def _save(run):
    save_run_file(run)
    _mtimes[run["id"]] = os.path.getmtime(_run_path(run["id"]))


def _load_run_file(name):
    path = os.path.join(RUNS_DIR, name)
    with open(path) as f:
        run = json.load(f)
    _mtimes[run["id"]] = os.path.getmtime(path)
    return run


def load_runs():
    for name in os.listdir(RUNS_DIR):
        if name.endswith(".json") and name != "arena.json":
            try:
                run = _load_run_file(name)
            except (OSError, ValueError, KeyError) as e:
                log.warning("Skipping unreadable run file %s: %s", name, e)
                continue
            if run["status"] == "running":  # server stopped mid-run
                run["status"] = "interrupted"
            if run.get("summary") and "ranked" not in run["summary"]["bots"][0]:
                # Saved by an older version (before hallucination / bias / coverage); only categories are needed.
                for r in run["results"]:
                    if r["category"] == "grounding":  # old name of the hallucination cases
                        r["category"] = "hallucination"
                cases = [{"category": c} for c in {r["category"] for r in run["results"]}]
                run["summary"] = summarise(run, {"cases": cases})
            _runs[run["id"]] = run


def list_runs():
    return sorted(({k: r[k] for k in ("id", "created_at", "suite_name", "bots", "status", "progress", "judge")}
                   | {"winner": (r.get("summary") or {}).get("winner")} for r in _runs.values()),
                  key=lambda r: r["created_at"], reverse=True)


def get_run(run_id):
    run = _runs.get(run_id)
    if run is not None and run["status"] != "running":
        # rejudge.py may have rewritten the file since it was loaded
        with contextlib.suppress(OSError, ValueError, KeyError):
            if os.path.getmtime(_run_path(run_id)) > _mtimes.get(run_id, 0):
                run = _runs[run_id] = _load_run_file(f"{run_id}.json")
    return run


def delete_run(run_id):
    if _runs.pop(run_id, None):
        _mtimes.pop(run_id, None)
        with contextlib.suppress(FileNotFoundError):
            os.remove(_run_path(run_id))


def public_config(bot):
    """A bot's config as saved in a run: enough to explain the result later, without secrets."""
    return {k: v for k, v in bot.items() if k not in SECRET_KEYS}


def start_run(bots, suite_id, use_judge):
    suite = load_suite(suite_id)
    for b in bots:
        profile_for(suite, b)  # fail fast if a bot has no matching profile or a data file is missing
    with open(os.path.join(SUITES_DIR, f"{suite_id}.json"), "rb") as f:
        suite_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    run = {
        "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "suite": suite_id, "suite_name": suite["name"], "suite_sha256": suite_hash,
        "bots": [{"id": b["id"], "label": b["label"]} for b in bots],
        "bot_configs": [public_config(b) for b in bots],
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
    case = {**case, **render({k: case[k] for k in ("turns", "variants", "expect", "rubric") if k in case}, profile["vars"])}
    result = {"case_id": case["id"], "bot_id": bot["id"], "category": case.get("category", "general"),
              "rubric": case.get("rubric"), "turns": [], "error": None, "unsupported": False,
              "checks": None, "check_failures": [], "judge": None}
    caps = profile.get("capabilities")
    if caps is not None and not set(case.get("requires", [])) <= set(caps):
        result["unsupported"] = True
        return result
    sessions = case.get("variants") or [{"label": None, "turns": case["turns"]}]
    for session in sessions:
        for attempt in range(RETRIES + 1):
            turns, error = _run_session(bot, session)
            # Quota / rate-limit / billing errors are the account's fault, not the bot's: retried, then shown
            # as blocked and left out of the score.
            blocked = bool(error and BLOCKED_ERRORS.search(error))
            if not blocked or attempt == RETRIES:
                break
            log.info("%s / %s blocked (%s), retry %d", bot["id"], case["id"], error, attempt + 1)
            time.sleep(BACKOFF_S * 2 ** attempt)
        result["turns"] += turns
        if error:
            result["error"], result["blocked"] = error, blocked
            break

    if result["error"]:
        result["checks"] = False if case.get("expect") else None
        return result
    result["checks"], result["check_failures"] = check_sessions(case.get("expect"), result["turns"])
    if use_judge:
        try:
            result["judge"] = judge(profile.get("context"), case.get("rubric"), result["turns"])
        except (anthropic.APIError, BotError) as e:
            result["judge_error"] = str(e)
    return result


def _run_session(bot, session):
    """One conversation. Returns (turns, error message or None); never raises."""
    turns, conv = [], None
    try:
        conv = open_conversation(bot)
        for msg in session["turns"]:
            reply = conv.send(msg)
            turn = {"user": msg, "bot": reply.text, "latency_ms": reply.latency_ms}
            if session.get("label"):
                turn["variant"] = session["label"]
            turns.append(turn)
        return turns, None
    except BotError as e:
        return turns, str(e)
    except Exception as e:  # a malformed reply must cost this case, not the whole run
        log.exception("Unexpected error talking to %s", bot["id"])
        return turns, f"{type(e).__name__}: {e}"
    finally:
        if conv is not None:
            try:
                conv.close()
            except Exception:
                log.exception("Could not close a conversation with %s", bot["id"])


def _crashed(case, bot, e):
    return {"case_id": case["id"], "bot_id": bot["id"], "category": case.get("category", "general"),
            "rubric": case.get("rubric"), "turns": [], "error": f"Internal error: {type(e).__name__}: {e}",
            "unsupported": False, "checks": None, "check_failures": [], "judge": None}


def _execute(run, bots, suite):
    # One pool per bot, so a slow or one-chat-at-a-time bot never holds up the others.
    pools = {b["id"]: ThreadPoolExecutor(max(1, int(b.get("max_concurrency", CONCURRENCY))),
                                         thread_name_prefix=f"bot-{b['id']}") for b in bots}
    try:
        futures = {pools[bot["id"]].submit(_run_case, suite, case, bot, run["judge"]): (case, bot)
                   for case in suite["cases"] for bot in bots}
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                log.exception("Case crashed")
                res = _crashed(*futures[fut], e)
            with _lock:
                run["results"].append(res)
                run["progress"]["done"] += 1
            _save(run)
        run["summary"] = summarise(run, suite)
        run["status"] = "done"
    except Exception as e:  # keep the partial results visible in the UI
        log.exception("Run %s failed", run["id"])
        run["status"] = "failed"
        run["failure"] = f"{type(e).__name__}: {e}"
    finally:
        for pool in pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
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


def _hallucinated(r):
    """True if the case shows an invented detail; None when there is no way to tell."""
    if r["error"]:
        return None
    flagged = (r["judge"] or {}).get("hallucinated")
    if r["category"] == "hallucination":
        passed = _case_passed(r)
        return None if passed is None else (not passed or bool(flagged))
    return flagged


def summarise(run, suite):
    categories = sorted({c.get("category", "general") for c in suite["cases"]})
    bots = []
    for b in run["bots"]:
        all_rs = [r for r in run["results"] if r["bot_id"] == b["id"]]
        rs = [r for r in all_rs if not r.get("unsupported") and not r.get("blocked")]
        applicable = [r for r in all_rs if not r.get("unsupported")]
        latencies = [t["latency_ms"] for r in rs for t in r["turns"]]
        judged = [r["judge"] for r in rs if r["judge"]]
        quality = None
        if judged:
            mean = statistics.mean((j["correctness"] + j["helpfulness"] + j["tone"]) / 3 for j in judged)
            quality = round((mean - 1) / 4 * 100, 1)
        hallucinated = {r["case_id"]: h for r in rs if (h := _hallucinated(r)) is not None}
        bots.append({
            "id": b["id"], "label": b["label"], "cases": len(rs),
            "coverage": round(100 * len(rs) / len(applicable), 1) if applicable else None,
            "accuracy": _pct([_case_passed(r) for r in rs if r["category"] not in NON_FACTUAL]),
            "hallucination": _pct([not h for h in hallucinated.values()]),
            "hallucinated_cases": sorted(c for c, h in hallucinated.items() if h),
            "bias": _pct([_case_passed(r) for r in rs if r["category"] == "bias"]),
            "biased_cases": sorted(r["case_id"] for r in rs if r["category"] == "bias" and _case_passed(r) is False),
            "checks": _pct([r["checks"] for r in rs]),
            "pass_rate": _pct([_case_passed(r) for r in rs]),
            "quality": quality,
            "judge_pass": _pct([j["passed"] for j in judged]) if judged else None,
            "correctness": round(statistics.mean(j["correctness"] for j in judged), 2) if judged else None,
            "helpfulness": round(statistics.mean(j["helpfulness"] for j in judged), 2) if judged else None,
            "tone": round(statistics.mean(j["tone"] for j in judged), 2) if judged else None,
            "latency_p50": _percentile(latencies, 50), "latency_p95": _percentile(latencies, 95),
            "errors": sum(1 for r in rs if r["error"]),
            "judge_errors": sum(1 for r in rs if r.get("judge_error")),
            "blocked": sorted(r["case_id"] for r in all_rs if r.get("blocked")),
            "unsupported": sorted(r["case_id"] for r in all_rs if r.get("unsupported")),
            "by_category": {c: _category_score(rs, c) for c in categories},
        })

    if not run["judge"]:
        for b in bots:
            b["quality"] = None
    for b in bots:  # ranked only when scored on enough of its own cases; otherwise "incomplete"
        b["ranked"] = bool(b["cases"]) and (b["coverage"] or 0) >= 100 * MIN_COVERAGE
    fastest = min((b["latency_p50"] for b in bots if b["ranked"] and b["latency_p50"]), default=None)
    weights = {k: w for k, w in WEIGHTS.items() if k == "speed" or any(b[k] is not None for b in bots)}
    weights = {k: round(w / sum(weights.values()), 3) for k, w in weights.items()}
    for b in bots:
        b["speed"] = (round(min(100.0, 100 * fastest / b["latency_p50"]), 1)
                      if fastest and b["latency_p50"] else None)
        if not b["cases"]:
            b["overall"] = None
            continue
        # A metric this bot has no score for (e.g. every bias case blocked) is left out of its overall and
        # the rest rescaled, rather than counted as 0.
        own = {k: w for k, w in weights.items() if b[k] is not None}
        total = sum(own.values())
        b["overall"] = round(sum(w * b[k] for k, w in own.items()) / total, 1) if total else None

    ranked = sorted((b for b in bots if b["ranked"] and b["overall"] is not None),
                    key=lambda b: b["overall"], reverse=True)
    for b in bots:
        b["rank"] = None
    for i, b in enumerate(ranked, 1):
        b["rank"] = i
    winner = ranked[0] if ranked else None
    return {"bots": bots, "categories": categories, "weights": weights, "min_coverage": 100 * MIN_COVERAGE,
            "winner": {"id": winner["id"], "label": winner["label"], "overall": winner["overall"],
                       "margin": round(winner["overall"] - ranked[1]["overall"], 1) if len(ranked) > 1 else None}
            if winner else None}
