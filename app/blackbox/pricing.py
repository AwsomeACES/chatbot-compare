"""Immutable price snapshots. Rates are USD per million tokens, never code constants."""

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx

from .. import database as db
from ..config import ROOT, RUNTIME

SOURCE = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
LOCK = threading.RLock()
RATE_KEYS = ("input", "cached_input", "output", "reasoning", "cache_write", "cache_write_1h")


def decimal(value):
    try:
        result = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError("Enter a valid numeric rate or budget.") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1000000000"):
        raise ValueError("Rates and budgets must be finite, non-negative numbers.")
    return result


def micro(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def now():
    return datetime.now(timezone.utc).isoformat()


def folder():
    p = RUNTIME / "pricing"
    p.mkdir(exist_ok=True)
    return p


def store_snapshot(models, source=SOURCE, source_date=None, activate=True):
    body = {"source": source, "date": source_date or now(), "models": models}
    ident = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:24]
    body["id"] = ident
    p = folder() / f"{ident}.json"
    with LOCK:
        if not p.exists():
            p.write_text(json.dumps(body, indent=2), encoding="utf-8")
        if activate:
            db.save("cost_meta", {"id": "active-prices", "snapshot_id": ident})
    return body


def snapshot(ident=None):
    if not ident:
        record = db.get("cost_meta", "active-prices")
        ident = record["snapshot_id"] if record else None
    if ident:
        if len(ident) != 24 or any(c not in "0123456789abcdef" for c in ident):
            raise ValueError("Invalid price snapshot ID.")
        return json.loads((folder() / f"{ident}.json").read_text(encoding="utf-8"))
    seed = ROOT / "app" / "pricing" / "seed.json"
    if seed.exists():
        data = json.loads(seed.read_text(encoding="utf-8"))
        return store_snapshot(data["models"], data["source"], data["date"])
    return store_snapshot({}, "No price snapshot installed")


def normalize_catalog(data):
    if not isinstance(data, dict) or len(data) > 100000:
        raise ValueError("Invalid pricing catalogue.")
    models = {}
    for model, row in data.items():
        if not isinstance(row, dict) or not isinstance(model, str) or len(model) > 250:
            continue
        mapping = {
            "input": "input_cost_per_token",
            "cached_input": "cache_read_input_token_cost",
            "output": "output_cost_per_token",
            "reasoning": "output_cost_per_reasoning_token",
            "cache_write": "cache_creation_input_token_cost",
            "cache_write_1h": "cache_creation_input_token_cost_above_1hr",
        }
        rates = {}
        for name, key in mapping.items():
            if key in row and row[key] is not None:
                try:
                    rates[name] = str(decimal(row[key]) * 1000000)
                except (ValueError, ArithmeticError):
                    continue
        if not rates:
            continue
        # Reasoning output uses the output rate unless a separate price is explicitly supplied.
        if "reasoning" not in rates and "output" in rates:
            rates["reasoning"] = rates["output"]
        rates["provider"] = str(row.get("litellm_provider", "unknown"))
        rates["tiers"] = {
            k: str(v)
            for k, v in row.items()
            if ("cost" in k and ("above_" in k or "priority" in k))
        }
        models[model] = rates
    if not models:
        raise ValueError("Pricing source contains no usable token rates.")
    return models


async def refresh():
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", SOURCE) as response:
            response.raise_for_status()
            raw = bytearray()
            async for part in response.aiter_bytes():
                raw.extend(part)
                if len(raw) > 20000000:
                    raise ValueError("Price file exceeds size limit.")
    return store_snapshot(normalize_catalog(json.loads(raw)))


def settings():
    return db.get("cost_settings", "global") or {
        "id": "global",
        "overrides": {},
        "aliases": {},
        "compute_usd_hour": "0",
        "inr_per_usd": None,
        "quality_threshold": 80,
        "average_input_tokens": 1000,
        "average_output_tokens": 300,
        "max_budget_usd": None,
    }


def save_settings(data):
    allowed = {
        "overrides",
        "aliases",
        "compute_usd_hour",
        "inr_per_usd",
        "quality_threshold",
        "average_input_tokens",
        "average_output_tokens",
        "max_budget_usd",
    }
    if set(data) - allowed:
        raise ValueError("Unsupported cost setting.")
    clean = settings()
    clean.update(data)
    if not isinstance(clean["overrides"], dict) or len(clean["overrides"]) > 500:
        raise ValueError("Maximum 500 price overrides.")
    for model, rates in clean["overrides"].items():
        if (
            not isinstance(model, str)
            or not 1 <= len(model) <= 250
            or not isinstance(rates, dict)
            or set(rates) - set(RATE_KEYS)
        ):
            raise ValueError("Invalid price override.")
        clean["overrides"][model] = {
            k: str(decimal(v)) for k, v in rates.items() if v is not None and v != ""
        }
    if not isinstance(clean["aliases"], dict) or len(clean["aliases"]) > 500:
        raise ValueError("Invalid aliases.")
    for name, value in clean["aliases"].items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or len(name) > 250
            or len(value) > 250
        ):
            raise ValueError("Invalid model alias.")
    for key in ("compute_usd_hour", "inr_per_usd", "max_budget_usd"):
        clean[key] = str(decimal(clean[key])) if clean[key] not in (None, "") else None
    if not 0 <= float(clean["quality_threshold"]) <= 100:
        raise ValueError("Score threshold must be 0-100.")
    for key in ("average_input_tokens", "average_output_tokens"):
        value = clean[key]
        if type(value) is not int or not 0 <= value <= 1000000:
            raise ValueError("Average tokens must be integers from 0 to 1,000,000.")
    db.save("cost_settings", clean)
    return clean


def pin(config):
    if getattr(config, "price_snapshot_id", ""):
        return snapshot(config.price_snapshot_id)
    current = snapshot()
    s = settings()
    models = json.loads(json.dumps(current["models"]))
    for name, rates in s["overrides"].items():
        models[name] = {**models.get(name, {}), **rates, "override": True}
    pinned = (
        store_snapshot(
            models, current["source"] + " + saved overrides", current["date"], activate=False
        )
        if s["overrides"]
        else current
    )
    config.price_snapshot_id = pinned["id"]
    config.cost_settings_snapshot = s
    if config.max_budget_usd is None and s["max_budget_usd"] is not None:
        config.max_budget_usd = s["max_budget_usd"]
    return pinned


def price_for(snap, model, alias="", saved=None):
    name = alias or model
    name = (saved or {}).get("aliases", {}).get(name, name)
    return snap["models"].get(name), name


def calculate(tokens, rates, latency_ms=0, local=False, compute_rate="0"):
    if local:
        return Decimal(str(compute_rate or 0)) * Decimal(str(latency_ms)) / Decimal(
            3600000
        ) * Decimal(1000000), "local"
    if not rates:
        return None, "unknown"
    # Counts are disjoint: plain input/output exclude cached/write/reasoning tokens.
    total = Decimal(0)
    keys = {
        "input_tokens": "input",
        "cached_input_tokens": "cached_input",
        "output_tokens": "output",
        "reasoning_tokens": "reasoning",
        "cache_write_tokens": "cache_write",
        "cache_write_1h_tokens": "cache_write_1h",
    }
    effective = dict(rates)
    total_input = sum(
        tokens.get(k, 0)
        for k in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "cache_write_1h_tokens",
        )
    )
    tiers = rates.get("tiers", {})
    for threshold in (128000, 200000):
        if total_input > threshold:
            suffix = "128k" if threshold == 128000 else "200k"
            for key, lite in [
                ("input", "input"),
                ("output", "output"),
                ("cached_input", "cache_read_input_token"),
            ]:
                field = (
                    f"{lite}_cost_per_token_above_{suffix}_tokens"
                    if key != "cached_input"
                    else f"{lite}_cost_above_{suffix}_tokens"
                )
                if field in tiers:
                    effective[key] = str(decimal(tiers[field]) * 1000000)
            if rates.get("reasoning") == rates.get("output"):
                effective["reasoning"] = effective.get("output")
    for count_key, rate_key in keys.items():
        count = tokens.get(count_key, 0)
        if count:
            rate = effective.get(rate_key)
            if rate is None:
                return None, "unknown"
            total += Decimal(count) * decimal(rate)  # USD/1M * tokens = micro-USD
    return total, "priced"
