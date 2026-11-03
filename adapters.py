"""Bot adapters. Each adapter opens a conversation with one chatbot and sends it messages.

Every bot in bots.json has a "type" that picks the adapter:
  voltkart           VoltKart-style API: POST {base_url}/api/chat {message, session_id, model}
  http               Any JSON chat API, described by a body template and the path to the reply
  sse_chat           Streaming (SSE) chat API that takes the history each turn (e.g. the Reliance multi-agent bot)
  supportflow        SupportFlow AI (Mouni's chatbot): JWT login + POST /api/chat {message, conversation_id}
  openai_compatible  Any OpenAI-style /chat/completions API (OpenAI, Ollama, vLLM, OpenRouter, Groq...)
  claude_bedrock     Claude on Amazon Bedrock with your own system prompt (e.g. a no-tools baseline)
  web_widget         A chat widget on a web page, driven in a real browser (Playwright), for a bot with no API:
                     "url", "input_selector" (the message box), "reply_selector" (each bot message); optional
                     "send_selector" (else Enter), "open_selector" (a launcher button to click first),
                     "settle_ms" (how long the last reply must stay unchanged, default 1500), "headless" (default
                     true) and "browser_path" (else CHROME_PATH, else Playwright's own Chromium). Needs the
                     playwright package; a login, CAPTCHA or a selector that matches nothing ends the case with a
                     clear error. Use "max_concurrency": 1 or 2: every chat is its own browser.

Optional for every type: "max_concurrency" (parallel test chats, see evaluator.py), "timeout" (seconds per reply,
default BOT_TIMEOUT; raise it for a slow local model) and "fallback_replies":
phrases the bot only says when its own LLM call failed. Such a reply raises a BotError the evaluator retries; if it
persists the case is an error (scored as a fail, since that's what a customer got), never graded as a real answer.

Traces (gray-box / white-box testing): besides the reply, an adapter records what it can see of the bot's insides,
as a dict with any of these keys (a missing key means the bot doesn't expose it):
  route      which agent / intent handled the turn (gray-box: the API already returns it; VoltKart's route is
             the kind of lookup its reply started with: product, order, policy or chat)
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
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass

import httpx2

log = logging.getLogger("adapters")

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


def bot_key_allowed(name):
    """May a bot added by URL send this environment variable as its API key? Only names meant for bots: BOT_* or
    one listed in BOT_KEY_VARS. Otherwise anyone at the dashboard could paste their own URL and name GOOGLE_API_KEY,
    NVIDIA_API_KEY or an AWS secret, and this app would send that secret to them."""
    listed = {v.strip() for v in os.environ.get("BOT_KEY_VARS", "").split(",") if v.strip()}
    return bool(name) and (name in listed or (name.startswith("BOT_") and name.replace("_", "").isalnum()
                                               and name.upper() == name))


def _headers(cfg):
    headers = dict(cfg.get("headers", {}))
    if cfg.get("quick") and cfg.get("api_key_env") and not bot_key_allowed(cfg["api_key_env"]):
        raise BotError(f"A bot added by URL can only use a key variable named BOT_... (or listed in BOT_KEY_VARS), "
                       f"not {cfg['api_key_env']}")
    if cfg.get("api_key_env"):
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise BotError(f"Environment variable {cfg['api_key_env']} is not set")
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _password(cfg):
    if env := cfg.get("password_env"):
        if not os.environ.get(env):
            raise BotError(f"Environment variable {env} is not set (the bot's test login password)")
        return os.environ[env]
    return cfg["password"]


def _json(r):
    try:
        return r.json()
    except ValueError as e:
        raise BotError(f"Bot returned non-JSON (HTTP {r.status_code}): {r.text[:200]}") from e


def _post(url, body, headers=None, timeout=None):
    return _json(_post_response(url, body, headers, timeout))


def _post_response(url, body, headers=None, timeout=None):
    """The response itself (for its cookies), after the same error handling as _post."""
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
    return r


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
    """VoltKart's /api/chat. Since AIRM-157 a conversation belongs to the owner cookie ("chat_owner") VoltKart sets
    on its first reply: later turns and /api/reset without it answer 404, so the cookies it sets are kept and sent
    back. Its tool calls (white-box) come only with the X-Debug-Token header matching the server's DEBUG_TOKEN:
    with "trace" on, the token is read from the env var named in "debug_token_env"."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.session_id = None
        self.cookies = {}
        self._warned = False

    def _headers(self):
        headers = {}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if self.debug and (token := os.environ.get(self.cfg.get("debug_token_env") or "", "")):
            headers["X-Debug-Token"] = token
        return headers

    def _keep_cookies(self, r):
        jar = getattr(r, "cookies", None)
        if jar:
            self.cookies.update(dict(jar.items()) if hasattr(jar, "items") else jar)

    def _send(self, message):
        body = {"message": message, "session_id": self.session_id, "model": self.cfg["model"]}
        if self.debug:
            body["debug"] = True
        r = _post_response(f"{self.cfg['base_url'].rstrip('/')}/api/chat", body, headers=self._headers(),
                           timeout=self.cfg.get("timeout"))
        self._keep_cookies(r)
        data = _json(r)
        self.session_id = data["session_id"]
        self.usage = data.get("usage")
        calls = (data.get("trace") or {}).get("tools") if self.debug else None
        if self.debug and calls is None and not self._warned:  # asked for tool calls, got none: token missing/wrong
            self._warned = True
            log.warning("%s: trace is on but VoltKart sent no tool calls; set %s to the server's DEBUG_TOKEN",
                        self.cfg.get("id"), self.cfg.get("debug_token_env") or "debug_token_env")
        # route (gray-box) comes with every reply; tools need debug output (an old server sends neither)
        self.trace = make_trace(route=data.get("route"),
                                tools=None if calls is None else [{"name": c["name"], "input": c.get("input")} for c in calls],
                                context=None if calls is None else
                                [{"tool": c["name"], "output": c.get("output")} for c in calls] if calls else "")
        return data["reply"]

    def close(self):
        if self.session_id:
            url = f"{self.cfg['base_url'].rstrip('/')}/api/reset"
            try:
                r = httpx2.post(url, json={"message": "", "session_id": self.session_id}, headers=self._headers(),
                                timeout=10)
                if r.status_code >= 400:
                    log.warning("%s: reset of session %s answered HTTP %s", self.cfg.get("id"), self.session_id,
                                r.status_code)
            except httpx2.HTTPError as e:
                log.warning("%s: reset of session %s failed: %s", self.cfg.get("id"), self.session_id, e)


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
    For this login only one test chat runs at a time, and each chat is closed when it ends, so the next one starts
    fresh. Config: base_url, email, and password_env (the .env variable holding the test login's password; "password"
    in bots.json still works). Chats are closed with "close_path" (her main since 2026-10-23 has
    /api/conversations/{id}/close; older versions had /api/conversations/{id}/escalate, the default). Her 2026-10-09
    version had no way to end a chat: for it set "db_path" (the bot's SQLite file) and no "close_path", and chats are
    marked CLOSED there. That writes into the system under test, so it is only done on a test database: the file name
    must contain "test" (e.g. compare-test.db), and only conversations this login opened are touched. Set "handoff":
    false for a version that never hands chats to a human.
    Her bot acts on what it's told (cancels an order, opens a return), so one case would change the data the next ones
    are graded against. With "db_path" and "restore_tables", those tables are copied before the first chat and put
    back before and after every later one, so each case starts from the same data."""

    _tokens = {}
    _locks = {}
    _cleaned = set()
    _snapshots = {}
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
            data = _post(f"{self.base}/api/auth/login", {"email": self.cfg["email"], "password": _password(self.cfg)})
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

    def _test_db(self):
        db_path = self.cfg["db_path"]
        if "test" not in os.path.basename(db_path).lower():
            raise BotError(f"Won't write to {db_path}: the bot's data is only changed directly in a test database "
                           "(a file name with \"test\" in it, e.g. compare-test.db)")
        return closing(sqlite3.connect(os.path.expanduser(db_path), timeout=30))

    def _restore(self):
        """Puts the "restore_tables" back as they were before this process's first chat (see the class docstring)."""
        tables = self.cfg.get("restore_tables")
        if not tables or not self.cfg.get("db_path"):
            return
        try:
            with self._test_db() as db, db:
                if self.key not in self._snapshots:
                    self._snapshots[self.key] = {t: db.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables}
                    return
                for t, rows in self._snapshots[self.key].items():
                    db.execute(f'DELETE FROM "{t}"')
                    if rows:
                        db.executemany(f'INSERT INTO "{t}" VALUES ({",".join("?" * len(rows[0]))})', rows)
        except sqlite3.Error as e:
            raise BotError(f"Could not restore {', '.join(tables)} in {self.cfg['db_path']}: {e}") from e

    def _retire(self, conversation_id):
        if self.cfg.get("db_path") and not self.cfg.get("close_path"):
            try:
                with self._test_db() as db, db:
                    db.execute("UPDATE conversations SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP WHERE id = ? "
                               "AND customer_id = (SELECT id FROM users WHERE email = ?)",
                               (conversation_id, self.cfg["email"]))
            except sqlite3.Error as e:
                raise BotError(f"Could not close chat {conversation_id} in {self.cfg['db_path']}: {e}") from e
            return
        self._call("POST", self.cfg.get("close_path", "/api/conversations/{id}/escalate").format(id=conversation_id))

    def _send(self, message):
        if not self.held:
            if not self.lock.acquire(timeout=float(self.cfg.get("busy_timeout", TIMEOUT))):
                # e.g. an arena battle still holds the chat: retried by the evaluator, then shown as blocked
                raise BotError("Bot is busy: another conversation with this login is still open")
            self.held = True
            if self.key not in self._cleaned:  # chats left open from earlier use would be continued
                for c in self._call("GET", "/api/conversations"):
                    if c["status"] in ("AI_ACTIVE", "WAITING_FOR_CUSTOMER", "WAITING_FOR_AGENT", "AGENT_ACTIVE"):
                        self._retire(c["id"])
                self._cleaned.add(self.key)
            self._restore()
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
                try:
                    self._restore()
                except BotError:
                    pass  # restored again before the next chat
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
                     {"model": self.cfg["model"], "messages": self.messages}, _headers(self.cfg),
                     timeout=self.cfg.get("timeout"))
        text = data["choices"][0]["message"].get("content") or ""
        self.usage = data.get("usage")
        cached = ((self.usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        if cached:  # OpenAI counts cached tokens inside prompt_tokens
            self.usage = {**self.usage, "prompt_tokens": self.usage["prompt_tokens"] - cached, "cache_read_tokens": cached}
        self.messages.append({"role": "assistant", "content": text})
        return text


_bedrock_clients = {}


def bedrock_client(region=None):
    from anthropic import AnthropicBedrockMantle  # imported here: the SDK takes seconds to load, and few bots use it

    region = region or os.environ.get("AWS_REGION", "us-east-1")
    if region not in _bedrock_clients:
        _bedrock_clients[region] = AnthropicBedrockMantle(aws_region=region)
    return _bedrock_clients[region]


class ClaudeBedrockConversation(Conversation):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.messages = []

    def _send(self, message):
        import anthropic

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


class WebWidgetConversation(Conversation):
    """A chat widget on a web page, driven in its own headless browser. A reply is every bot message that appeared
    after ours, once the last one has stopped changing (widgets stream text in)."""

    def __init__(self, cfg):
        super().__init__(cfg)
        try:
            from playwright.sync_api import Error as PlaywrightError, sync_playwright
        except ImportError as e:
            raise BotError("web_widget bots need Playwright: .venv/bin/pip install playwright") from e
        self._error = PlaywrightError
        self.timeout_ms = int(1000 * float(cfg.get("timeout", TIMEOUT)))
        self.settle_ms = int(cfg.get("settle_ms", 1500))
        self._pw = sync_playwright().start()
        try:
            path = cfg.get("browser_path") or os.environ.get("CHROME_PATH")
            self._browser = self._pw.chromium.launch(headless=cfg.get("headless", True),
                                                     **({"executable_path": path} if path else {}))
            self.page = self._browser.new_page()
            self.page.goto(cfg["url"], timeout=self.timeout_ms)
            if cfg.get("open_selector"):
                self.page.click(cfg["open_selector"], timeout=self.timeout_ms)
            self.page.wait_for_selector(cfg["input_selector"], state="visible", timeout=min(self.timeout_ms, 30000))
        except self._error as e:
            self.close()
            raise BotError(f"Chat widget not usable at {cfg['url']} (login, CAPTCHA or a selector that matches "
                           f"nothing?): {str(e).splitlines()[0][:200]}") from e
        except Exception:
            self.close()
            raise

    def _texts(self):
        return [t.strip() for t in self.page.locator(self.cfg["reply_selector"]).all_inner_texts()]

    def _send(self, message):
        before = len(self._texts())
        try:
            box = self.page.locator(self.cfg["input_selector"]).first
            box.fill(message, timeout=10000)
            if self.cfg.get("send_selector"):
                self.page.click(self.cfg["send_selector"], timeout=10000)
            else:
                box.press("Enter")
        except self._error as e:
            raise BotError(f"Could not send the message in the widget: {str(e).splitlines()[0][:200]}") from e
        deadline = time.monotonic() + self.timeout_ms / 1000
        last, stable_since = None, None
        while time.monotonic() < deadline:
            texts = self._texts()
            new = [t for t in texts[before:] if t]
            if new:
                if new != last:
                    last, stable_since = new, time.monotonic()
                elif (time.monotonic() - stable_since) * 1000 >= self.settle_ms:
                    return "\n".join(new)
            self.page.wait_for_timeout(200)
        if last:
            return "\n".join(last)  # still changing at the timeout: take what is there
        raise BotError(f"No reply in the widget within {self.timeout_ms // 1000}s (reply_selector "
                       f"{self.cfg['reply_selector']!r} found no new message)")

    def close(self):
        for thing in ("_browser", "_pw"):
            obj = getattr(self, thing, None)
            if obj is not None:
                try:
                    obj.close() if thing == "_browser" else obj.stop()
                except Exception:
                    pass
                setattr(self, thing, None)


ADAPTERS = {
    "voltkart": VoltKartConversation,
    "http": HttpConversation,
    "sse_chat": SSEChatConversation,
    "supportflow": SupportFlowConversation,
    "openai_compatible": OpenAICompatibleConversation,
    "claude_bedrock": ClaudeBedrockConversation,
    "web_widget": WebWidgetConversation,
}


REQUIRED = {
    "voltkart": ["base_url", "model"],
    "http": ["url"],
    "sse_chat": ["url"],
    "supportflow": ["base_url", "email"],
    "openai_compatible": ["base_url", "model"],
    "claude_bedrock": ["model"],
    "web_widget": ["url", "input_selector", "reply_selector"],
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
    if cfg["type"] == "supportflow" and not (cfg.get("password") or cfg.get("password_env")):
        raise BotError(f"Bot '{name}' (supportflow) is missing: password_env (or password)")
    if "max_concurrency" in cfg and not (isinstance(cfg["max_concurrency"], int) and cfg["max_concurrency"] >= 1):
        raise BotError(f"Bot '{name}': max_concurrency must be a whole number of at least 1")
    return adapter


def open_conversation(cfg) -> Conversation:
    return validate(cfg)(cfg)
