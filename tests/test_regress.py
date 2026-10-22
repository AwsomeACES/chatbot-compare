"""Baselines and regression alerts (no network, no bots)."""

import pytest

import evaluator
import regress


def result(bot, case, category="products", passed=True, repeat=0, **extra):
    return {"case_id": case, "bot_id": bot, "category": category, "repeat": repeat, "error": None,
            "unsupported": False, "checks": passed, "check_failures": [], "judge": None,
            "turns": [{"user": "q", "bot": "a", "latency_ms": 1000}], **extra}


def make_run(run_id, created, results, suite_sha="s1", bots=("a",)):
    run = {"id": run_id, "created_at": created, "suite": "store_support", "suite_sha256": suite_sha,
           "bots": [{"id": b, "label": b.upper()} for b in bots], "judge": False, "status": "done",
           "results": results}
    cats = {r["category"] for r in results}
    run["summary"] = evaluator.summarise(run, {"cases": [{"category": c} for c in cats]})
    return run


@pytest.fixture
def runs(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluator, "BASELINES_FILE", str(tmp_path / "baselines.json"))
    store = {}
    monkeypatch.setattr(evaluator, "_runs", store)
    monkeypatch.setattr(evaluator, "get_run", store.get)

    def add(run):
        store[run["id"]] = run
        return run
    return add


GOOD = [result("a", f"p{i}") for i in range(10)] + [result("a", "inj", "prompt-injection"), result("a", "h1", "hallucination")]


def test_a_broken_safety_case_is_critical_and_a_product_case_a_warning(runs):
    runs(make_run("base", "2026-10-01T00:00:00", GOOD))
    evaluator.set_baseline("base")
    now = runs(make_run("now", "2026-10-02T00:00:00", [
        result("a", f"p{i}", passed=i != 3) for i in range(10)] + [
        result("a", "inj", "prompt-injection", passed=False), result("a", "h1", "hallucination")]))
    rep = evaluator.regressions(now)
    b = rep["bots"][0]
    assert b["status"] == "compared" and [x["case_id"] for x in b["broken"]] == ["inj", "p3"]
    assert rep["critical"] == 1 and rep["warnings"] >= 1
    assert b["deltas"]["safety"] == {"before": 100.0, "now": 0.0, "delta": -100.0}
    assert "CRITICAL: inj (prompt-injection) passed in the baseline, fails now" in evaluator.regression_text(now, rep)


def test_fixed_and_new_cases_are_reported_but_not_alerted(runs):
    runs(make_run("base", "2026-10-01T00:00:00", [result("a", "p1", passed=False), result("a", "p2")]))
    evaluator.set_baseline("base")
    now = runs(make_run("now", "2026-10-02T00:00:00",
                        [result("a", "p1"), result("a", "p2"), result("a", "brand-new", passed=False)], suite_sha="s2"))
    rep = evaluator.regressions(now)
    b = rep["bots"][0]
    assert [x["case_id"] for x in b["fixed"]] == ["p1"] and [x["case_id"] for x in b["new_failing"]] == ["brand-new"]
    assert b["suite_changed"] and rep["critical"] == rep["warnings"] == 0


def test_one_flaky_repeat_is_not_a_regression(runs):
    runs(make_run("base", "2026-10-01T00:00:00", [result("a", "p1", repeat=i) for i in range(3)]))
    evaluator.set_baseline("base")
    now = runs(make_run("now", "2026-10-02T00:00:00",
                        [result("a", "p1", repeat=i, passed=i != 0) for i in range(3)]))  # 3/3 -> 2/3
    assert evaluator.regressions(now)["bots"][0]["broken"] == []


def test_blocked_cases_are_not_regressions(runs):
    runs(make_run("base", "2026-10-01T00:00:00", [result("a", "p1"), result("a", "p2")]))
    evaluator.set_baseline("base")
    now = runs(make_run("now", "2026-10-02T00:00:00",
                        [result("a", "p1"), result("a", "p2", passed=False, blocked=True, error="429")]))
    assert evaluator.regressions(now)["bots"][0]["broken"] == []


def test_runs_without_a_usable_baseline_say_why(runs):
    base = runs(make_run("base", "2026-10-02T00:00:00", GOOD))
    older = runs(make_run("older", "2026-10-01T00:00:00", GOOD, bots=("a", "b")))
    evaluator.set_baseline("base")
    assert [b["status"] for b in evaluator.regressions(older)["bots"]] == ["older_than_baseline", "no_baseline"]
    assert evaluator.regressions(base)["bots"][0]["status"] == "is_baseline"
    evaluator.clear_baseline("base")
    assert evaluator.load_baselines() == {}


def test_only_a_finished_run_can_be_a_baseline(runs):
    runs({**make_run("live", "2026-10-01T00:00:00", GOOD), "status": "running"})
    with pytest.raises(ValueError):
        evaluator.set_baseline("live")


def test_cli_exit_codes_and_webhook(runs, monkeypatch, capsys):
    posted = []
    monkeypatch.setattr(regress, "notify", posted.append)
    monkeypatch.setattr(evaluator, "load_runs", lambda: None)
    runs(make_run("base", "2026-10-01T00:00:00", GOOD))
    evaluator.set_baseline("base")
    runs(make_run("same", "2026-10-02T00:00:00", GOOD))
    runs(make_run("leak", "2026-10-03T00:00:00", [r if r["case_id"] != "inj" else {**r, "checks": False} for r in GOOD]))
    assert regress.main(["check", "same"]) == 0 and not posted
    assert regress.main(["check", "leak"]) == 2 and "1 critical" in posted[0]
    assert regress.main(["check", "missing"]) == 3
    assert "no regressions" in capsys.readouterr().out


def test_a_run_of_selected_cases_only_compares_cases_and_cannot_be_a_baseline(runs):
    runs(make_run("base", "2026-10-01T00:00:00", GOOD))
    evaluator.set_baseline("base")
    part = runs({**make_run("part", "2026-10-02T00:00:00", [result("a", "inj", "prompt-injection")]), "case_ids": ["inj"]})
    rep = evaluator.regressions(part)
    assert rep["bots"][0]["status"] == "compared" and rep["warnings"] == 0 and rep["critical"] == 0
    with pytest.raises(ValueError, match="selected cases"):
        evaluator.set_baseline("part")


def test_a_critical_break_is_retested_and_downgraded_when_it_was_a_fluke(runs, monkeypatch, capsys):
    evaluator.set_baseline(runs(make_run("base", "2026-10-01T00:00:00", GOOD))["id"])
    broken = [r if r["case_id"] != "inj" else result("a", "inj", "prompt-injection", passed=False) for r in GOOD]
    run = runs(make_run("now", "2026-10-02T00:00:00", broken))
    asked = []

    def start_run(bots, suite, judge, repeats, case_ids, **kw):
        asked.append((case_ids, repeats))
        return make_run("retest", "2026-10-02T01:00:00", [result("a", "inj", "prompt-injection", repeat=i, passed=i > 0)
                                                           for i in range(repeats)])
    monkeypatch.setattr(regress.evaluator, "start_run", start_run)
    assert regress.report(run, bots=[{"id": "a", "label": "A"}]) == 1  # a warning now, not critical
    assert asked == [(["inj"], regress.CONFIRM_REPEATS)] and "flaky" in capsys.readouterr().out


def test_preflight_asks_a_real_question_so_a_bot_whose_llm_is_out_is_caught(monkeypatch):
    from adapters import BotError

    class GreetsWithoutItsLLM:
        def send(self, message):
            if message == "Hi":
                return None
            raise BotError("Bot's LLM call failed (fallback reply, model_used=auto:mock)")

        def close(self):
            pass

    monkeypatch.setattr(regress, "open_conversation", lambda cfg: GreetsWithoutItsLLM())
    bot = {"id": "m", "label": "M"}
    suite = {"cases": [{"id": "c", "turns": ["What does the {thing} cost?"]}], "profiles": {"p": {"vars": {"thing": "TV"}}}}
    assert regress.preflight([bot]) == []
    assert regress.preflight([{**bot, "profile": "p"}], suite)[0][0] == "M"


def test_judge_preflight_reports_a_retired_judge_model(monkeypatch):
    from adapters import BotError

    class Retired:
        model = "moonshotai/kimi-k3"

        def structured(self, *args):
            raise BotError("moonshotai/kimi-k3: HTTP 410: end of life")

    class Fine:
        model = "gemini-3.7-flash"

        def structured(self, *args):
            return {"prime": True}

    monkeypatch.setattr(regress.evaluator.llm, "JUDGE", Retired())
    monkeypatch.setattr(regress.evaluator.llm, "SECOND_JUDGE", Fine())
    assert [m for m, _ in regress.judge_preflight(second=True)] == ["moonshotai/kimi-k3"]
    monkeypatch.setattr(regress.evaluator.llm, "JUDGE", Fine())
    assert regress.judge_preflight(second=True) == []


def test_resume_continues_a_stopped_run_in_this_process_then_checks_it(monkeypatch):
    run = {"id": "r1", "status": "interrupted", "bots": [{"id": "a", "label": "A"}], "progress": {"done": 3, "total": 9}}
    resumed = []

    def resume_run(run_id, bots, budget_usd=None):
        resumed.append((run_id, [b["id"] for b in bots]))
        run.update(status="done", progress={"done": 9, "total": 9})
    monkeypatch.setattr(regress, "load_bots", lambda: [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}])
    monkeypatch.setattr(regress.evaluator, "resume_run", resume_run)
    monkeypatch.setattr(regress, "report", lambda r, *a, **k: 0 if r["status"] == "done" else 9)
    assert regress.cmd_resume(run) == 0 and resumed == [("r1", ["a"])]

    monkeypatch.setattr(regress, "load_bots", lambda: [])  # its bot was since removed from bots.json
    assert regress.cmd_resume({**run, "status": "interrupted"}) == 3
