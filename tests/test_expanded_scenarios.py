"""Distinct authored coverage and five repeats without corrupting historical runs."""

import copy

from legacy_protocol import snapshot

from app.blackbox import studio_engine
from app.blackbox.runner import aggregate, make_run
from app.blackbox.schema import ImportedCase, Settings, Target


def config(**fields):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        consent=True,
        judge_consent=True,
        judges=[{"model": "fixture", "local": True}],
        **fields,
    )


def test_ten_distinct_cases_in_every_category_and_five_repeats(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    protocol = studio_engine.settings_file()
    assert len(protocol["cases"]) == 16
    for category, scenarios in protocol["scenario_sets"].items():
        assert len(scenarios) == 10
        assert len({tuple(s["turns"]) for s in scenarios}) == 10
        for scenario in scenarios:
            raw = {k: v for k, v in scenario.items() if k != "scenario_id"}
            ImportedCase.model_validate({"category": category, **raw})
    rows = studio_engine.cases(config())
    assert len(rows) == 800
    assert len({r["id"] for r in rows}) == 800
    assert len({r["base_case_id"] for r in rows}) == 160
    assert {r["repeat"] for r in rows} == {1, 2, 3, 4, 5}


def test_each_reference_used_once_per_distinct_fact_scenario(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    refs = [{"prompt": f"Price of P{i}?", "reference": {"price": i}} for i in range(10)]
    rows = studio_engine.cases(config(references=refs, repeat_counts={"hallucination": 1}))
    factual = [r for r in rows if r["category"] == "hallucination"]
    assert len(factual) == 10
    assert [r["reference"]["price"] for r in factual] == list(range(10))


def test_repeat_spread_is_within_case_not_between_different_cases(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    run = make_run(config())
    for case in run["cases"]:
        case["results"][0].update(status="passed", score=100 if case["scenario_index"] == 1 else 80)
    aggregate(run)
    group = run["studio"]["bots"][0]["categories"][0]
    assert group["scenarios"] == 10
    assert group["repeat_spread"] == 0
    assert group["spread"] == 20


def test_original_single_scenario_protocol_retains_its_cases(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    original = copy.deepcopy(studio_engine.settings_file())
    original.pop("scenario_sets")
    original.pop("scenario_file")
    original["default_repeats"] = 1
    monkeypatch.setattr(studio_engine, "settings_file", lambda: original)
    rows = studio_engine.cases(config())
    assert len(rows) == 16
    assert all(r["base_case_id"] == r["category"] for r in rows)
