import asyncio

import pytest

from app.blackbox import judge, runner
from app.blackbox.schema import Settings, Target


def make(compare=False, **kw):
    targets = [Target(name="A", url="http://localhost:8765/chat")]
    if compare:
        targets.append(Target(name="B", url="http://localhost:8766/chat"))
    cfg = Settings(
        targets=targets,
        categories=["bias"],
        consent=True,
        custom_cases=[
            {
                "category": "bias",
                "name": f"Fixture {i}",
                "turns": [f"Fixture question {i}"],
                "expected": "Synthetic fixture only.",
            }
            for i in range(30)
        ],
        **kw,
    )
    return cfg, runner.make_run(cfg)


def mark(run, start, end, slot=0, score=90):
    for case in run["cases"][start:end]:
        case["results"][slot].update(status="passed" if score >= 80 else "failed", score=score)


def test_missing_excluded_but_actual_zero_included():
    _, run = make()
    mark(run, 0, 1, score=100)
    mark(run, 1, 2, score=0)
    runner.aggregate(run)
    s = run["summary"][0]
    assert s["score"] == 50 and s["coverage"] == 6.67 and not s["rankable"]
    assert s["categories"][0]["failed"] == 1 and s["categories"][0]["not_tested"] == 28
    assert run["cases"][2]["results"][0]["score"] is None


def test_threshold_boundary_and_per_category_gate():
    _, run = make()
    mark(run, 0, 23)
    runner.aggregate(run)
    assert not run["summary"][0]["rankable"]
    mark(run, 23, 24)
    runner.aggregate(run)
    assert run["summary"][0]["rankable"]
    assert run["summary"][0]["coverage"] == 80
    run["categories"].append("language")
    run["cases"].append(dict(id="extra", category="language", results=[runner.missing("No judge")]))
    runner.aggregate(run)
    assert not run["summary"][0]["rankable"]


def test_comparison_uses_only_shared_valid_cases():
    _, run = make(True)
    run["status"] = "completed"
    mark(run, 0, 24, 0, 90)
    mark(run, 0, 30, 1, 70)
    for case in run["cases"]:
        case["pair"] = {"status": "judged", "winner": 0}  # stale pair on missing A must be ignored
    runner.aggregate(run)
    c = run["comparison"]
    row = c["categories"][0]
    assert c["winner"] == "A" and c["coverage"] == 80
    assert row["a_wins"] == 24 and row["not_judged"] == 6
    assert row["a_score"] == 90 and row["b_score"] == 70
    mark(run, 24, 30, 0, 100)
    for case in run["cases"][23:]:
        case["pair"] = {"status": "order_sensitive", "winner": None}
    runner.aggregate(run)
    assert run["comparison"]["winner"] is None


def test_disjoint_completion_does_not_rank():
    _, run = make(True)
    mark(run, 0, 24, 0)
    mark(run, 6, 30, 1)
    for case in run["cases"]:
        case["pair"] = {"status": "judged", "winner": "tie"}
    runner.aggregate(run)
    assert all(s["rankable"] for s in run["summary"])
    assert run["comparison"]["coverage"] == 60
    assert run["comparison"]["winner"] is None


@pytest.mark.parametrize(
    "error", ["HTTP 429 quota exceeded", "request timed out", "Judge returned invalid JSON"]
)
def test_judge_errors_remain_unscored(monkeypatch, error):
    cfg, run = make()

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            return {"transcript": [{"input": "hi", "output": "hello", "seconds": 0.1}]}

    async def fail(*a):
        raise ValueError(error)

    async def no_sleep(*a):
        pass

    monkeypatch.setattr(runner, "evaluate", fail)
    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    asyncio.run(runner.execute(run, cfg, Bot))
    assert run["summary"][0]["score"] is None
    assert run["summary"][0]["categories"][0]["failed"] == 0
    assert all(c["results"][0]["reason"] == error for c in run["cases"])


def test_target_errors_and_circuit_breaker(monkeypatch):
    cfg, run = make()

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            return {
                "error": "HTTP 429 quota",
                "transcript": [{"input": "hi", "error": "HTTP 429 quota", "seconds": 0.1}],
            }

    async def no_sleep(*a):
        pass

    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    asyncio.run(runner.execute(run, cfg, Bot))
    assert run["summary"][0]["score"] is None
    assert run["summary"][0]["errors"] == 3
    assert sum("circuit breaker" in c["results"][0]["reason"] for c in run["cases"]) == 27


def test_performance_quota_is_missing_not_failed_answer():
    cfg, _ = make()
    with pytest.raises(ValueError, match="429"):
        asyncio.run(judge.evaluate(cfg, {"category": "performance"}, {"error": "HTTP 429 quota"}))


def test_legacy_missing_zero_normalized():
    _, run = make()
    run["cases"][0]["results"][0]["score"] = 0
    runner.aggregate(run)
    assert run["cases"][0]["results"][0]["score"] is None
    assert run["summary"][0]["score"] is None
