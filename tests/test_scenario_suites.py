"""Selectable scenario suites (Phase H): more coverage without inflated confidence.

The suite is additive. The screening default must stay small and unchanged, the extended suite
must be reachable and versioned, Bias must keep its nine subtypes, and nothing here may turn
repeats or paraphrases into independent coverage.
"""

import json

import pytest

from app.blackbox import studio_engine
from app.blackbox.schema import JudgeSelection, Settings, Target

EXTENDED = "extended"


def config(suite: str = "", **kwargs):
    return Settings(
        targets=[Target(url="http://localhost:8000/chat")],
        simple_mode=True,
        judges=[JudgeSelection(model="fixture", local=True)],
        consent=True,
        judge_consent=True,
        scenario_suite=suite,
        **kwargs,
    )


def distinct(rows) -> set[str]:
    return {row["base_case_id"] for row in rows}


# --- the default stays light ------------------------------------------------------------------


def test_the_default_suite_is_unchanged_and_lightweight():
    protocol = studio_engine.settings_file()
    assert protocol["scenario_suite"] == "screening"
    assert protocol["protocol_version"] == "ten-categories-bias-nine-v5", (
        "selecting nothing must not change the saved protocol version"
    )
    rows = studio_engine.cases(config())
    assert len(distinct(rows)) == 18, "screening keeps one scenario per Category plus Bias"
    assert len({row["category"] for row in rows}) == 10


def test_an_unknown_suite_is_refused_rather_than_silently_ignored():
    with pytest.raises(ValueError, match="Unknown scenario suite"):
        studio_engine.settings_file("does-not-exist")


# --- the extended suite is selectable and versioned -------------------------------------------


def test_the_extended_suite_is_selectable_and_changes_the_protocol_version():
    protocol = studio_engine.settings_file(EXTENDED)
    assert protocol["scenario_suite"] == EXTENDED
    assert protocol["scenario_suite_version"] == "extended-v1"
    assert protocol["protocol_version"].endswith("+extended-v1"), (
        "a saved Run must record which suite produced it"
    )
    assert protocol["protocol_version"] != "ten-categories-bias-nine-v5"


def test_the_extended_suite_plans_ten_distinct_scenarios_for_each_of_nine_categories():
    rows = studio_engine.cases(config(EXTENDED))
    per_category: dict[str, set[str]] = {}
    for row in rows:
        per_category.setdefault(row["category"], set()).add(row["base_case_id"])
    for category, scenarios in per_category.items():
        expected = 9 if category == "bias" else 10
        assert len(scenarios) == expected, f"{category} has {len(scenarios)} distinct scenarios"
    assert len(distinct(rows)) == 99


def test_repeats_are_identifiable_and_never_counted_as_distinct_scenarios():
    rows = studio_engine.cases(config(EXTENDED, repeat_counts={"injection": 4}))
    injection = [row for row in rows if row["category"] == "injection"]
    assert len(injection) == 40, "ten scenarios times four repeats"
    assert len({row["base_case_id"] for row in injection}) == 10, (
        "repeats must not raise the distinct-scenario count"
    )
    assert len({row["id"] for row in injection}) == 40, "every repeat stays separately identifiable"
    assert sorted({row["repeat"] for row in injection}) == [1, 2, 3, 4]


# --- Bias is untouched -------------------------------------------------------------------------


def test_the_extended_suite_does_not_replace_the_nine_bias_subtypes():
    rows = [row for row in studio_engine.cases(config(EXTENDED)) if row["category"] == "bias"]
    subtypes = {row["bias_subtype"] for row in rows}
    assert subtypes == {
        "gender",
        "racial_ethnic",
        "age",
        "socioeconomic",
        "cultural",
        "cognitive",
        "media",
        "selection",
        "algorithmic",
    }


def test_the_derived_bias_aggregate_is_not_an_independent_observation():
    rows = [row for row in studio_engine.cases(config(EXTENDED)) if row["category"] == "bias"]
    derived = [row for row in rows if row["bias_subtype"] == "algorithmic"]
    assert derived, "the aggregate subtype is still present"
    assert all(row["derived"] for row in derived), (
        "the aggregate must stay marked derived so it is never counted as a fresh sample"
    )
    assert not any(row["derived"] for row in rows if row["bias_subtype"] != "algorithmic")


# --- content quality ---------------------------------------------------------------------------


def document() -> dict:
    return studio_engine.scenario_document("scenarios-extended-v1.json")


def test_no_two_extended_scenarios_share_a_prompt():
    """A paraphrase or a duplicated prompt is not independent coverage."""
    seen: dict[tuple[str, ...], str] = {}
    for category, rows in document()["sets"].items():
        for row in rows:
            key = tuple(turn.strip().casefold() for turn in row["turns"])
            assert key not in seen, (
                f"{category}/{row['scenario_id']} repeats the prompt of {seen.get(key)}"
            )
            seen[key] = f"{category}/{row['scenario_id']}"


def test_every_extended_scenario_has_a_distinct_identifier_and_expected_behaviour():
    identifiers = []
    for rows in document()["sets"].values():
        for row in rows:
            identifiers.append(row["scenario_id"])
            assert row["expected"].strip(), f"{row['scenario_id']} has no expected behaviour"
            assert row["turns"] and all(t.strip() for t in row["turns"])
    assert len(identifiers) == len(set(identifiers)) == 90


def test_the_extended_suite_covers_multi_turn_ambiguous_benign_and_adversarial_cases():
    intents = {row["intent"] for rows in document()["sets"].values() for row in rows}
    assert any("adversarial" in intent for intent in intents)
    assert "ambiguous" in intents
    assert any(intent.startswith("benign") for intent in intents)
    multi_turn = [
        row for rows in document()["sets"].values() for row in rows if len(row["turns"]) > 1
    ]
    assert len(multi_turn) >= 20, "multi-turn behaviour needs real multi-turn scenarios"


def test_factual_scenarios_supply_reference_facts_with_their_scope():
    for row in document()["sets"]["hallucination"]:
        reference = row.get("reference")
        assert reference, f"{row['scenario_id']} needs reference facts for factual scoring"
        assert reference["facts"], "reference facts cannot be empty"
        assert "not proof that the identifier does not exist" in reference["scope"], (
            "a reference set must state that absence from it is not global nonexistence"
        )


def test_reference_facts_reach_the_planned_case():
    rows = studio_engine.cases(config(EXTENDED))
    factual = [row for row in rows if row["category"] == "hallucination"]
    assert factual
    assert all(row["reference"] for row in factual)
    assert all("supplied reference facts" in row["expected"] for row in factual)


def test_authored_scenarios_are_distinguished_from_independently_reviewed_ones():
    review = document()["review"]
    assert review["status"] == "authored"
    assert review["independently_reviewed"] is False
    assert not review["reviewer"]
    assert "not been reviewed by a second person" in review["note"]
    rows = studio_engine.cases(config(EXTENDED))
    authored = [row for row in rows if row["category"] != "bias"]
    assert authored and all(row["review_status"] == "authored" for row in authored), (
        "every planned Case must carry its review status"
    )


def test_the_extended_suite_states_its_limitations():
    limitations = " ".join(document()["limitations"])
    assert "not independently reviewed" in limitations
    assert "does not transfer" in limitations
    assert "do not establish that a bot is safe" in limitations


# --- reporting ---------------------------------------------------------------------------------


def test_suite_summaries_report_size_review_status_and_version():
    summaries = studio_engine.suite_summaries()
    assert set(summaries) == {"screening", EXTENDED}
    assert summaries["screening"]["distinct_scenarios"] == 18
    assert summaries[EXTENDED]["distinct_scenarios"] == 99
    assert summaries[EXTENDED]["protocol_version"].endswith("+extended-v1")
    for row in summaries.values():
        assert row["review"]["independently_reviewed"] is False
        assert row["label"] and row["version"]
    counts = summaries[EXTENDED]["scenarios_per_category"]
    assert counts["injection"] == 10 and counts["bias"] == 9


def test_the_coverage_block_counts_only_distinct_scenarios():
    coverage = document()["coverage"]
    assert coverage["distinct_scenarios"] == 90
    assert sum(coverage["scenarios_per_category"].values()) == 90
    assert "bias" in coverage["excluded_categories"]
    assert "not independent coverage" in coverage["note"]


# --- scoring compatibility ---------------------------------------------------------------------


def test_the_extended_suite_satisfies_the_comparison_minimum_scenario_rule():
    """The screening suite withholds an inferential winner; the extended suite can qualify."""
    protocol = studio_engine.settings_file(EXTENDED)
    policy = protocol["comparison"]
    rows = studio_engine.cases(config(EXTENDED))
    per_category: dict[str, set[str]] = {}
    for row in rows:
        if not row.get("derived"):
            per_category.setdefault(row["category"], set()).add(row["base_case_id"])
    assert len(distinct(rows)) >= policy["min_scenarios"]
    short = {
        category: len(scenarios)
        for category, scenarios in per_category.items()
        if len(scenarios) < policy["min_scenarios_per_category"]
    }
    assert not short, f"these Categories cannot support a category comparison: {short}"


def test_saved_protocol_snapshots_are_preserved_per_run():
    from app.blackbox.runner import make_run

    screening = make_run(config())
    extended = make_run(config(EXTENDED))
    assert screening["protocol_snapshot"]["protocol_version"] == "ten-categories-bias-nine-v5"
    assert extended["protocol_snapshot"]["protocol_version"].endswith("+extended-v1")
    assert len(extended["cases"]) > len(screening["cases"])
    # Each Run keeps its own snapshot, so an older report is still read on its own terms.
    assert screening["protocol_snapshot"] != extended["protocol_snapshot"]


def test_a_scenario_file_outside_the_studio_directory_is_refused():
    with pytest.raises(ValueError, match="stay inside app/studio"):
        studio_engine.scenario_document("../../settings.json")


def test_the_declared_suites_and_the_shipped_file_agree():
    from app.config import ROOT

    settings = json.loads((ROOT / "app/studio/settings.json").read_text(encoding="utf-8"))
    declared = settings["scenario_suites"][EXTENDED]
    shipped = json.loads(
        (ROOT / "app/studio" / declared["scenario_file"]).read_text(encoding="utf-8")
    )
    assert declared["version"] == shipped["version"]
    assert settings["default_scenario_suite"] == "screening", (
        "the light screening suite must remain the default"
    )
