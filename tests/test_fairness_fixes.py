"""Scoring and safety fixes: disputed verdicts, hallucination counting, case weights, shared footing for unsupported
cases, the timing pass, a pinned judge, masked storage, bot key names, consent for LAN hosts."""
import pytest

import adapters
import app
import evaluator
import governance
import llm
import quickbot
from adapters import BotError
from test_evaluator import BOT_A, SUITE, FakeConversation, result

V = {"correctness": 4, "helpfulness": 4, "tone": 4, "hallucinated": False, "passed": True, "reason": ""}


def verdict(**kw):
    return {**V, **kw}


def summary(results, judge=True, **run):
    bots = sorted({r["bot_id"] for r in results})
    run = {"bots": [{"id": b, "label": b.upper()} for b in bots], "judge": judge, "results": results, **run}
    return {b["id"]: b for b in evaluator.summarise(run, {"cases": [{"category": r["category"]} for r in results]})["bots"]}


# ---------- two judges ----------

def test_a_verdict_the_two_judges_disagree_on_counts_for_nothing():
    split = result("a", "p1", passed=None, judge=verdict(passed=True), judge2=verdict(passed=False))
    agreed = result("a", "p2", passed=None, judge=verdict(passed=False), judge2=verdict(passed=False))
    assert evaluator._case_passed(split) is None and evaluator._disputed(split)
    assert evaluator._case_passed(agreed) is False and not evaluator._disputed(agreed)
    # the exact checks still decide a disputed case that has them
    assert evaluator._case_passed({**split, "checks": False}) is False
    b = summary([split, agreed])["a"]
    assert b["judge_disputed"] == ["p1"] and b["accuracy"] == 0.0


def test_quality_averages_both_judges():
    r = result("a", "p1", judge=verdict(correctness=5, helpfulness=5, tone=5), judge2=verdict(correctness=3,
                                                                                                 helpfulness=3, tone=3))
    assert evaluator._facts(r, True)["quality"] == 4


def test_a_judge_of_the_same_family_as_a_bot_is_flagged_unless_another_family_checked_it():
    rs = [result("a", "p1", judge=verdict(model="gemini-3.7-flash")),
          result("b", "p1", judge=verdict(model="gemini-3.7-flash"))]
    run = {"bots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], "judge": True, "results": rs,
           "judge_model": "gemini-3.7-flash", "bot_configs": [{"id": "a", "llm": "Gemini 3.6 Flash"},
                                                              {"id": "b", "llm": "Claude Sonnet 5"}]}
    s = evaluator.summarise(run, {"cases": [{"category": "products"}]})
    assert s["judge_overlap"] == ["A"]
    run["second_judge_model"] = "moonshotai/kimi-k2.6"
    for r in rs:
        r["judge2"] = verdict(model="moonshotai/kimi-k2.6")
    assert evaluator.summarise(run, {"cases": [{"category": "products"}]})["judge_overlap"] == []
    assert evaluator.model_family("moonshotai/kimi-k2.6") == "kimi" and evaluator.model_family("qwen2.5:3b") == "qwen"


def test_bots_graded_by_different_judge_models_get_no_clear_winner():
    rs = [result("a", f"p{i}", judge=verdict(model="gemini-3.7-flash")) for i in range(5)]
    rs += [result("b", f"p{i}", passed=False, judge=verdict(passed=False, model="qwen2.5:3b")) for i in range(5)]
    run = {"bots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], "judge": True, "results": rs}
    w = evaluator.summarise(run, {"cases": [{"category": "products"}]})["winner"]
    assert w["id"] == "a" and w["mixed_judges"] and not w["clear"]


def test_the_judge_uses_only_its_first_model_unless_switching_is_on(monkeypatch):
    pinned = llm.Endpoint(llm.OLLAMA, "first,second", switch=False, fallback=llm.Endpoint(llm.OLLAMA, "spare"))
    assert pinned.models == ["first"] and pinned.fallback is None
    assert llm.Endpoint(llm.OLLAMA, "first,second").models == ["first", "second"]


# ---------- what counts ----------

def test_failing_a_hallucination_case_without_an_invented_fact_isnt_a_hallucination():
    unhelpful = result("a", "h1", "hallucination", passed=False, judge=verdict(passed=False, hallucinated=False))
    invented = result("a", "h2", "hallucination", passed=False, check_failures=["should not mention: 30-day"],
                      judge=verdict(passed=False, hallucinated=False))
    flagged = result("a", "h3", "hallucination", passed=True, judge=verdict(hallucinated=True))
    no_judge = result("a", "h4", "hallucination", passed=False)
    assert [evaluator._hallucinated(r) for r in (unhelpful, invented, flagged, no_judge)] == [False, True, True, True]


def test_robustness_cases_count_in_accuracy():
    assert summary([result("a", "r1", "robustness", passed=False), result("a", "p1")], judge=False)["a"]["accuracy"] == 50.0


def test_a_case_asked_in_many_wordings_counts_once():
    rs = [result("a", "inj", "prompt-injection", passed=False, wording=w) for w in range(6)]
    rs += [result("a", "guard", "guardrails")]
    assert summary(rs, judge=False)["a"]["safety"] == 50.0  # not 1 of 7


def test_overall_compares_bots_only_on_cases_every_ranked_bot_supports():
    rs = [result("a", "p1"), result("a", "t1", "after-sales", passed=False),
          result("b", "p1"), result("b", "t1", "after-sales", unsupported=True, turns=[])]
    for i in range(2, 6):
        rs += [result("a", f"p{i}"), result("b", f"p{i}")]
    run = {"bots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], "judge": False, "results": rs}
    s = evaluator.summarise(run, {"cases": [{"category": "products"}, {"category": "after-sales"}]})
    a, b = s["bots"]
    assert a["overall"] == b["overall"] and s["shared"] == {"samples": 5, "left_out": 1}
    assert a["accuracy"] < b["accuracy"]  # the per-bot scores still show a's failure


# ---------- speed ----------

def test_speed_comes_from_the_timing_pass_when_it_has_enough_replies(monkeypatch):
    monkeypatch.setattr(evaluator, "TIMING_N", 3)
    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: FakeConversation(["fine"]))
    suite = {"cases": [{"id": f"c{i}", "turns": [f"q{i}"]} for i in range(4)]
             + [{"id": "multi", "turns": ["a", "b"]}]}
    assert evaluator.timing_prompts(suite, BOT_A) == ["q0", "q1", "q2"]
    timing = evaluator.timing_pass(suite, [BOT_A])
    assert timing == {"a": [100, 100, 100]}
    slow = [result("a", f"p{i}", turns=[{"user": "q", "bot": "a", "latency_ms": 30000}]) for i in range(3)]
    b = summary(slow, judge=False, timing=timing)["a"]
    assert b["latency_p50"] == 100 and b["speed"] == 100 and b["speed_from"] == "timing pass"


# ---------- errors ----------

def test_a_bot_that_stays_overloaded_fails_the_case(monkeypatch):
    scripts = [[BotError("HTTP 503: high demand")] for _ in range(evaluator.RETRIES + 1)]
    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: FakeConversation(scripts.pop(0)))
    monkeypatch.setattr(evaluator, "BACKOFF_S", 0)
    r = evaluator._run_case(SUITE, SUITE["cases"][0], BOT_A, use_judge=False)
    assert not scripts and r["error"] and not r["blocked"] and evaluator.outcome(r) == "error"


# ---------- personal data, keys, consent ----------

def test_personal_data_a_bot_produced_is_masked_in_the_saved_run(monkeypatch):
    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: FakeConversation(["Call 9876543210 now"]))
    suite = {"cases": [{"id": "c", "category": "guardrails", "turns": ["Hi"]}]}
    r = evaluator._run_case(suite, suite["cases"][0], {"id": "b"}, use_judge=False)
    assert r["pii"] == {"phone": 1} and r["turns"][0]["bot"] == "Call [phone number] now" and r["pii_masked"]


def test_a_bot_added_by_url_can_only_send_keys_meant_for_bots(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "secret")
    monkeypatch.setenv("BOT_MINE_KEY", "ok")
    monkeypatch.delenv("BOT_KEY_VARS", raising=False)
    assert adapters.bot_key_allowed("BOT_MINE_KEY") and not adapters.bot_key_allowed("GOOGLE_API_KEY")
    with pytest.raises(BotError, match="BOT_"):
        adapters._headers({"quick": True, "api_key_env": "GOOGLE_API_KEY"})
    with pytest.raises(BotError, match="BOT_"):
        quickbot.detect("http://localhost:1/v1", api_key_env="NVIDIA_API_KEY")
    assert adapters._headers({"quick": True, "api_key_env": "BOT_MINE_KEY"})["Authorization"] == "Bearer ok"
    monkeypatch.setenv("BOT_KEY_VARS", "OPENAI_API_KEY")
    assert adapters.bot_key_allowed("OPENAI_API_KEY")
    with pytest.raises(app.HTTPException) as e:
        app.detect_bot(app.DetectRequest(url="http://localhost:1", api_key_env="GOOGLE_API_KEY"))
    assert e.value.status_code == 400


def test_another_machine_on_the_network_needs_consent():
    assert not governance.is_local("http://printer.local:8000") and governance.is_local("http://127.0.0.1:8000")
    with pytest.raises(app.HTTPException):
        app.require_send_consent([{"id": "x", "label": "X", "url": "http://box.local/chat"}], False)
    app.require_send_consent([{"id": "x", "label": "X", "url": "http://box.local/chat"}], True)


def test_the_prompt_version_covers_the_verdict_schema(monkeypatch):
    assert "fair" in str(evaluator.VERDICT_SCHEMA)  # its field descriptions are grading rules
    assert len(evaluator.JUDGE_PROMPT_VERSION) == 8


def test_names_and_addresses_a_bot_produced_are_masked_but_test_data_is_not():
    known = governance.known_values("Customers: Rahul Sharma, Priya Patel.", "Hi, I'm Alex Fernandes")
    leak = "Her name is Meera Krishnan and she lives at 12, MG Road, Indiranagar, Bengaluru 560038."
    assert governance.unknown_pii(leak, known) == {"name": 1, "address": 1}
    assert governance.redact(leak, known)[0] == "Her name is [name] and she lives at [address]."
    assert governance.redact("Deliver to Mr Vikram Rao, pin code 400001.", known)[0] == "Deliver to Mr [name], pin code [address]."
    for fine in ("The customer name is Rahul Sharma.", "Customer: Alex Fernandes", "Sector 5 has 123456 units",
                 "The Sony headphones cost Rs 29,990."):
        assert governance.unknown_pii(fine, known) == {}, fine


def test_a_run_refuses_to_start_when_a_judge_has_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NVIDIA_API_KEY")
    monkeypatch.setattr(evaluator, "SUITES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setattr(evaluator.llm, "JUDGE", llm.Endpoint(llm.NIM, "moonshotai/kimi-k2.6", "NVIDIA_API_KEY"))
    monkeypatch.setattr(evaluator, "load_suite", lambda _: SUITE)
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        evaluator.start_run([BOT_A], "t", use_judge=True)


def test_the_main_judge_is_not_the_family_of_the_free_bots():
    assert evaluator.model_family(llm.JUDGE.models[0]) not in {"gemini", "claude"}


def test_a_safety_case_one_judge_finds_unsafe_fails():
    split = dict(passed=None, judge=verdict(passed=True), judge2=verdict(passed=False))
    assert evaluator._case_passed(result("a", "inj", "prompt-injection", **split)) is False
    assert evaluator._case_passed(result("a", "p1", "products", **split)) is None


def test_free_form_names_are_found_when_spacy_is_installed():
    if governance._ner() is None:
        pytest.skip("spaCy's en_core_web_sm isn't installed")
    known = governance.known_values("Customers: Rahul Sharma, Priya Patel.")
    assert governance.redact("Meera’s phone is new.", known)[0] == "[name]’s phone is new."
    assert governance.redact("I spoke to Kavitha Reddy yesterday.", known)[0] == "I spoke to [name] yesterday."
    assert governance.unknown_pii("Rahul Sharma's order is shipped.", known) == {}


def test_an_invented_product_is_shown_to_the_judge_not_masked_as_a_name():
    if governance._ner() is None:
        pytest.skip("spaCy's en_core_web_sm isn't installed")
    known = governance.known_values("Pulse Pro headphones Rs 149.", "How much are the Pulse Pro headphones?")
    reply = "They're Rs 99 this week, and the Pulse Max is Rs 199."
    assert governance.redact(reply, known)[0] == reply


def _run_now(monkeypatch, tmp_path, suite, judge_delay, **kw):
    """start_run in this thread, with a fake judge that takes judge_delay seconds per verdict."""
    import threading as real_threading
    import time as real_time
    from types import SimpleNamespace
    monkeypatch.setattr(evaluator, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(evaluator, "SUITES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setattr(evaluator, "load_suite", lambda _: suite)
    chats = []

    class Conv:
        def send(self, message):
            chats.append(real_time.monotonic())
            from adapters import Reply
            return Reply(text="TV-A is 100", latency_ms=1)

        def close(self):
            pass

    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: Conv())

    def structured(system, prompt, schema, name):
        real_time.sleep(judge_delay)
        return {"correctness": 5, "helpfulness": 5, "tone": 5, "hallucinated": False, "grounded": True,
                "passed": True, "reason": "", "evidence": ["TV-A is 100"]}

    monkeypatch.setattr(evaluator.llm.JUDGE, "structured", structured)
    monkeypatch.setattr(evaluator, "threading", SimpleNamespace(
        Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
        get_ident=real_threading.get_ident, Condition=real_threading.Condition, Lock=real_threading.Lock))
    governance._ner()  # loaded once per process (a second or two), not part of what's timed
    started = real_time.monotonic()
    run = evaluator.start_run([{**BOT_A, "max_concurrency": 1}], "t", True, comparative=False, **kw)
    return run, chats, real_time.monotonic() - started


def test_a_slow_judge_doesnt_hold_up_a_one_chat_at_a_time_bot(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluator, "JUDGE_CONCURRENCY", 6)
    suite = {**SUITE, "cases": [{**SUITE["cases"][0], "id": f"price{i}"} for i in range(6)]}
    run, chats, elapsed = _run_now(monkeypatch, tmp_path, suite, judge_delay=0.5)
    assert run["status"] == "done" and len(run["results"]) == 6 and all(r["judge"]["passed"] for r in run["results"])
    assert chats[-1] - chats[0] < 0.4  # all six chats ran back to back, without waiting for a verdict
    assert elapsed < 2.0  # graded in parallel: 6 x 0.5 s one after another would take 3 s


def test_grading_not_started_when_a_run_is_cancelled_is_left_for_rejudge(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluator, "JUDGE_CONCURRENCY", 1)
    suite = {**SUITE, "cases": [{**SUITE["cases"][0], "id": f"price{i}"} for i in range(3)]}
    orig = evaluator._grade

    def grade_then_cancel(res, grading, use_judge, second_judge=False):
        out = orig(res, grading, use_judge, second_judge)
        evaluator._stops[next(iter(evaluator._active))].set()  # cancelled after the first verdict
        return out

    monkeypatch.setattr(evaluator, "_grade", grade_then_cancel)
    run, _, _ = _run_now(monkeypatch, tmp_path, suite, judge_delay=0.2)
    graded = [r for r in run["results"] if r.get("judge")]
    skipped = [r for r in run["results"] if "cancelled" in (r.get("judge_error") or "")]
    assert run["status"] == "cancelled" and len(graded) == 1 and len(skipped) == 2


def test_rejudge_fills_in_a_missing_second_verdict_without_regrading_the_first(monkeypatch, tmp_path):
    import json as _json
    import sys
    import rejudge
    monkeypatch.setattr(evaluator, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(evaluator, "load_suite", lambda _: SUITE)
    first = verdict(model="moonshotai/kimi-k3")
    rs = [result("a", "price", judge=first, turns=[{"user": "Price of TV-A?", "bot": "TV-A is 100", "latency_ms": 1}],
                 judge2_error="Not graded: the run was cancelled (rejudge.py grades it)")]
    run = {"id": "r1", "suite": "t", "bots": [{"id": "a", "label": "A"}], "bot_configs": [BOT_A], "judge": True,
           "second_judge_model": "gemini-3.7-flash", "results": rs, "comparisons": [], "status": "done"}
    (tmp_path / "r1.json").write_text(_json.dumps(run))
    calls = []
    monkeypatch.setattr(evaluator, "judge", lambda *a: calls.append("first") or first)
    monkeypatch.setattr(evaluator, "judge_second", lambda *a: calls.append("second") or verdict(model="gemini-3.7-flash"))
    monkeypatch.setattr(evaluator.llm, "SECOND_JUDGE", llm.Endpoint(llm.GEMINI, "gemini-3.7-flash", "GOOGLE_API_KEY"))
    monkeypatch.setattr(sys, "argv", ["rejudge.py", "r1"])
    rejudge.main()
    saved = _json.loads((tmp_path / "r1.json").read_text())["results"][0]
    assert calls == ["second"] and saved["judge2"]["model"] == "gemini-3.7-flash" and "judge2_error" not in saved
