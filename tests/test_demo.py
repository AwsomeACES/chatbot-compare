"""The no-key synthetic demo (T-047).

A new user must be able to complete a real evaluation with no provider account.
These tests assert the demo bot is deterministic, that its Cases validate
through the ordinary imported-case schema, that the demo both passes and fails
Cases, that scoring works with the AI Judge switched off, and that no provider
call is ever attempted.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.blackbox import demo_bot, runner
from app.blackbox.schema import ImportedCase, Settings, Target
from app.blackbox_app import app

_SPEC = importlib.util.spec_from_file_location(
    "studio_demo_bot", Path(__file__).parents[1] / "scripts" / "demo_bot.py"
)
demo_server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(demo_server)


def client() -> TestClient:
    return TestClient(app)


def bot_client() -> TestClient:
    """A client for the separate demo-bot process's app."""
    return TestClient(demo_server.app)


def test_the_demo_bot_is_deterministic():
    for case in demo_bot.case_set():
        for turn in case["turns"]:
            assert demo_bot.reply(turn) == demo_bot.reply(turn)


def test_the_demo_bot_answers_and_discloses_that_it_is_synthetic():
    response = bot_client().post("/chat", json={"message": "What is the warranty for SD-100?"})
    assert response.status_code == 200
    body = response.json()
    assert "24 months" in body["answer"]
    assert body["demo"] is True
    assert "not a measurement of a real chatbot" in body["disclosure"]


@pytest.mark.parametrize("payload", [{}, {"message": 7}, {"message": "x" * 20001}])
def test_the_demo_bot_validates_its_input(payload):
    assert bot_client().post("/chat", json=payload).status_code == 422


def test_the_demo_bot_only_binds_loopback():
    assert demo_server.main(["--host", "0.0.0.0"]) == 2


def test_the_demo_bot_reports_its_identity():
    body = bot_client().get("/health").json()
    assert body["service"] == "studio-synthetic-demo" and body["demo"] is True


def test_the_demo_case_set_validates_as_imported_cases():
    published = client().get("/api/blackbox/case-set/demo")
    assert published.status_code == 200
    body = published.json()
    assert body["judge_enabled"] is False
    assert "not a measurement of a real chatbot" in body["disclosure"]
    cases = [ImportedCase.model_validate(case) for case in body["cases"]]
    assert len(cases) == len(body["cases"]) >= 6
    # Unique names within a category, which Settings also enforces.
    identities = [(c.category, c.name.casefold()) for c in cases]
    assert len(identities) == len(set(identities))
    # Every Case must be scorable without an AI Judge.
    for case in cases:
        checks = case.checks
        assert checks.required or checks.forbidden or checks.canary


def test_the_published_demo_target_is_the_separate_loopback_process():
    body = client().get("/api/blackbox/case-set/demo").json()
    assert body["target_url"] == demo_bot.DEMO_URL
    assert body["target_url"].startswith("http://127.0.0.1:")
    assert body["response_field"] == "answer"
    assert "scripts/demo_bot.py" in body["start_command"]


def test_the_demo_is_accepted_as_a_settings_payload_without_a_judge():
    config = Settings(
        targets=[Target(name=demo_bot.DEMO_BOT_NAME, url=demo_bot.DEMO_URL)],
        categories=["hallucination"],
        consent=True,
        judge_enabled=False,
        custom_cases=demo_bot.case_set(),
    )
    assert config.judge_enabled is False
    assert len(config.custom_cases) >= 6


def test_the_demo_shows_both_a_pass_and_a_real_failure():
    """A demo where everything passes would misrepresent the tool."""
    outcomes = {}
    for case in demo_bot.case_set():
        answers = [demo_bot.reply(turn) for turn in case["turns"]]
        joined = " ".join(answers).casefold()
        checks = case["checks"]
        met = all(term.casefold() in joined for term in checks.get("required", []))
        met = met and not any(term.casefold() in joined for term in checks.get("forbidden", []))
        canary = checks.get("canary", "")
        met = met and not (canary and canary.casefold() in joined)
        outcomes[case["name"]] = met
    assert any(outcomes.values()), "The demo must contain passing Cases"
    assert not all(outcomes.values()), "The demo must contain a failing Case"
    assert outcomes["Demo: invented refund guarantee (fails on purpose)"] is False
    assert outcomes["Demo: supported warranty lookup"] is True


def test_a_demo_run_scores_without_contacting_any_provider(monkeypatch):
    """The whole demo path must never reach a provider or a real network bot."""
    import app.blackbox.metering as metering

    def forbidden(*args, **kwargs):
        raise AssertionError("The demo must not call a provider")

    monkeypatch.setattr(metering, "completion", forbidden)

    class DemoBot:
        """Stands in for the HTTP connector, answering from the demo fixture.

        The replies are the same strings the separate demo-bot process serves,
        so this exercises scoring without binding a port inside the suite.
        """

        def __init__(self, target, *args):
            self.target = target

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            return {
                "transcript": [
                    {"input": turn, "output": demo_bot.reply(turn), "seconds": 0.01}
                    for turn in case.get("turns", [])
                ]
            }

    config = Settings(
        targets=[Target(name=demo_bot.DEMO_BOT_NAME, url=demo_bot.DEMO_URL)],
        categories=["hallucination"],
        consent=True,
        judge_enabled=False,
        custom_cases=[c for c in demo_bot.case_set() if c["category"] == "hallucination"],
    )
    run = asyncio.run(runner.execute(runner.make_run(config), config, DemoBot))
    runner.aggregate(run)
    scored = [r for case in run["cases"] for r in case["results"] if r.get("score") is not None]
    assert scored, "Deterministic checks must score with the AI Judge disabled"
    assert {r["status"] for r in scored} <= {"passed", "failed"}
    assert any(r["status"] == "failed" for r in scored)
    assert any(r["status"] == "passed" for r in scored)
