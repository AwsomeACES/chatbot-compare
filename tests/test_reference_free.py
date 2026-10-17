import asyncio

from fastapi.testclient import TestClient

from app.blackbox import easy_setup, runner
from app.blackbox.catalog import build_cases
from app.blackbox.readiness import preview
from app.blackbox.schema import Settings, Target
from app.blackbox_app import app


def config(**kw):
    return Settings(
        targets=[Target(url="http://unknown.example/chat")],
        categories=["hallucination", "bias", "guardrails", "injection"],
        consent=True,
        judge_consent=True,
        judge_model="fixture",
        **kw,
    )


def test_unknown_defaults_ready_without_reference_facts():
    cfg = config()
    p = preview(cfg)
    assert p["excluded_categories"] == [] and len(p["runnable_categories"]) == 4
    cases = [c for c in build_cases(cfg) if c["category"] == "hallucination"]
    assert len(cases) == 10 and all(not c["prerequisite"] for c in cases)
    assert len({c["turns"][0] for c in cases}) == 10
    assert all(c["reference"]["probe_type"] == "reference_free_uncertainty" for c in cases)
    assert all("global nonexistence is not asserted" in c["reference"]["limitation"] for c in cases)


def test_grounded_references_take_priority_and_empty_references_do_not():
    cfg = config(references=[{"prompt": "Price?", "reference": {"price": 42}}])
    assert build_cases(cfg)[0]["reference"] == cfg.references[0]
    cfg.references = [{}]
    assert build_cases(cfg)[0]["reference"]["probe_type"] == "reference_free_uncertainty"


def test_preview_returns_missing_requirements_without_network(monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError("Preview must not connect")

    monkeypatch.setattr(easy_setup, "Connector", no_network)
    cfg = config()
    cfg.categories = ["hallucination", "scope", "functional", "performance"]
    cfg.scope = "  "
    with TestClient(app) as client:
        response = client.post(
            "/api/blackbox/preview",
            headers={"X-Studio-Request": "1"},
            json=cfg.model_dump(mode="json"),
        )
    assert response.status_code == 200
    p = response.json()
    assert p["runnable_categories"] == ["hallucination"]
    assert p["excluded_categories"] == ["scope", "functional", "performance"]
    assert all(r["reasons"] for r in p["categories"] if not r["ready"])


def test_no_judge_is_not_ready(monkeypatch):
    monkeypatch.setattr(easy_setup, "judge_defaults", lambda: {"model": ""})
    cfg = config()
    cfg.judge_model = ""
    cfg.judge_consent = False
    assert preview(cfg)["runnable_categories"] == []


def test_unknown_hallucination_executes_all_10_with_fixture_judge(monkeypatch):
    cfg = config()
    cfg.categories = ["hallucination"]
    seen = []

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            seen.append(case["id"])
            return {
                "transcript": [
                    {
                        "input": case["turns"][0],
                        "output": "I cannot verify this identifier. Please provide a source.",
                        "seconds": 0.1,
                    }
                ]
            }

    async def fixture_judge(config, case, observation):
        assert case["reference"]["probe_type"] == "reference_free_uncertainty"
        return {
            "score": 100,
            "reason": "Synthetic test judge: uncertainty acknowledged.",
            "estimated": True,
            "evidence": ["I cannot verify this identifier."],
        }

    async def no_sleep(*a):
        pass

    monkeypatch.setattr(runner, "evaluate", fixture_judge)
    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    run = asyncio.run(runner.execute(runner.make_run(cfg), cfg, Bot))
    assert len(seen) == 10 and run["summary"][0]["coverage"] == 100
    assert run["summary"][0]["score"] == 100


def test_prepare_drops_unavailable_categories(monkeypatch):
    class Bot:
        def __init__(self, *a):
            self.kind = "rest"

        async def detect(self):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(easy_setup, "Connector", Bot)
    cfg = config()
    cfg.categories = ["hallucination", "scope", "functional"]
    prepared, notes = asyncio.run(easy_setup.prepare(cfg))
    assert prepared.categories == ["hallucination"]
    assert sum("Excluded before execution" in n for n in notes) == 2
    assert len(runner.make_run(prepared)["cases"]) == 10
