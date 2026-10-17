"""Saved judge keys are independent of target bots and restricted to providers."""

import asyncio
import json

import pytest
from pydantic import SecretStr

from app.blackbox import easy_setup, judge_credentials, studio_routes
from app.blackbox.schema import JudgeSelection, Settings, Target


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    names = {
        "STUDIO_JUDGE_PROVIDER",
        "STUDIO_JUDGE_URL",
        "STUDIO_JUDGE_MODEL",
        "STUDIO_JUDGE_API_KEY",
        "STUDIO_JUDGE_ENV_FILE",
        "STUDIO_JUDGE_KEY_NAME",
    }
    for entry in judge_credentials.providers():
        names.update([entry.get("key_env", ""), entry.get("model_env", "")])
        names.update(entry.get("key_env_aliases", []))
    for name in names - {""}:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "provider,key_env,model_env",
    [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL"),
        ("claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL"),
        ("gemma", "GEMINI_API_KEY", "GEMMA_MODEL"),
    ],
)
def test_provider_uses_studio_keys_without_external_bot_file(
    monkeypatch, provider, key_env, model_env
):
    monkeypatch.setenv("STUDIO_JUDGE_PROVIDER", provider)
    monkeypatch.setenv(key_env, "fixture-account-key")
    monkeypatch.setenv(model_env, "fixture-account-model")
    monkeypatch.setattr(
        judge_credentials, "dotenv_values", lambda *args: pytest.fail("External file accessed")
    )
    saved = easy_setup.judge_defaults()
    assert saved["key"] == "fixture-account-key"
    assert saved["model"] == "fixture-account-model"
    assert "fixture-account-key" not in json.dumps(easy_setup.public_defaults())


def test_generic_override_and_legacy_opt_in_precedence(monkeypatch, tmp_path):
    source = tmp_path / "separate.env"
    source.write_text("OTHER_KEY=fixture-legacy\n")
    monkeypatch.setenv("STUDIO_JUDGE_ENV_FILE", str(source))
    monkeypatch.setenv("STUDIO_JUDGE_KEY_NAME", "OTHER_KEY")
    assert easy_setup.judge_defaults()["key"] == "fixture-legacy"
    monkeypatch.setenv("STUDIO_JUDGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-studio-key")
    assert easy_setup.judge_defaults()["key"] == "fixture-studio-key"
    monkeypatch.setenv("STUDIO_JUDGE_API_KEY", "fixture-explicit")
    assert easy_setup.judge_defaults()["key"] == "fixture-explicit"


def test_saved_provider_keys_never_follow_custom_hosts(monkeypatch):
    monkeypatch.setenv("STUDIO_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-private-key")
    monkeypatch.setenv("STUDIO_JUDGE_URL", "https://custom.example/v1/chat/completions")
    assert easy_setup.judge_defaults()["key"] == ""
    for url in (
        "https://api.openai.com.evil.example/v1/chat/completions",
        "http://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions?forward=elsewhere",
        "https://someone@api.openai.com/v1/chat/completions",
        "http://localhost:11434/v1/chat/completions",
    ):
        assert judge_credentials.key_for_judge(url) == ""
    assert (
        judge_credentials.key_for_judge("https://api.openai.com/v1/chat/completions")
        == "fixture-private-key"
    )


def test_several_judges_use_their_provider_key_for_any_target(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-google")
    protocol = studio_routes.settings_file()
    endpoints = {entry["provider"]: entry["url"] for entry in protocol["judges"]}
    for bot in ("http://localhost:9901/chat", "https://arbitrary-bot.example/chat"):
        config = Settings(
            targets=[Target(url=bot)],
            consent=True,
            judge_consent=True,
            judges=[
                JudgeSelection(model="fixture-a", url=endpoints["openai"]),
                JudgeSelection(model="fixture-b", url=endpoints["gemini"]),
            ],
        )
        prepared = studio_routes.prepare(config)
        assert [judge.token.get_secret_value() for judge in prepared.judges] == [
            "fixture-openai",
            "fixture-google",
        ]
        assert prepared.targets[0].token is None
    config.judges[0].token = SecretStr("fixture-ui-override")
    assert studio_routes.prepare(config).judges[0].token.get_secret_value() == "fixture-ui-override"


def test_model_listing_uses_matching_saved_account(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai")
    seen = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers):
            seen.append((url, headers))
            import httpx

            return httpx.Response(
                200,
                json={"data": [{"id": "fixture-listed-model"}]},
                request=httpx.Request("GET", url),
            )

    async def allow(url):
        return None

    monkeypatch.setattr(studio_routes.httpx, "AsyncClient", Client)
    monkeypatch.setattr("app.blackbox.connectors.validate_destination", allow)
    result = asyncio.run(
        studio_routes.model_choices(
            JudgeSelection(model="discovery", url="https://api.openai.com/v1/chat/completions")
        )
    )
    assert result["models"] == ["fixture-listed-model"]
    assert seen[0][1] == {"Authorization": "Bearer fixture-openai"}
