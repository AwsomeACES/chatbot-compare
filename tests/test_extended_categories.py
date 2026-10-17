"""Verify category visibility, paired design and immutable historical protocols."""

import copy

from legacy_protocol import snapshot

from app.blackbox import studio_engine
from app.blackbox.catalog import build_cases
from app.blackbox.runner import aggregate, make_run
from app.blackbox.schema import ImportedCase, Settings, Target
from app.blackbox.studio_routes import prepare

NEW = {
    "hallucination_relevant",
    "hallucination_irrelevant",
    "bias_religion",
    "bias_caste",
    "bias_sex",
    "bias_colour",
}


def config(**kwargs):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        judges=[{"model": "local-fixture", "local": True}],
        consent=True,
        judge_consent=True,
        **kwargs,
    )


def test_new_checks_are_visible_valid_and_have_independent_repeat_counts(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    protocol = studio_engine.settings_file()
    assert len(protocol["cases"]) == 16
    assert NEW <= {c["category"] for c in protocol["cases"]}
    rows = studio_engine.cases(config(repeat_counts={"bias_religion": 1}))
    assert len(rows) == 760
    assert sum(r["category"] == "bias_religion" for r in rows) == 10
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["source"] == protocol["protocol_version"] for r in rows)
    for row in protocol["cases"]:
        ImportedCase.model_validate(row)


def test_demographic_pairs_change_only_attribute_and_use_same_request(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    rows = {r["category"]: r for r in studio_engine.settings_file()["cases"]}
    for category in ("bias_religion", "bias_caste", "bias_sex", "bias_colour"):
        row = rows[category]
        assert row["parallel"] and len(row["turns"]) == 2
        a, b = row["turns"]
        assert a.split(".", 1)[1] == b.split(".", 1)[1]
        assert a.split(".", 1)[0] != b.split(".", 1)[0]
        assert "BOTH" in row["expected"]
        assert "Different wording alone is not bias" in row["expected"]


def test_relevant_factuality_uses_reference_and_relevance_rubric(monkeypatch):
    monkeypatch.setattr(studio_engine, "settings_file", snapshot)
    rows = studio_engine.cases(
        config(references=[{"prompt": "What is the price?", "reference": {"price": 100}}])
    )
    row = next(r for r in rows if r["category"] == "hallucination_relevant")
    assert row["reference"] == {"price": 100}
    assert row["turns"][0].startswith("What is the price?")
    assert "relevance" in row["expected"].lower()


def test_legacy_catalog_can_execute_added_categories_without_padding():
    cfg = Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        categories=sorted(NEW),
        judge_model="fixture",
    )
    rows = build_cases(cfg)
    assert {r["category"] for r in rows} == NEW
    assert len(rows) == 6
    assert all(r["source"] == "authored" for r in rows)


def test_saved_ten_case_summary_and_resume_keep_original_protocol(monkeypatch):
    monkeypatch.setattr("app.blackbox.runner.summarize", lambda run: {})
    original = copy.deepcopy(studio_engine.settings_file())
    original["cases"] = [c for c in original["cases"] if c["category"] not in NEW]
    original["weights"] = {c["category"]: 1 for c in original["cases"]}
    original["protocol_version"] = "simple-ten-v1"
    cfg = config()
    run = make_run(cfg)
    run["cases"] = [c for c in run["cases"] if c["category"] not in NEW]
    run["protocol_snapshot"] = original
    run["categories"] = [c["category"] for c in original["cases"]]
    run["config"]["categories"] = run["categories"]
    run["config"]["category_weights"] = original["weights"]
    for case in run["cases"]:
        case["results"][0].update(status="passed", score=90)
    aggregate(run)
    assert run["studio"]["bots"][0]["score"] == 90
    assert len(run["studio"]["bots"][0]["categories"]) == 10
    cfg = prepare(cfg, original)
    assert cfg.categories == run["categories"]
    assert not NEW.intersection(cfg.categories)
