"""The quick suite: a short subset of the store suite for runs that finish in minutes."""
import evaluator
import regress


def store():
    return evaluator.load_suite("store_support")


def test_quick_cases_exist_and_cover_every_skill():
    s = store()
    cases = {c["id"]: c for c in s["cases"]}
    quick = s["quick"]
    assert len(quick) == len(set(quick)), "duplicate quick case"
    assert all(q in cases for q in quick), "unknown quick case id"
    assert {cases[q]["category"] for q in quick} == {c["category"] for c in s["cases"]}
    assert len(quick) < len(cases) / 3


def test_quick_cases_run_on_every_bot():
    # A case that needs a capability only some bots have would be "not supported" for the others,
    # so the quick set would rank bots on different cases.
    s = store()
    cases = {c["id"]: c for c in s["cases"]}
    assert not [q for q in s["quick"] if cases[q].get("requires")]


def test_list_suites_reports_the_quick_subset():
    by_id = {s["id"]: s for s in evaluator.list_suites()}
    st = by_id["store_support"]
    assert st["quick"] == store()["quick"]
    assert st["quick_rewordings"] <= st["rewordings"]
    assert by_id["generic_support"]["quick"] == []


def test_help_never_starts_a_run(monkeypatch, capsys):
    started = []
    monkeypatch.setattr(evaluator, "start_run", lambda *a, **k: started.append(a))
    monkeypatch.setattr(evaluator, "load_runs", lambda: started.append("load"))
    assert regress.main(["run", "--help"]) == 0
    assert regress.main(["run", "--bots", "x", "-h"]) == 0
    assert not started
    assert "Usage" in capsys.readouterr().out


def test_quick_flag_passes_the_quick_case_ids(monkeypatch):
    got = {}
    bot = {"id": "b1", "profile": "voltkart"}
    monkeypatch.setattr(regress, "load_bots", lambda: [bot])
    monkeypatch.setattr(regress, "preflight", lambda bots, suite: [])
    monkeypatch.setattr(regress, "judge_preflight", lambda second: [])
    monkeypatch.setattr(regress, "baseline_used_rewordings", lambda ids: False)

    def fake_start(bots, suite_id, judge, **kw):
        got.update(kw)
        raise SystemExit(0)

    monkeypatch.setattr(evaluator, "start_run", fake_start)
    try:
        regress.cmd_run(["--bots", "b1", "--quick", "--no-judge"])
    except SystemExit:
        pass
    assert got["case_ids"] == store()["quick"]
