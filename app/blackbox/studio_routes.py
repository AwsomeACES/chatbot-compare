"""Small public API for the nontechnical ten-case Studio screen."""

import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr

from .judge_credentials import key_for_judge
from .schema import JudgeSelection, Settings
from .studio_engine import LIVE_CONFIGS, LIVE_RUNS, audit, settings_file, suite_summaries

router = APIRouter(prefix="/api/studio")


class JudgesUpdate(BaseModel):
    ownership_confirmed: bool = False
    judges: list[JudgeSelection] = Field(min_length=1, max_length=8)
    consent: bool
    target_tokens: list[SecretStr | None] = Field(default_factory=list, max_length=4)


class Override(BaseModel):
    case_id: str
    bot: int = Field(ge=0, le=3)
    score: float = Field(ge=0, le=100)
    note: str = Field(min_length=10, max_length=2000)


@router.get("/settings")
async def settings():
    from .easy_setup import public_defaults

    data = settings_file()
    data["scenario_suite_summaries"] = suite_summaries()
    data["saved_judge"] = public_defaults()
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get("http://127.0.0.1:11434/api/tags")
            response.raise_for_status()
            data["ollama_models"] = [m["name"] for m in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        data["ollama_models"] = []
    text_models = [m for m in data["ollama_models"] if "embed" not in m.lower()]
    for entry in data["judges"]:
        if entry["local"]:
            entry["model"] = text_models[0] if text_models else ""
        else:
            entry["model"] = os.getenv(entry.get("model_env", ""), "").strip() or entry["model"]
        entry["credential_configured"] = bool(not entry["local"] and key_for_judge(entry["url"]))
    data["preferred_local_model"] = text_models[0] if text_models else ""
    return data


def prepare(config: Settings, protocol: dict | None = None) -> Settings:
    from .easy_setup import BASE_POLICY, judge_defaults

    is_new = protocol is None
    # The selected suite must reach the override, or `cases()` would silently plan the default.
    protocol = protocol or settings_file(config.scenario_suite)
    config._protocol_override = protocol
    if is_new:
        config.judge_batch_size = protocol.get("judge_batch_size", config.judge_batch_size)
        config.judge_batch_wait_ms = protocol.get("judge_batch_wait_ms", config.judge_batch_wait_ms)
        config.local_classifiers = protocol.get("local_classifiers", config.local_classifiers)
    config.simple_mode = True
    config.categories = [c["category"] for c in protocol["cases"]]
    config.policy = config.policy or BASE_POLICY
    if not config.consent or not config.judge_consent:
        raise HTTPException(422, "Allow test messages and judge access to transcripts first.")
    if not any(not j.fallback for j in config.judges):
        raise HTTPException(422, "Choose at least one judge model.")
    defaults = judge_defaults()
    from pydantic import SecretStr

    for j in config.judges:
        if not j.token and not j.local:
            key = key_for_judge(j.url, defaults)
            j.token = SecretStr(key) if key else None
    config.category_weights = config.category_weights or protocol["weights"]
    first = next(j for j in config.judges if not j.fallback)
    config.judge_url, config.judge_model, config.judge_token = first.url, first.model, first.token
    config.judge_local_model, config.judge_model_alias = (
        first.local,
        first.price_alias or first.model,
    )
    return config


@router.post("/runs")
async def run(config: Settings):
    from ..blackbox_app import start

    config = prepare(config)
    # Discovery stays inside the runner, so unknown connections produce recorded reasons.
    return await start(config)


@router.put("/runs/{ident}/judges")
async def update_judges(ident: uuid.UUID, update: JudgesUpdate):
    from .runner import save

    key = str(ident)
    if key not in LIVE_CONFIGS:
        raise HTTPException(409, "This run is not active. Use Resume missing cases.")
    if not update.consent:
        raise HTTPException(422, "Allow the selected judges to receive transcripts.")
    cfg, run = LIVE_CONFIGS[key], LIVE_RUNS[key]
    if not any(not j.fallback for j in update.judges):
        raise HTTPException(422, "Select a primary judge.")
    import hashlib

    def fingerprint(j):
        return (
            hashlib.sha256(j.token.get_secret_value().encode()).hexdigest()[:12]
            if j.token
            else "saved-or-none"
        )

    switches = [{"model": j.model, "credential_fingerprint": fingerprint(j)} for j in update.judges]
    cfg._used_secrets.extend(j.token.get_secret_value() for j in cfg.judges if j.token)
    cfg.judges = update.judges
    cfg = prepare(cfg, run.get("protocol_snapshot"))
    run["config"]["judges"] = [j.model_dump(exclude={"token"}) for j in cfg.judges]
    audit(
        run,
        "judges_changed",
        credential_switches=switches,
        models=[j.model for j in cfg.judges],
        note="In-flight calls retain previous model; future cases use updated selection.",
    )
    save(run, cfg)
    return {"updated": True}


@router.post("/runs/{ident}/resume")
async def resume(ident: uuid.UUID, update: JudgesUpdate):
    from ..blackbox_app import get_run, resume_run

    original = get_run(ident)
    if not original["config"].get("simple_mode"):
        raise HTTPException(422, "Use the legacy screen to resume this older protocol.")
    cfg = Settings.model_validate(
        {
            **original["config"],
            "judges": update.judges,
            "consent": True,
            "judge_consent": update.consent,
            "ownership_confirmed": update.ownership_confirmed
            or original["config"].get("ownership_confirmed", False),
        }
    )
    if update.target_tokens:
        if len(update.target_tokens) != len(cfg.targets):
            raise HTTPException(422, "Enter credentials in the matching chatbot cards.")
        for target, token in zip(cfg.targets, update.target_tokens):
            target.token = token
    for slot in original.get("target_auth_slots", []):
        if not cfg.targets[slot].token:
            raise HTTPException(
                422, "Re-enter the API key for " + cfg.targets[slot].name + " before resuming."
            )
    cfg = prepare(cfg, original.get("protocol_snapshot"))
    return await resume_run(ident, cfg)


@router.post("/runs/{ident}/override")
def override(ident: uuid.UUID, value: Override):
    from ..blackbox_app import get_run
    from .runner import ACTIVE, aggregate, save

    if str(ident) in ACTIVE:
        raise HTTPException(409, "Stop the run before adding a human review.")
    run = get_run(ident)
    if value.bot >= len(run["targets"]):
        raise HTTPException(422, "Unknown chatbot.")
    case = next((c for c in run["cases"] if c["id"] == value.case_id), None)
    if not case:
        raise HTTPException(404, "Case not found.")
    result = case["results"][value.bot]
    if not any(t.get("output") for t in result.get("transcript", [])):
        raise HTTPException(422, "Cannot score a conversation that has no chatbot response.")
    # Preserve the original verdict as evidence rather than silently replacing it.
    result.setdefault(
        "original_verdict", {k: v for k, v in result.items() if k != "original_verdict"}
    )
    audit(
        run,
        "human_override",
        case=value.case_id,
        bot=value.bot,
        previous_score=result.get("score"),
        score=value.score,
        note=value.note,
    )
    result.update(
        score=value.score,
        status="passed" if value.score >= 80 else "failed",
        human_review_note=value.note,
        reason="Human review: " + value.note,
        estimated=False,
        overridden=True,
    )
    save(aggregate(run))
    return {"saved": True}


@router.post("/models")
async def model_choices(selection: JudgeSelection):
    """List models from the selected account, without guessing available IDs."""
    from urllib.parse import urlsplit

    from pydantic import SecretStr

    from .connectors import safe_error, validate_destination
    from .easy_setup import judge_defaults

    defaults = judge_defaults()
    if not selection.token and not selection.local:
        key = key_for_judge(selection.url, defaults)
        selection.token = SecretStr(key) if key else None
    host = urlsplit(selection.url).hostname
    headers = {}
    secret = selection.token.get_secret_value() if selection.token else ""
    if host == "generativelanguage.googleapis.com":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"x-goog-api-key": secret}
    elif host == "api.anthropic.com":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": secret, "anthropic-version": "2023-06-01"}
    else:
        url = selection.url.rsplit("/chat/completions", 1)[0] + "/models"
        if secret:
            headers = {"Authorization": "Bearer " + secret}
    await validate_destination(url)
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        models = data.get("models", data.get("data", []))
        return {
            "models": [m.get("id", m.get("name", "")).removeprefix("models/") for m in models],
            "note": "Account model listing succeeded; actual judgment still requires a valid response.",
        }
    except Exception as exc:
        raise HTTPException(422, safe_error(exc)) from exc
