"""Run-scoped provider health and installed-only local fallback discovery."""

import asyncio
import hashlib
import time

import httpx

from .schema import JudgeSelection, Settings


def identity(judge: JudgeSelection) -> str:
    key = judge.token.get_secret_value() if judge.token else ""
    return hashlib.sha256(f"{judge.url}|{judge.model}|{key}".encode()).hexdigest()


async def local_fallbacks(config: Settings) -> list[JudgeSelection]:
    """Never download models, send private inputs to cloud, or switch bot models."""
    explicit = [j for j in config.judges if j.local and j.fallback]
    if explicit or not config.auto_local_fallback:
        return explicit
    if config._fallback_checked:
        return config._discovered_fallbacks
    # One lock per config, created on its owning event loop.
    if config._fallback_lock is None:
        config._fallback_lock = asyncio.Lock()
    async with config._fallback_lock:
        if config._fallback_checked:
            return config._discovered_fallbacks
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get("http://127.0.0.1:11434/api/tags")
                response.raise_for_status()
                models = [m["name"] for m in response.json().get("models", [])]
            names = [m for m in models if "embed" not in m.lower()]
            names.sort(key=lambda m: (not m.lower().startswith("gemma"), m))
            primary = {identity(j) for j in config.judges if not j.fallback}
            for name in names:
                candidate = JudgeSelection(model=name, local=True, fallback=True)
                if identity(candidate) not in primary:
                    config._discovered_fallbacks.append(candidate)
                if len(config._discovered_fallbacks) >= 2:
                    break
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
        config._fallback_checked = True
    return config._discovered_fallbacks


def blocked_reason(config: Settings, judge: JudgeSelection) -> str:
    until, reason = config._judge_health.get(identity(judge), (0, ""))
    return reason if until > time.monotonic() else ""


def mark_unavailable(config: Settings, judge: JudgeSelection, reason: str, quota: bool) -> None:
    # Credential changes produce a new identity; transient failures expire quickly.
    config._judge_health[identity(judge)] = (
        float("inf") if quota else time.monotonic() + 30,
        reason,
    )
