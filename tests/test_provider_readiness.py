"""Provider readiness, failure classification and panel policy (ST-05).

The saved VoltKart retest surfaced four different conditions as one "judge unavailable" state:
OpenAI listed its models but refused inference with an exhausted API billing quota; Gemini 2.5
Flash Lite appeared in discovery but its inference call reported the model unavailable for new
users; VoltKart's own Gemini calls returned HTTP 429; and some responses were not valid verdicts.
They need different owner actions, so they must be reported as different states.
"""

import asyncio

import httpx
import pytest

from app.blackbox import provider_status, studio_engine
from app.blackbox.schema import JudgeSelection, Settings, Target


def error(message="", status=None, body=""):
    """An exception shaped like the ones the provider clients raise."""
    if status is None:
        return ValueError(message)
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(status, request=request, text=body or message)
    return httpx.HTTPStatusError(message, request=request, response=response)


# --- the four conditions from the retest -------------------------------------------------------


def test_exhausted_billing_is_not_a_rate_limit():
    """OpenAI returns 429 for an exhausted balance, which waiting cannot fix."""
    exc = error("You exceeded your current quota", status=429, body="insufficient_quota")
    assert provider_status.classify(exc) == "billing_exhausted"
    described = provider_status.describe(exc)
    assert described["retryable"] is False
    assert "Add provider credit" in described["action"]
    assert provider_status.needs_owner_action(exc) is True


def test_a_daily_quota_block_is_distinct_from_an_exhausted_balance():
    exc = error("Quota exceeded", status=429, body="GenerateRequestsPerDayPerProject")
    assert provider_status.classify(exc) == "quota_exhausted"
    assert "quota reset" in provider_status.describe(exc)["action"]


def test_a_model_listed_but_not_callable_is_its_own_state():
    """Gemini 2.5 Flash Lite was discoverable but reported unavailable for new users."""
    exc = error("Model is not available for new users", status=400)
    assert provider_status.classify(exc) == "model_unavailable"
    assert provider_status.needs_owner_action(exc) is True
    assert "entitled to use" in provider_status.describe(exc)["action"]


def test_a_plain_rate_limit_is_transient():
    """VoltKart's Gemini calls hit HTTP 429 with no billing or quota marker."""
    exc = error("Too Many Requests", status=429)
    assert provider_status.classify(exc) == "rate_limited"
    assert provider_status.describe(exc)["retryable"] is True
    assert provider_status.needs_owner_action(exc) is False


def test_an_authentication_failure_is_not_a_quota_problem():
    for exc in (error("Forbidden", status=403), error("API key not valid"), error("", status=401)):
        assert provider_status.classify(exc) == "authentication_failed", exc
        assert provider_status.needs_owner_action(exc) is True


@pytest.mark.parametrize(
    "message",
    [
        "Judge must return exactly one verdict object.",
        "Judge omitted its explanation.",
        "Judge score must be a finite number from 0 to 100.",
        "Judge evidence did not match the recorded assistant replies after one retry.",
        "Judge response was incomplete.",
        "Batch IDs missing, duplicated or invalid",
    ],
)
def test_an_unusable_response_is_an_invalid_verdict_not_an_outage(message):
    """The provider answered; the output was the problem. That is not a provider outage."""
    exc = provider_status.classify(error(message))
    assert exc == "invalid_verdict"
    assert "retained raw output" in provider_status.STATES["invalid_verdict"]["action"]


@pytest.mark.parametrize("status", [500, 502, 503, 504, 408])
def test_a_server_side_failure_is_transport(status):
    assert provider_status.classify(error("Server error", status=status)) == "transport_error"


def test_a_timeout_is_transport():
    assert provider_status.classify(ValueError("Request timed out.")) == "transport_error"
    assert provider_status.classify(ValueError("Target connection failed")) == "transport_error"


def test_an_unfamiliar_failure_is_not_assumed_transient():
    """An unrecognised condition must not be retried as though it were temporary."""
    exc = error("something nobody has seen before")
    assert provider_status.classify(exc) == "unclassified"
    assert provider_status.needs_owner_action(exc) is True


def test_classification_never_raises_on_an_odd_error():
    class Awkward(Exception):
        def __str__(self):
            return "boom"

    assert provider_status.classify(Awkward()) in provider_status.STATES


def test_every_state_declares_a_label_retry_flag_and_action():
    for state, row in provider_status.STATES.items():
        assert row["label"] and row["action"], state
        assert isinstance(row["retryable"], bool), state


# --- discovery is not inference readiness -------------------------------------------------------


def test_the_discovery_note_separates_listing_from_calling():
    note = provider_status.DISCOVERY_NOTE
    assert "not what it can call" in note
    assert "successful metered request that returns a valid verdict" in note


def test_the_models_endpoint_reports_discoverable_rather_than_ready(monkeypatch):
    from fastapi.testclient import TestClient

    from app.blackbox import studio_routes
    from app.blackbox_app import app

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "models/gemini-2.5-flash-lite"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return Response()

    monkeypatch.setattr(studio_routes.httpx, "AsyncClient", lambda **kw: Client())

    async def allow(url):
        return None

    monkeypatch.setattr("app.blackbox.connectors.validate_destination", allow)
    with TestClient(app) as client:
        body = client.post(
            "/api/studio/models",
            json={"model": "probe", "url": "https://api.example.test/v1/chat/completions"},
            headers={"X-Studio-Request": "1"},
        )
    assert body.status_code == 200
    data = body.json()
    assert data["readiness"] == "discoverable"
    assert "not what it can call" in data["note"]
    assert data["models"] == ["gemini-2.5-flash-lite"]


# --- the panel policy is stated, not inferred ---------------------------------------------------


def policy_config():
    return Settings(
        targets=[Target(url="http://localhost:8765", model="gemini-3.5-flash-lite")],
        simple_mode=True,
        judges=[
            JudgeSelection(model="gemini-3.5-flash-lite", url="https://api.example.test/v1"),
            JudgeSelection(model="llama3.2:3b", local=True, fallback=True),
        ],
        consent=True,
        judge_consent=True,
    )


def test_the_policy_records_requested_judges_and_declared_fallbacks():
    policy = provider_status.panel_policy(policy_config())
    assert [j["model"] for j in policy["requested_judges"]] == ["gemini-3.5-flash-lite"]
    assert [j["model"] for j in policy["declared_fallbacks"]] == ["llama3.2:3b"]
    assert policy["version"] == "judge-panel-policy-v1"


def test_the_policy_forbids_dropping_a_judge_or_changing_the_bot_model():
    rules = " ".join(provider_status.PANEL_POLICY["rules"])
    assert "never removed to make the panel look complete" in rules
    assert "target chatbot's model is never changed because its Judge failed" in rules
    assert "No model is downloaded" in rules
    assert "Judges are not interchangeable" in rules


def test_a_run_states_its_panel_policy(monkeypatch):
    from app.blackbox import runner

    monkeypatch.setattr(runner, "summarize", lambda run: {})
    protocol = studio_engine.settings_file()
    config = policy_config()
    config.repeat_counts = {case["category"]: 1 for case in protocol["cases"]}
    run = runner.make_run(config)
    policy = run["judge_policy"]
    assert policy["requested_judges"][0]["model"] == "gemini-3.5-flash-lite"
    assert "not what it can call" in policy["discovery_note"]


# --- a failed judge is classified and never swaps the bot's model --------------------------------


def run_panel(monkeypatch, failure):
    from app.blackbox import judge

    async def fake(cfg, case, observation):
        if cfg.judge_model == "cloud":
            raise failure
        return {"score": 90, "reason": "Supported", "evidence": ["Answer"]}

    monkeypatch.setattr(judge, "evaluate", fake)
    config = Settings(
        targets=[Target(url="http://localhost:8765", model="gemini-3.5-flash-lite")],
        simple_mode=True,
        judges=[
            JudgeSelection(model="cloud", url="https://api.example.test/v1"),
            JudgeSelection(model="local-judge", local=True, fallback=True),
        ],
        consent=True,
        judge_consent=True,
        auto_local_fallback=False,
    )
    result = asyncio.run(
        studio_engine.panel(config, {"id": "test"}, {"transcript": [{"output": "Answer"}]})
    )
    return config, result


def test_a_judge_failure_records_its_classification_and_action(monkeypatch):
    failure = error("You exceeded your current quota", status=429, body="insufficient_quota")
    config, result = run_panel(monkeypatch, failure)
    [recorded] = result["judge_failures"]
    assert recorded["model"] == "cloud"
    assert recorded["state"] == "billing_exhausted"
    assert recorded["retryable"] is False
    assert "Add provider credit" in recorded["action"]


def test_a_failed_judge_does_not_change_the_target_model(monkeypatch):
    """A Judge problem must never be answered by switching the chatbot under test."""
    config, result = run_panel(monkeypatch, error("Too Many Requests", status=429))
    assert config.targets[0].model == "gemini-3.5-flash-lite"
    assert result["judges"][0]["model"] == "local-judge", "the fallback judged it"
    assert result["judges"][0]["requested_model"] == "cloud", "the request is still recorded"
    assert result["judges"][0]["fallback"] is True
    assert [r["model"] for r in result["judges"][0]["fallback_reasons"]] == ["cloud"]


def test_a_transient_failure_gets_a_short_cooldown_and_a_block_reason(monkeypatch):
    from app.blackbox.judge_recovery import blocked_reason

    config, _ = run_panel(monkeypatch, error("Too Many Requests", status=429))
    cloud = next(j for j in config.judges if j.model == "cloud")
    assert blocked_reason(config, cloud), "a failed judge is put on cooldown"


def test_an_owner_action_failure_is_not_retried_for_the_rest_of_the_run(monkeypatch):
    """Billing exhaustion cannot be waited out, so the judge stays blocked."""
    import time

    from app.blackbox.judge_recovery import identity

    failure = error("insufficient balance", status=429)
    config, _ = run_panel(monkeypatch, failure)
    cloud = next(j for j in config.judges if j.model == "cloud")
    until, _reason = config._judge_health[identity(cloud)]
    assert until == float("inf")
    assert until > time.monotonic() + 3600
