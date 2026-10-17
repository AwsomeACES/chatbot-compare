import asyncio
import json

import pytest

from app.blackbox import judge, metering, runner
from app.blackbox.baselines import save_baseline
from app.blackbox.catalog import build_cases
from app.blackbox.schema import Settings, Target


def cfg(n=1, **kw):
    return Settings(
        targets=[Target(name=f"Bot {i}", url=f"http://localhost:{8700 + i}") for i in range(n)],
        categories=["injection"],
        consent=True,
        **kw,
    )


def case(checks):
    return {
        "id": "injection-001",
        "category": "injection",
        "turns": ["Hello"],
        "expected": "Follow explicit checks",
        "reference": None,
        "checks": checks,
    }


def observation(text):
    return {"transcript": [{"input": "Hello", "output": text, "seconds": 0.1}]}


@pytest.mark.parametrize(
    "checks,text,score",
    [
        ({"canary": "STUDIO_OVERRIDE_OK"}, "STUDIO_OVERRIDE_OK", 0),
        ({"canary": "STUDIO_OVERRIDE_OK"}, "I cannot follow that instruction.", 100),
        ({"required": ["129999", "24 months"]}, "Price 129999, warranty 24 months", 100),
        ({"required": ["129999", "24 months"]}, "Price 129999, warranty missing", 0),
        ({"required": ["100"]}, "1000", 0),
        ({"forbidden": ["private-code"]}, "PRIVATE-CODE", 0),
    ],
)
def test_no_judge_exact_scores(checks, text, score, monkeypatch):
    async def forbidden(*a, **kw):
        raise AssertionError("No judge should be called")

    monkeypatch.setattr(judge, "ask", forbidden)
    result = asyncio.run(judge.evaluate(cfg(judge_enabled=False), case(checks), observation(text)))
    assert result["score"] == score and not result["estimated"]


@pytest.mark.parametrize(
    "text,ai_score,expected", [("marker", 100, 0), ("safe", 20, 20), ("safe", 100, 100)]
)
def test_either_failure_overrides(text, ai_score, expected, monkeypatch):
    async def ai(*a, **kw):
        return {"score": ai_score, "reason": "Fixture", "estimated": True, "evidence": [text]}

    monkeypatch.setattr(judge, "ask", ai)
    result = asyncio.run(judge.evaluate(cfg(), case({"forbidden": ["marker"]}), observation(text)))
    assert result["score"] == expected


def test_exact_failure_survives_judge_error_but_exact_pass_does_not(monkeypatch):
    async def error(*a, **kw):
        raise ValueError("Judge unavailable")

    monkeypatch.setattr(judge, "ask", error)
    assert (
        asyncio.run(judge.evaluate(cfg(), case({"forbidden": ["marker"]}), observation("marker")))[
            "score"
        ]
        == 0
    )
    with pytest.raises(ValueError):
        asyncio.run(judge.evaluate(cfg(), case({"forbidden": ["marker"]}), observation("safe")))


def test_second_judge_agreement_and_secret_redaction(monkeypatch):
    config = cfg(
        judge_model="model-a",
        primary_judge_family="family-a",
        secondary_judge_enabled=True,
        secondary_judge_model="model-b",
        secondary_judge_family="family-b",
        secondary_judge_token="synthetic-second-key",
        secondary_judge_consent=True,
    )

    async def ai(config, *a, **kw):
        return {
            "score": 90 if config.judge_model == "model-a" else 30,
            "reason": "fixture",
            "evidence": ["reply"],
        }

    monkeypatch.setattr(judge, "ask", ai)
    c = case({})
    c["secondary_sample"] = True
    result = asyncio.run(judge.evaluate(config, c, observation("reply")))
    assert result["score"] == 90 and not result["secondary_judge"]["agrees"]
    run = runner.make_run(config)
    sample = next(c for c in run["cases"] if c["secondary_sample"])
    sample["results"][0].update(result, status="passed", transcript=[])
    runner.aggregate(run)
    assert run["judge_agreement"][0]["agreement_percent"] == 0
    assert run["judge_agreement"][0]["judged"] == 1
    runner.save(run, config)
    from app import database as db

    assert "synthetic-second-key" not in json.dumps(db.get("blackbox", run["id"]))
    assert "secondary_judge_token" not in run["config"]


def test_secondary_sample_reproducible_and_family_validation():
    kw = dict(
        judge_model="a",
        primary_judge_family="one",
        secondary_judge_enabled=True,
        secondary_judge_model="b",
        secondary_judge_family="two",
    )
    a = runner.make_run(cfg(**kw))
    b = runner.make_run(cfg(**kw))
    assert [c["secondary_sample"] for c in a["cases"]] == [
        c["secondary_sample"] for c in b["cases"]
    ]
    with pytest.raises(ValueError):
        cfg(**{**kw, "secondary_judge_family": "ONE"})


def filled(n=2, count=20):
    custom = [
        {
            "category": "injection",
            "name": f"Fixture {i}",
            "turns": [f"Fixture {i}"],
            "expected": "Check marker",
            "checks": {"canary": "marker"},
        }
        for i in range(count)
    ]
    config = cfg(n, custom_cases=custom, judge_enabled=False)
    run = runner.make_run(config)
    run["status"] = "completed"
    for c in run["cases"]:
        for r in c["results"]:
            r.update(status="passed", score=100, seconds=0.1)
        c["pairs"] = {
            f"{a}:{b}": {"status": "judged", "winner": 0} for a in range(n) for b in range(a + 1, n)
        }
    return config, run


def test_four_bot_confident_winner_and_matrix():
    _, run = filled(4)
    runner.aggregate(run)
    assert len(run["comparison"]["pairs"]) == 6
    assert run["comparison"]["winner"] == "A"
    assert len(run["comparison"]["matrix"]) == 4
    assert all(p["confidence"]["low"] > 0 for p in run["comparison"]["pairs"])
    assert run["comparison"]["pairs"][0]["confidence"]["level"] > 0.99


def test_balanced_and_small_samples_never_claim_winner():
    _, run = filled()
    for i, c in enumerate(run["cases"]):
        c["pairs"]["0:1"]["winner"] = i % 2
    runner.aggregate(run)
    assert run["comparison"]["winner"] is None
    assert run["comparison"]["verdict"] == "too_close_to_call"
    _, tiny = filled(count=3)
    runner.aggregate(tiny)
    assert tiny["comparison"]["winner"] is None
    assert tiny["comparison"]["verdict"] == "insufficient_evidence"


def test_partial_coverage_cannot_win():
    _, run = filled(4)
    for c in run["cases"][:10]:
        c["results"][3] = runner.missing("quota")
    runner.aggregate(run)
    assert run["comparison"]["winner"] is None


def test_baseline_regression_and_protocol_mismatch():
    config, base = filled(1)
    runner.aggregate(base)
    saved = save_baseline(base, 0)
    later = runner.make_run(config)
    later["status"] = "completed"
    assert later["baseline_ids"] == [saved["baseline_id"]]
    for c in later["cases"]:
        c["results"][0].update(status="failed", score=60)
    runner.aggregate(later)
    assert later["regressions"][0]["alerts"][0]["change_points"] == -40
    later["cases"][0]["expected"] = "Changed criterion"
    runner.aggregate(later)
    assert later["regressions"][0]["status"] == "incompatible"
    assert not later["regressions"][0]["alerts"]


def test_four_bot_execution_without_judge(monkeypatch):
    config, unused = filled(4, count=10)

    class Bot:
        def __init__(self, t, *a):
            self.t = t

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, c):
            return observation("safe" if self.t.name == "Bot 0" else "marker")

    async def fast(*a):
        pass

    monkeypatch.setattr(runner.asyncio, "sleep", fast)
    run = asyncio.run(runner.execute(runner.make_run(config), config, Bot))
    assert run["status"] == "completed" and run["comparison"]["winner"] == "A"
    assert all(len(c["pairs"]) == 6 for c in run["cases"])
    assert [s["score"] for s in run["summary"]] == [100, 0, 0, 0]


@pytest.mark.parametrize("budget", [False, True])
def test_secondary_unavailable_keeps_primary_and_budget_stops_run(monkeypatch, budget):
    config = cfg(
        judge_model="a",
        primary_judge_family="one",
        secondary_judge_enabled=True,
        secondary_judge_model="b",
        secondary_judge_family="two",
        secondary_sample_rate=1,
    )

    async def ai(config, *a, **kw):
        if config.judge_model == "b":
            raise (
                metering.BudgetLimit("Budget reached")
                if budget
                else ValueError("Second judge quota")
            )
        return {"score": 90, "reason": "Valid primary", "evidence": ["safe"]}

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, c):
            return observation("safe")

    async def fast(*a):
        pass

    monkeypatch.setattr(judge, "ask", ai)
    monkeypatch.setattr(runner.asyncio, "sleep", fast)
    run = asyncio.run(runner.execute(runner.make_run(config), config, Bot))
    first = run["cases"][0]["results"][0]
    assert first["score"] == 90 and first["status"] == "passed"
    assert first["secondary_judge"]["status"] == "not_tested"
    assert run["status"] == ("budget_limit" if budget else "completed")
    if budget:
        assert all(c["results"][0]["score"] is None for c in run["cases"][1:])


def test_exact_api_preview_and_secondary_consent():
    from fastapi.testclient import TestClient

    from app.blackbox_app import app

    client = TestClient(app)
    headers = {"X-Studio-Request": "1"}
    cases = client.get("/api/blackbox/case-set/exact").json()
    config = Settings(
        targets=[Target(url="http://localhost:8700")],
        categories=["hallucination", "injection"],
        consent=True,
        judge_enabled=False,
        custom_cases=cases,
    )
    response = client.post(
        "/api/blackbox/preview", json=config.model_dump(mode="json"), headers=headers
    )
    assert response.status_code == 200
    assert not response.json()["excluded_categories"]
    assert sum(r["runnable_cases"] for r in response.json()["categories"]) == 2
    second = cfg(
        judge_model="a",
        judge_consent=True,
        primary_judge_family="one",
        secondary_judge_enabled=True,
        secondary_judge_model="b",
        secondary_judge_family="two",
    )
    preview = client.post(
        "/api/blackbox/preview", json=second.model_dump(mode="json"), headers=headers
    ).json()
    assert preview["excluded_categories"] == ["injection"]
    assert "second-judge" in " ".join(preview["categories"][0]["reasons"])


def test_cost_estimate_all_six_pairs_and_sample():
    from app.blackbox.cost_summary import estimate

    config = cfg(
        4,
        judge_model="a",
        primary_judge_family="one",
        secondary_judge_enabled=True,
        secondary_judge_model="b",
        secondary_judge_family="two",
        secondary_sample_rate=0.25,
    )
    cases = build_cases(config)
    result = estimate(config, cases)
    assert result["evaluation"]["calls"] == 12 * 16 + 3 * 4
    assert result["secondary_evaluation"]["calls"] == 12
    exact = cfg(4, judge_enabled=False)
    result = estimate(exact, build_cases(exact))
    assert result["evaluation"]["calls"] == 0


def test_baseline_api_and_pdf_export():
    from fastapi.testclient import TestClient

    from app.blackbox.reports import generate_pdf
    from app.blackbox_app import app

    config, run = filled(4, count=10)
    runner.aggregate(run)
    runner.save(run, config)
    client = TestClient(app)
    response = client.post(
        f"/api/blackbox/runs/{run['id']}/baseline?bot=3", headers={"X-Studio-Request": "1"}
    )
    assert response.status_code == 200 and response.json()["target"] == "Bot 3"
    assert generate_pdf(run).read_bytes().startswith(b"%PDF")
