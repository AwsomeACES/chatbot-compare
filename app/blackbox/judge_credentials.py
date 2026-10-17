"""Studio-owned credentials, resolved by judge endpoint rather than target bot."""

import json
import os
from urllib.parse import urlsplit

from dotenv import dotenv_values

from ..config import ROOT


def providers() -> list[dict]:
    """Provider names, endpoints and environment names are editable configuration."""
    path = ROOT / "app/studio/settings.json"
    return json.loads(path.read_text(encoding="utf-8"))["judges"]


def same_endpoint(first: str, second: str) -> bool:
    def normalized(value: str) -> tuple | None:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        if not parsed.hostname:
            return None
        return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/")

    expected = normalized(second)
    return expected is not None and normalized(first) == expected


def provider_key(entry: dict) -> str:
    names = [entry.get("key_env", ""), *entry.get("key_env_aliases", [])]
    return next(
        (os.environ[name].strip() for name in names if name and os.getenv(name, "").strip()), ""
    )


def endpoint_key(url: str) -> str:
    """Never forward a provider key to an arbitrary custom endpoint."""
    return next(
        (
            provider_key(entry)
            for entry in providers()
            if not entry.get("local") and same_endpoint(url, entry["url"]) and provider_key(entry)
        ),
        "",
    )


def saved_judge() -> dict[str, str]:
    entries = providers()
    provider = os.getenv("STUDIO_JUDGE_PROVIDER", "").strip().lower()
    selected = next(
        (
            entry
            for entry in entries
            if provider in [entry.get("provider"), *entry.get("provider_aliases", [])]
        ),
        {},
    )
    if provider and not selected and provider != "custom":
        raise ValueError(
            "Unknown STUDIO_JUDGE_PROVIDER; use a provider from app/studio/settings.json."
        )
    url = os.getenv("STUDIO_JUDGE_URL", "").strip() or selected.get(
        "url", "http://127.0.0.1:1234/v1/chat/completions"
    )
    if not selected:
        selected = next((entry for entry in entries if same_endpoint(url, entry["url"])), {})
    model = (
        os.getenv("STUDIO_JUDGE_MODEL", "").strip()
        or os.getenv(selected.get("model_env", ""), "").strip()
    )
    key = os.getenv("STUDIO_JUDGE_API_KEY", "").strip() or endpoint_key(url)
    # Explicit legacy opt-in only. No chatbot folder is consulted by default.
    source = os.getenv("STUDIO_JUDGE_ENV_FILE", "").strip()
    if not key and source:
        values = dotenv_values(source)
        key = values.get(os.getenv("STUDIO_JUDGE_KEY_NAME", "GOOGLE_API_KEY"), "") or ""
    return {"url": url, "model": model, "key": key}


def key_for_judge(url: str, defaults: dict | None = None) -> str:
    saved = defaults if defaults is not None else saved_judge()
    if same_endpoint(url, saved["url"]) and saved.get("key"):
        return saved["key"]
    return endpoint_key(url)
