"""Bot adapters. Each adapter opens a conversation with one chatbot and sends it messages.

Every bot in bots.json has a "type" that picks the adapter:
  voltkart           VoltKart-style API: POST {base_url}/api/chat {message, session_id, model}
  http               Any JSON chat API, described by a body template and the path to the reply
  sse_chat           Streaming (SSE) chat API that takes the history each turn (e.g. the Reliance multi-agent bot)
  supportflow        SupportFlow AI (Mouni's chatbot): JWT login + POST /api/chat {message, conversation_id}
  openai_compatible  Any OpenAI-style /chat/completions API (OpenAI, Ollama, vLLM, OpenRouter, Groq...)
  claude_bedrock     Claude on Amazon Bedrock with your own system prompt (e.g. a no-tools baseline)

Optional for every type: "max_concurrency" (parallel test chats, see evaluator.py), "timeout" (seconds per reply,
default BOT_TIMEOUT; raise it for a slow local model) and "fallback_replies":
phrases the bot only says when its own LLM call failed. Such a reply raises a BotError the evaluator treats as
blocked (retried, then left out of the score) instead of grading it as a real answer.

Traces (gray-box / white-box testing): besides the reply, an adapter records what it can see of the bot's insides,
as a dict with any of these keys (a missing key means the bot doesn't expose it):
  route      which agent / intent handled the turn (gray-box: the API already returns it)
  escalated  whether the turn was handed to a human (gray-box)
  tools      [{"name", "input"}] tool calls made for the reply (white-box)
  context    text the bot retrieved and answered from; "" = retrieved nothing (white-box)
White-box keys need the bot's opt-in debug output: set "trace": true on the bot in bots.json, which sends
"debug": true with each message (voltkart, sse_chat, supportflow).

Usage (cost per bot): an adapter also records the tokens behind each reply when the bot reports them, as
{"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"} (see normalize_usage). voltkart and
supportflow read a "usage" field in the reply, sse_chat a "usage" field in a meta/trace event, http the JSON at
"usage_path", and openai_compatible / claude_bedrock the API's own usage. A bot that reports nothing has no usage.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass

import anthropic
import httpx2
from anthropic import AnthropicBedrockMantle

TIMEOUT = float(os.environ.get("BOT_TIMEOUT", "120"))
MAX_CONTEXT = 8000  # characters of retrieved context kept per turn


class BotError(Exception):
    pass


@dataclass
class Reply:
    text: str
    latency_ms: int
    trace: dict | None = None
    usage: dict | None = None


# Names bots and APIs use for the same counts -> our names. Input excludes cached tokens where the API splits them.
USAGE_KEYS = {
    "input_tokens": "input_tokens", "prompt_tokens": "input_tokens", "inputTokens": "input_tokens",
    "prompt_token_count": "input_tokens", "promptTokenCount": "input_tokens",
    "output_tokens": "output_tokens", "completion_tokens": "output_tokens", "outputTokens": "output_tokens",
    "candidates_token_count": "output_tokens", "candidatesTokenCount": "output_tokens",
    "cache_read_tokens": "cache_read_tokens", "cache_read_input_tokens": "cache_read_tokens",
    "cacheReadInputTokens": "cache_read_tokens",
    "cache_write_tokens": "cache_write_tokens", "cache_creation_input_tokens": "cache_write_tokens",
    "cacheWriteInputTokens": "cache_write_tokens",
}


def normalize_usage(raw):
    """A bot's token counts in our names, or None when it reported none."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, v in raw.items():
        if k in USAGE_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[USAGE_KEYS[k]] = out.get(USAGE_KEYS[k], 0) + int(v)
    return out or None


def make_trace(route=None, escalated=None, tools=None, context=None, **extra):
    """A turn's trace without the keys the bot didn't expose (None)."""
    if isinstance(context, (dict, list)):
        context = json.dumps(context, ensure_ascii=False)
    if isinstance(context, str) and len(context) > MAX_CONTEXT:
        context = context[:MAX_CONTEXT] + " [...]"
    trace = {"route": route, "escalated": escalated, "tools": tools, "context": context, **extra}
    return {k: v for k, v in trace.items() if v is not None} or None


def _dig(data, path):
    """Follow a dotted path such as "choices.0.message.content" into parsed JSON."""
    for key in path.split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def _fill(template, values):
    """Replace "{message}" / "{session_id}" placeholders anywhere inside a JSON-like template."""
    if isinstance(template, str):
        for k, v in values.items():
            if template == "{" + k + "}":
                return v
            template = template.replace("{" + k + "}", str(v))
        return template
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    return template


def _headers(cfg):
    headers = dict(cfg.get("headers", {}))
    if cfg.get("api_key_env"):
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise BotError(f"Environment variable {cfg['api_key_env']} is not set")
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _json(r):
    try:
        return r.json()
    except ValueError as e:
        raise BotError(f"Bot returned non-JSON (HTTP {r.status_code}): {r.text[:200]}") from e


def _post(url, body, headers=None, timeout=None):
    try:
        r = httpx2.post(url, json=body, headers=headers or {}, timeout=timeout or TIMEOUT)
    except httpx2.HTTPError as e:
        raise BotError(f"Could not reach {url}: {e}") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail") or r.text
        except (ValueError, AttributeError):
            detail = r.text
        raise BotError(f"HTTP {r.status_code}: {str(detail)[:300]}")
    return _json(r)


class Conversation:
    """One conversation with one bot. Subclasses implement _send."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.debug = bool(cfg.get("trace"))
        self.trace = None  # set by _send
        self.usage = None  # set by _send when the bot reports its tokens

    def send(self, message: str) -> Reply:
        started = time.monotonic()
        self.trace = self.usage = None
        try:
            text = (self._send(message) or "").strip()
        except (KeyError, IndexError, TypeError) as e:  # reply JSON not shaped as expected
            raise BotError(f"Unexpected reply format: {type(e).__name__}: {e}") from e
        for phrase in self.cfg.get("fallback_replies", []):
            if phrase.lower() in text.lower():
                raise BotError(f"Bot's LLM call failed (fallback reply): {text[:150]}")
        return Reply(text=text, latency_ms=int((time.monotonic() - started) * 1000), trace=self.trace,
                     usage=normalize_usage(self.usage))

    def _send(self, message: str) -> str:
        raise NotImplementedError

    def close(self):
        pass


class VoltKartConversation(Conversation):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.session_id = None

    def _send(self, message):
        body = {"message": message, "session_id": self.session_id, "model": self.cfg["model"]}
        if self.debug:
            body["debug"] = True
        data = _post(f"{self.cfg['base_url'].rstrip('/')}/api/chat", body, timeout=self.cfg.get("timeout"))
        self.session_id = data["session_id"]
        self.usage = data.get("usage")
        if self.debug:  # an old server without debug output sends no trace: then nothing is observable
            calls = (data.get("trace") or {}).get("tools")
            if calls is not None:
                self.trace = make_trace(tools=[{"name": c["name"], "input": c.get("input")} for c in calls],
                                        context=[{"tool": c["name"], "output": c.get("output")} for c in calls] if calls else "")
        return data["reply"]

    def close(self):
        if self.session_id:
            try:
                httpx2.post(f"{self.cfg['base_url'].rstrip('/')}/api/reset",
                            json={"message": "", "session_id": self.session_id}, timeout=10)
            except httpx2.HTTPError:
                pass


class HttpConversation(Conversation):
    """Generic JSON API. Config:
    url, body (template using {message} and {session_id}), reply_path, optional session_path, usage_path + headers."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.session_id = str(uuid.uuid4())

    def _send(self, message):
        body = _fill(self.cfg.get("body", {"message": "{message}"}),
                     {"message": message, "session_id": self.session_id})
        data = _post(self.cfg["url"], body, _headers(self.cfg), timeout=self.cfg.get("timeout"))
        if self.cfg.get("session_path"):
            self.session_id = _dig(data, self.cfg["session_path"])
        if self.cfg.get("usage_path"):
            try:
                self.usage = _dig(data, self.cfg["usage_path"])
            except (KeyError, IndexError, TypeError):
                pass
        try:
            return str(_dig(data, self.cfg.get("reply_path", "reply")))
        except (KeyError, IndexError, TypeError):
            raise BotError(f"No reply at '{self.cfg.get('reply_path', 'reply')}' in response: {json.dumps(data)[:300]}")


class SSEChatConversation(Conversation):
    """Streaming (Server-Sent Events) chat API where the client sends the history each turn,
    e.g. the Reliance Digital multi-agent backend: POST /chat/stream {message, provider, history}.
    Config: url, optional body (extra fields), history_field, token_event, error_event, trace_events (events whose
    data describe the turn, default meta + trace) and trace_fields (trace key -> field in that data)."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.history = []

    def _send(self, message):
        body = {**self.cfg.get("body", {}), "message": message,
                self.cfg.get("history_field", "history"): self.history}
        if self.debug:
            body["debug"] = True
        token_event = self.cfg.get("token_event", "token")
        error_event = self.cfg.get("error_event", "error")
        trace_events = self.cfg.get("trace_events", ["meta", "trace"])
        pieces, event, info = [], None, {}
        try:
            with httpx2.stream("POST", self.cfg["url"], json=body, headers=_headers(self.cfg),
                               timeout=self.cfg.get("timeout") or TIMEOUT) as r:
                if r.status_code >= 400:
                    r.read()
                    raise BotError(f"HTTP {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        try:
                            data = json.loads(line[5:].strip() or "null")
                        except ValueError as e:
                            raise BotError(f"Malformed stream line: {line[:200]}") from e
                        if event == token_event:
                            pieces.append(data.get("text", "") if isinstance(data, dict) else str(data))
                        elif event in trace_events and isinstance(data, dict):
                            info.update(data)
                        elif event == error_event:
                            raise BotError(f"Bot error: {data.get('message', data) if isinstance(data, dict) else data}")
        except httpx2.HTTPError as e:
            raise BotError(f"Could not reach {self.cfg['url']}: {e}") from e
        text = "".join(pieces)
        self.usage = info.pop("usage", None)
        fields = {"route": "agent", "context": "retrieved", **self.cfg.get("trace_fields", {})}
        self.trace = make_trace(**{k: info.get(f) for k, f in fields.items()},
                                **{k: v for k, v in info.items() if k not in fields.values() and k != "provider"})
        self.history += [{"role": "user", "content": message}, {"role": "assistant", "content": text or "(no reply)"}]
        return text


class SupportFlowConversation(Conversation):
    """SupportFlow AI (Mouni's Flask bot): JWT login, then POST /api/chat {message, conversation_id}.
    The bot continues the customer's latest open conversation, so for this login only one test chat runs
    at a time, and each chat is retired (escalated) when it closes, so the next one starts fresh.
    Config: base_url, email, password. The GitHub version of 2026-10-06 has no escalate endpoint and no other way to
    end a chat, so for it set "db_path" (the bot's SQLite file; run it on a test copy) and chats are retired by
    marking them CLOSED there; set "handoff": false as it never hands chats to a human."""

    _tokens = {}
    _locks = {}
    _cleaned = set()
    _guard = threading.Lock()

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = cfg["base_url"].rstrip("/")
        self.key = (self.base, cfg["email"])
        with self._guard:
            self.lock = self._locks.setdefault(self.key, threading.Lock())
        self.conversation_id = None
        self.held = False

    def _token(self, refresh=False):
        if refresh or self.key not in self._tokens:
            data = _post(f"{self.base}/api/auth/login", {"email": self.cfg["email"], "password": self.cfg["password"]})
            self._tokens[self.key] = data["token"]
        return self._tokens[self.key]

    def _call(self, method, path, body=None):
        for refresh in (False, True):
            try:
                r = httpx2.request(method, f"{self.base}{path}", json=body, timeout=self.cfg.get("timeout") or TIMEOUT,
                                   headers={"Authorization": f"Bearer {self._token(refresh)}"})
            except httpx2.HTTPError as e:
                raise BotError(f"Could not reach {self.base}: {e}") from e
            if r.status_code not in (401, 422):  # 401/422 = expired or invalid token: log in again once
                break
        if r.status_code >= 400:
            raise BotError(f"HTTP {r.status_code}: {r.text[:300]}")
        return _json(r)

    def _retire(self, conversation_id):
        if db_path := self.cfg.get("db_path"):
            try:
                with closing(sqlite3.connect(os.path.expanduser(db_path), timeout=30)) as db, db:
                    db.execute("UPDATE conversations SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
                               (conversation_id,))
            except sqlite3.Error as e:
                raise BotError(f"Could not close chat {conversation_id} in {db_path}: {e}") from e
            return
        self._call("POST", f"/api/conversations/{conversation_id}/escalate")

    def _send(self, message):
        if not self.held:
            if not self.lock.acquire(timeout=float(self.cfg.get("busy_timeout", TIMEOUT))):
                # e.g. an arena battle still holds the chat: retried by the evaluator, then shown as blocked
                raise BotError("Bot is busy: another conversation with this login is still open")
            self.held = True
            if self.key not in self._cleaned:  # chats left open from earlier use would be continued
                for c in self._call("GET", "/api/conversations"):
                    if c["status"] in ("AI_ACTIVE", "WAITING_FOR_CUSTOMER"):
                        self._retire(c["id"])
                self._cleaned.add(self.key)
        body = {"message": message, "conversation_id": self.conversation_id}
        if self.debug:
            body["debug"] = True
        data = self._call("POST", "/api/chat", body)
        self.conversation_id = data["conversation_id"]
        used = str(data.get("model_used") or "")
        if used.endswith((":mock", "->mock")):  # every LLM failed and it answered offline ("mock" alone = greeting)
            raise BotError(f"Bot's LLM call failed (fallback reply, model_used={used}): {(data.get('reply') or '')[:150]}")
        self.usage = data.get("usage")
        escalated = data.get("escalate") if self.cfg.get("handoff", True) else None
        self.trace = make_trace(route=data.get("intent"), escalated=escalated,
                                context=(data.get("trace") or {}).get("context"),
                                priority=data.get("priority"), sentiment=data.get("sentiment"))
        return data.get("reply") or "(no reply: the chat was handed to a human agent)"

    def close(self):
        try:
            if self.conversation_id:
                self._retire(self.conversation_id)
        except BotError:
            self._cleaned.discard(self.key)  # clean up before the next chat instead
        finally:
            if self.held:
                self.held = False
                self.lock.release()


class OpenAICompatibleConversation(Conversation):
    """Keeps the history itself, because /chat/completions is stateless."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.messages = [{"role": "system", "content": cfg["system"]}] if cfg.get("system") else []

    def _send(self, message):
        self.messages.append({"role": "user", "content": message})
        data = _post(f"{self.cfg['base_url'].rstrip('/')}/chat/completions",
                     {"model": self.cfg["model"], "messages": self.messages}, _headers(self.cfg))
        text = data["choices"][0]["message"].get("content") or ""
        self.usage = data.get("usage")
        cached = ((self.usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        if cached:  # OpenAI counts cached tokens inside prompt_tokens
            self.usage = {**self.usage, "prompt_tokens": self.usage["prompt_tokens"] - cached, "cache_read_tokens": cached}
        self.messages.append({"role": "assistant", "content": text})
        return text


_bedrock_clients = {}


def bedrock_client(region=None):
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    if region not in _bedrock_clients:
        _bedrock_clients[region] = AnthropicBedrockMantle(aws_region=region)
    return _bedrock_clients[region]


class ClaudeBedrockConversation(Conversation):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.messages = []

    def _send(self, message):
        self.messages.append({"role": "user", "content": message})
        try:
            response = bedrock_client(self.cfg.get("region")).messages.create(
                model=self.cfg["model"],
                max_tokens=16000,
                system=self.cfg.get("system", "You are a helpful assistant."),
                messages=self.messages,
                output_config={"effort": self.cfg.get("effort", "low")},
            )
        except anthropic.APIStatusError as e:
            self.messages.pop()
            raise BotError(f"Bedrock error: {e.message}") from e
        except anthropic.APIConnectionError as e:
            self.messages.pop()
            raise BotError("Could not reach Amazon Bedrock") from e
        u = response.usage
        self.usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                      "cache_read_tokens": u.cache_read_input_tokens or 0,
                      "cache_write_tokens": u.cache_creation_input_tokens or 0}
        if response.stop_reason == "refusal":
            text = "(refused)"
        else:
            text = "".join(b.text for b in response.content if b.type == "text")
        self.messages.append({"role": "assistant", "content": text})
        return text


ADAPTERS = {
    "voltkart": VoltKartConversation,
    "http": HttpConversation,
    "sse_chat": SSEChatConversation,
    "supportflow": SupportFlowConversation,
    "openai_compatible": OpenAICompatibleConversation,
    "claude_bedrock": ClaudeBedrockConversation,
}


REQUIRED = {
    "voltkart": ["base_url", "model"],
    "http": ["url"],
    "sse_chat": ["url"],
    "supportflow": ["base_url", "email", "password"],
    "openai_compatible": ["base_url", "model"],
    "claude_bedrock": ["model"],
}


def validate(cfg):
    """Raise BotError naming what is wrong with one bots.json entry."""
    name = cfg.get("id", "?")
    adapter = ADAPTERS.get(cfg.get("type"))
    if adapter is None:
        raise BotError(f"Bot '{name}': unknown type '{cfg.get('type')}'. Use one of: {', '.join(ADAPTERS)}")
    missing = [k for k in ["id", "label", *REQUIRED[cfg["type"]]] if not cfg.get(k)]
    if missing:
        raise BotError(f"Bot '{name}' ({cfg['type']}) is missing: {', '.join(missing)}")
    if "max_concurrency" in cfg and not (isinstance(cfg["max_concurrency"], int) and cfg["max_concurrency"] >= 1):
        raise BotError(f"Bot '{name}': max_concurrency must be a whole number of at least 1")
    return adapter


def open_conversation(cfg) -> Conversation:
    return validate(cfg)(cfg)
