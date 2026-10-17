"""One usage row per attempted call; never persist prompts, answers or API keys here."""

import asyncio
import contextvars
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from urllib.parse import urlsplit

from .. import database as db
from . import pricing

TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_write_tokens",
    "cache_write_1h_tokens",
)
ROLES = {"target", "judge", "attacker", "generator", "guard", "hallucination_detector", "embedding"}
_context = contextvars.ContextVar("studio_meter_context", default=None)


class BudgetLimit(Exception):
    pass


@contextmanager
def scope(run_id, mode, config, **labels):
    token = _context.set({"run_id": run_id, "mode": mode, "config": config, **labels})
    try:
        yield
    finally:
        _context.reset(token)


def init_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS usage_events (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL, mode TEXT, bot_slot TEXT, role TEXT,
      category TEXT, test_case_id TEXT, turn_index INTEGER, provider TEXT, model TEXT, model_alias TEXT,
      token_source TEXT, input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER,
      reasoning_tokens INTEGER, cache_write_tokens INTEGER, cache_write_1h_tokens INTEGER,
      cost_micro_usd INTEGER, cost_exact_micro_usd TEXT, cost_status TEXT, price_snapshot_id TEXT,
      latency_ms REAL, attempt_number INTEGER, status TEXT, timestamp TEXT, in_flight INTEGER,
      reserved_micro_usd INTEGER, visibility TEXT, note TEXT, conversation_id TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS usage_run ON usage_events(run_id)")


def events(run_id):
    with db.connect() as conn:
        init_db(conn)
        conn.row_factory = __import__("sqlite3").Row
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM usage_events WHERE run_id=? ORDER BY timestamp,id", (run_id,)
            )
        ]


def recover_interrupted():
    """Called once at startup, before any new run can dispatch calls."""
    with db.connect() as conn:
        init_db(conn)
        conn.execute(
            (
                "UPDATE usage_events SET in_flight=0,reserved_micro_usd=0,status='error',"
                "cost_status='unknown',cost_micro_usd=NULL,cost_exact_micro_usd=NULL,note"
                "='Application stopped before billing evidence was recorded.' WHERE "
                "in_flight=1"
            )
        )


def provider_from(url):
    host = urlsplit(url).hostname or ""
    if "googleapis.com" in host:
        return "gemini"
    if "anthropic.com" in host:
        return "anthropic"
    if "openai.com" in host:
        return "openai"
    return "openai-compatible"


def normalize(data, model=""):
    if not isinstance(data, dict):
        return None
    usage = (
        data.get("usageMetadata")
        or data.get("usage")
        or data.get("stream_metadata", {}).get("usage")
    )
    if not isinstance(usage, dict):
        return None

    def n(key, source=usage):
        value = source.get(key, 0)
        if type(value) is not int or value < 0:
            raise ValueError("Invalid provider token usage.")
        return value

    counts = dict.fromkeys(TOKEN_FIELDS, 0)
    if "promptTokenCount" in usage:
        total = n("promptTokenCount")
        cached = n("cachedContentTokenCount")
        counts.update(
            input_tokens=total - cached,
            cached_input_tokens=cached,
            output_tokens=n("candidatesTokenCount"),
            reasoning_tokens=n("thoughtsTokenCount"),
        )
        if usage.get("toolUsePromptTokenCount"):
            return None  # Nonstandard charge requires instrumentation.
    elif "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:
        cache = usage.get("cache_creation") or {}
        short = n("ephemeral_5m_input_tokens", cache)
        long = n("ephemeral_1h_input_tokens", cache)
        total_write = n("cache_creation_input_tokens")
        if short + long == 0:
            short = total_write
        elif short + long != total_write:
            raise ValueError("Inconsistent cache write usage.")
        counts.update(
            input_tokens=n("input_tokens"),
            cached_input_tokens=n("cache_read_input_tokens"),
            output_tokens=n("output_tokens"),
            cache_write_tokens=short,
            cache_write_1h_tokens=long,
        )
    elif "prompt_tokens" in usage or "input_tokens" in usage:
        total = n("prompt_tokens") if "prompt_tokens" in usage else n("input_tokens")
        output = n("completion_tokens") if "completion_tokens" in usage else n("output_tokens")
        cached = n(
            "cached_tokens",
            usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {},
        )
        reasoning = n(
            "reasoning_tokens",
            usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {},
        )
        # Google's compatibility API can omit thoughts from completion_tokens
        # while including them in total_tokens. Reconcile provider totals so
        # these billable tokens are not silently omitted or counted twice.
        name = str(data.get("model") or model).lower()
        extra_thoughts = 0
        if any(family in name for family in ("gemini", "gemma")) and "total_tokens" in usage:
            reported_total = n("total_tokens")
            if reported_total < total + output:
                raise ValueError("Inconsistent Gemini token totals.")
            extra_thoughts = reported_total - total - output
        counts.update(
            input_tokens=total - cached,
            cached_input_tokens=cached,
            output_tokens=output - reasoning,
            reasoning_tokens=reasoning + extra_thoughts,
        )
    else:
        return None
    if any(v < 0 for v in counts.values()):
        raise ValueError("Provider token components exceed totals.")
    return counts


def count_text(model, messages, output, opaque=False, tokenizer=None):
    counts = dict.fromkeys(TOKEN_FIELDS, 0)
    text = json.dumps(messages, ensure_ascii=False)
    if tokenizer is not None and not opaque:
        counts["input_tokens"] = len(tokenizer.encode(text))
        counts["output_tokens"] = len(tokenizer.encode(output))
        return counts, "counted"
    if model and not opaque:
        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(model.removeprefix("openai/"))
            # LiteLLM applies the model's message framing; unknown model fallback is never labelled counted.
            from litellm import token_counter

            counts["input_tokens"] = token_counter(model=model, messages=messages)
            counts["output_tokens"] = len(encoding.encode(output))
            return counts, "counted"
        except Exception:
            pass
    counts["input_tokens"] = math.ceil(len(text) / 4)
    counts["output_tokens"] = math.ceil(len(output) / 4)
    return counts, "estimated"


def output_text(data):
    if not isinstance(data, dict):
        return str(data or "")
    try:
        return str(data["choices"][0]["message"].get("content") or "")
    except (KeyError, IndexError, TypeError):
        pass
    for key in ("reply", "answer", "response", "message", "text"):
        if isinstance(data.get(key), str):
            return data[key]
    return ""


class Meter:
    def __init__(self, config, run_id, mode):
        self.config = config
        self.run_id = run_id
        self.mode = mode

    async def call(
        self,
        operation,
        *,
        role,
        model="",
        alias="",
        provider="unknown",
        messages=None,
        turn_index=0,
        bot_slot=None,
        local=False,
        opaque=False,
        max_output_tokens=1500,
        retries=0,
        tokenizer=None,
        conversation_id="",
    ):
        if role not in ROLES:
            raise ValueError("Invalid usage role.")
        ctx = _context.get() or {}
        config = self.config
        snap = pricing.snapshot(config.price_snapshot_id)
        rates, resolved = pricing.price_for(snap, model, alias, config.cost_settings_snapshot)
        messages = messages or []
        for retry in range(retries + 1):
            estimate, _ = count_text(resolved, messages, "", opaque)
            estimate["output_tokens"] = max_output_tokens
            reservation, _ = pricing.calculate(
                estimate,
                rates,
                local=local,
                compute_rate=config.cost_settings_snapshot.get("compute_usd_hour", "0"),
            )
            ident = str(uuid.uuid4())
            labels = (self.run_id, bot_slot, role, ctx.get("test_case_id", ""), turn_index)
            with db.connect() as conn:
                init_db(conn)
                conn.execute("BEGIN IMMEDIATE")
                prior = conn.execute(
                    (
                        "SELECT COUNT(*) FROM usage_events WHERE run_id=? AND bot_slot IS ? AND "
                        "role=? AND test_case_id=? AND "
                        "turn_index=?"
                    ),
                    labels,
                ).fetchone()[0]
                if config.max_budget_usd is not None:
                    limit = pricing.decimal(config.max_budget_usd) * 1000000
                    rows = conn.execute(
                        (
                            "SELECT cost_exact_micro_usd,in_flight,reserved_micro_usd,cost_status "
                            "FROM usage_events WHERE run_id=?"
                        ),
                        (self.run_id,),
                    ).fetchall()
                    if any(not flight and status == "unknown" for _, flight, _, status in rows):
                        raise BudgetLimit(
                            "Not tested: paused because a failed call has unknown billing. This does not mean the dollar budget was spent. Check the provider error and billing before resuming."
                        )
                    spent = sum(
                        (Decimal(reserve or 0) if flight else Decimal(cost or 0))
                        for cost, flight, reserve, status in rows
                    )
                    if reservation is None:
                        raise BudgetLimit(
                            "Not tested: budget limit requires known model pricing before launching a call."
                        )
                    if spent >= limit or spent + reservation > limit:
                        raise BudgetLimit(
                            "Not tested: budget limit (including estimated next-call allowance)."
                        )
                event = {
                    "id": ident,
                    "run_id": self.run_id,
                    "mode": self.mode,
                    "bot_slot": bot_slot,
                    "role": role,
                    "category": ctx.get("category", ""),
                    "test_case_id": ctx.get("test_case_id", ""),
                    "turn_index": turn_index,
                    "provider": provider,
                    "model": model or "unknown",
                    "model_alias": resolved or "unknown",
                    "token_source": "estimated",
                    **dict.fromkeys(TOKEN_FIELDS, 0),
                    "cost_micro_usd": None,
                    "cost_exact_micro_usd": None,
                    "cost_status": "unknown",
                    "price_snapshot_id": snap["id"],
                    "latency_ms": 0,
                    "attempt_number": prior + 1,
                    "status": "error",
                    "timestamp": pricing.now(),
                    "conversation_id": conversation_id or ctx.get("test_case_id", ""),
                    "in_flight": 1,
                    "reserved_micro_usd": math.ceil(reservation) if reservation is not None else 0,
                    "visibility": "external_bot" if opaque else "direct",
                    "note": "Call in progress; interrupted calls have unknown billing.",
                }
                conn.execute(
                    f"INSERT INTO usage_events ({','.join(event)}) VALUES ({','.join('?' for _ in event)})",
                    list(event.values()),
                )
            start = time.perf_counter()
            data = None
            status = "success"
            error = None
            try:
                data = await operation()
                return data
            except BaseException as exc:
                error = exc
                status = (
                    "timeout"
                    if isinstance(exc, (TimeoutError, asyncio.CancelledError))
                    or "timeout" in type(exc).__name__.lower()
                    else "error"
                )
                if retry >= retries or isinstance(exc, (asyncio.CancelledError, BudgetLimit)):
                    raise
            finally:
                latency = (time.perf_counter() - start) * 1000
                try:
                    counts = normalize(data, model)
                except ValueError:
                    counts = None
                source = "reported" if counts is not None else None
                if counts is None:
                    counts, source = await asyncio.to_thread(
                        count_text, resolved, messages, output_text(data), opaque, tokenizer
                    )
                amount, cost_status = pricing.calculate(
                    counts,
                    rates,
                    latency,
                    local,
                    config.cost_settings_snapshot.get("compute_usd_hour", "0"),
                )
                if status != "success" and source != "reported" and not local:
                    amount = None
                    cost_status = "unknown"
                note = ""
                if opaque:
                    note = (
                        "Visible interface only; hidden system prompts, retries, tools and "
                        "embeddings are not observable without bot "
                        "telemetry."
                    )
                if status != "success":
                    note += " Provider billing on this failed/timeout call is unknown unless usage was returned."
                update = {
                    **counts,
                    "token_source": source,
                    "latency_ms": round(latency, 3),
                    "cost_micro_usd": pricing.micro(amount) if amount is not None else None,
                    "cost_exact_micro_usd": str(amount) if amount is not None else None,
                    "cost_status": cost_status,
                    "status": status,
                    "in_flight": 0,
                    "reserved_micro_usd": 0,
                    "note": note,
                }
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE usage_events SET "
                        + ",".join(k + "=?" for k in update)
                        + " WHERE id=?",
                        list(update.values()) + [ident],
                    )
            if error:
                await asyncio.sleep(min(2**retry, 8))


async def call(operation, **kwargs):
    ctx = _context.get()
    if not ctx:
        return (
            await operation()
        )  # Read-only discovery / standalone connector smoke checks are outside runs.
    kwargs.setdefault("bot_slot", ctx.get("bot_slot"))
    return await Meter(ctx["config"], ctx["run_id"], ctx["mode"]).call(operation, **kwargs)


async def completion(url, body, key="", timeout=30):
    """One SDK request: SDK retries/fallbacks disabled; all retries belong to Meter."""
    from .connectors import validate_destination

    await validate_destination(url)
    if not urlsplit(url).path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("Use a complete OpenAI-compatible chat/completions URL.")
    if (
        "gemma-4" in body["model"].lower()
        and urlsplit(url).hostname == "generativelanguage.googleapis.com"
    ):
        from .gemma_native import completion as gemma_completion

        return await gemma_completion(
            body["model"],
            body["messages"],
            key,
            timeout,
            body.get("max_tokens", 1500),
            bool(body.get("response_format")),
        )
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import importlib

    litellm = await asyncio.to_thread(importlib.import_module, "litellm")
    litellm.telemetry = False
    litellm.suppress_debug_info = True
    provider = "anthropic" if urlsplit(url).hostname == "api.anthropic.com" else "openai"
    api_base = (
        "https://api.anthropic.com"
        if provider == "anthropic"
        else url.rstrip("/")[: -len("/chat/completions")]
    )
    request_body = dict(body)
    if provider == "anthropic":
        request_body.pop("response_format", None)
    data = await litellm.acompletion(
        **request_body,
        custom_llm_provider=provider,
        api_base=api_base,
        api_key=key or "local-no-key",
        timeout=timeout,
        num_retries=0,
        max_retries=0,
        caching=False,
    )
    return data.model_dump() if hasattr(data, "model_dump") else data
