"""Offline comparison regressions: independent scenarios, paired panels and saved policy."""

import copy

import pytest
from pydantic import ValidationError

from app.blackbox.comparison_quality import ComparisonPolicy, _interval, measured
from app.blackbox.studio_engine import summarize


def completed_run(scores=(90, 50), scenarios=5, repeats=3):
    categories = ("memory", "injection")
    run = {
        "status": "completed",
        "targets": [{"name": f"Bot {i}"} for i in range(len(scores))],
        "config": {"seed": 17},
        "protocol_snapshot": {
            "cases": [{"category": c, "name": c} for c in categories],
            "weights": {c: 1 for c in categories},
            "tie_margin": 2,
            "comparison": ComparisonPolicy().model_dump(),
        },
        "cases": [],
    }
    for category in categories:
        for scenario in range(scenarios):
            for repeat in range(repeats):
                run["cases"].append(
                    {
                        "id": f"{category}-{scenario}-{repeat}",
                        "base_case_id": f"{category}-{scenario}",
                        "category": category,
                        "repeat": repeat + 1,
                        "completed": True,
                        "results": [
                            {
                                "status": "passed" if score >= 80 else "failed",
                                "score": score,
                                "panel_complete": True,
                                "engine": "multi-model-rubric-panel",
                                "judges": [{"model": "fixture-judge"}],
                            }
                            for score in scores
                        ],
                    }
                )
    return run


def result(run):
    summarize(run)
    return run["studio"]["comparison"]


def test_clear_winner_and_all_pair_correction_for_four_bots():
    data = result(completed_run((95, 70, 55, 40)))
    assert data["winner"] == 0
    assert data["family_pair_count"] == len(data["pairs"]) == 6
    assert all(p["scenarios"] == 10 for p in data["pairs"])
    assert data["pairs"][0]["low"] == data["pairs"][0]["high"] == 25


def test_repeating_same_scenarios_does_not_inflate_sample_or_change_interval():
    once = completed_run(repeats=1)
    repeated = completed_run(repeats=40)
    for run in (once, repeated):
        for case in run["cases"]:
            scenario = int(case["base_case_id"].rsplit("-", 1)[1])
            case["results"][0]["score"] = 70 + 5 * scenario
    a, b = result(once)["pairs"][0], result(repeated)["pairs"][0]
    assert a["scenarios"] == b["scenarios"] == 10
    assert (a["low"], a["high"], a["difference"]) == (b["low"], b["high"], b["difference"])


def test_repeats_cannot_make_a_single_scenario_per_category_rankable():
    data = result(completed_run(scenarios=1, repeats=100))
    assert data["winner"] is None
    assert data["pairs"][0]["scenarios"] == 2
    assert data["pairs"][0]["low"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"status": "not_tested", "score": None},
        {"panel_complete": False},
        {"needs_review": True},
        {"judges": [{"model": "different-judge"}]},
    ],
)
def test_missing_review_or_different_panels_withhold_winner(change):
    run = completed_run()
    run["cases"][0]["results"][0].update(change)
    data = result(run)
    assert data["winner"] is None
    assert data["pairs"][0]["low"] is None
    assert data["category_results"]["memory"]["leaders"] == []


def test_snapshot_margin_and_weights_determine_decision():
    run = completed_run((90, 80))
    run["protocol_snapshot"]["tie_margin"] = 11
    data = result(run)
    assert data["winner"] is None
    assert data["category_results"]["memory"]["leaders"] == [0, 1]
    run["protocol_snapshot"]["tie_margin"] = 2
    run["config"]["category_weights"] = {"memory": 3, "injection": 1}
    for case in run["cases"]:
        if case["category"] == "injection":
            case["results"][0]["score"] = 70
    data = result(run)
    assert data["winner"] == 0
    assert data["pairs"][0]["difference"] == data["pairs"][0]["low"] == 5


def test_interval_must_exceed_tie_margin_not_just_zero():
    data = result(completed_run((81, 80)))
    assert data["pairs"][0]["low"] == 1
    assert data["winner"] is None


def test_running_or_cancelled_results_cannot_declare_a_winner():
    for status in ("queued", "running", "stopped", "error"):
        run = completed_run()
        run["status"] = status
        data = result(run)
        assert data["winner"] is None
        assert not data["readiness"][0]["meets_checks"]


def test_derived_scores_do_not_add_independent_samples():
    run = completed_run()
    derived = copy.deepcopy(run["cases"][0])
    derived.update(id="derived", base_case_id="derived", derived=True)
    run["cases"].append(derived)
    data = result(run)
    assert data["pairs"][0]["scenarios"] == 10
    assert run["studio"]["bots"][0]["categories"][0]["scenarios"] == 5


def test_readiness_requires_every_category_threshold_and_no_review():
    run = completed_run((90, 70))
    data = result(run)
    assert data["readiness"][0]["meets_checks"]
    assert not data["readiness"][1]["meets_checks"]
    run["cases"][0]["results"][0]["needs_review"] = True
    assert result(run)["readiness"][0]["review_count"] == 1


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 101, True, "90", None])
def test_invalid_scores_never_count_as_evidence(score):
    assert not measured({"status": "passed", "score": score})
    run = completed_run()
    run["cases"][0]["results"][0]["score"] = score
    assert result(run)["winner"] is None


def test_all_pair_adjustment_widens_interval_and_cache_is_parameter_sensitive():
    groups = ((-30.0, -10.0, 2.0, 18.0, 40.0),) * 2
    single = _interval(groups, (1, 1), 17, 2000, 0.95, 1)
    multiple = _interval(groups, (1, 1), 17, 2000, 0.95, 6)
    assert multiple[0] <= single[0] and multiple[1] >= single[1]
    assert _interval(groups, (1, 1), 17, 2000, 0.95, 6) == multiple


def test_policy_rejects_invalid_or_unbounded_parameters():
    for values in (
        {"resamples": 1},
        {"resamples": 1000000},
        {"confidence": 1},
        {"method": "invented"},
        {"min_scenarios_per_category": 1},
    ):
        with pytest.raises(ValidationError):
            ComparisonPolicy.model_validate(values)


def test_pdf_uses_same_comparison_decision_and_review_checks(monkeypatch):
    from app.blackbox import reports
    from app.blackbox.runner import aggregate, make_run
    from app.blackbox.schema import Settings, Target

    cfg = Settings(
        simple_mode=True,
        targets=[
            Target(name="First", url="http://localhost/a"),
            Target(name="Second", url="http://localhost/b"),
        ],
    )
    run = make_run(cfg)
    run["status"] = "completed"
    aggregate(run)
    run["comparison"] = {"winner": "INCORRECT_LEGACY_WINNER", "reason": "Old method", "pairs": []}
    captured = []
    monkeypatch.setattr(
        reports.SimpleDocTemplate,
        "build",
        lambda self, story, **kwargs: captured.extend(
            p.getPlainText() for p in story if hasattr(p, "getPlainText")
        ),
    )
    reports.generate_pdf(run)
    text = "\n".join(captured)
    assert "Winner withheld" in text
    assert "Comparison evidence and review checks" in text
    assert "Interval unavailable" in text
    assert "First: Review required" in text
    assert "INCORRECT_LEGACY_WINNER" not in text
