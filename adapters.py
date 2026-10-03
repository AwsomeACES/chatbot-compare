"""Bot adapters. Each adapter opens a conversation with one chatbot and sends it messages.

Every bot in bots.json has a "type" that picks the adapter:
  voltkart           VoltKart-style API: POST {base_url}/api/chat {message, session_id, model}
  http               Any JSON chat API, described by a body template and the path to the reply
  sse_chat           Streaming (SSE) chat API that takes the history each turn (e.g. the Reliance multi-agent bot)
  supportflow        SupportFlow AI (Mouni's bot): JWT login + POST /api/chat {message, conversation_id}
  openai_compatible  Any OpenAI-style /chat/completions API (OpenAI, Ollama, vLLM, OpenRouter, Groq...)
  claude_bedrock     Claude on Amazon Bedrock with your own system prompt (e.g. a no-tools baseline)
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass

import anthropic
import httpx2
from anthropic import AnthropicBedrockMantle

TIMEOUT = float(os.environ.get("BOT_TIMEOUT", "120"))


class BotError(Exception):
    pass


@dataclass
class Reply:
    text: str
    latency_ms: int


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


def _post(url, body, headers=None):
    try:
        r = httpx2.post(url, json=body, headers=headers or {}, timeout=TIMEOUT)
    except httpx2.HTTPError as e:
        raise BotError(f"Could not reach {url}: {e}") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail") or r.text
        except ValueError:
            detail = r.text
        raise BotError(f"HTTP {r.status_code}: {str(detail)[:300]}")
    return r.json()


class Conversation:
    """One conversation with one bot. Subclasses implement _send."""

    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, message: str) -> Reply:
        started = time.monotonic()
        text = self._send(message)
        return Reply(text=(text or "").strip(), latency_ms=int((time.monotonic() - started) * 1000))

    def _send(self, message: str) -> str:
        raise NotImplementedError

    def close(self):
        pass


class VoltKartConversation(Conversation):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.session_id = None

    def _send(self, message):
        data = _post(f"{self.cfg['base_url'].rstrip('/')}/api/chat",
                     {"message": message, "session_id": self.session_id, "model": self.cfg["model"]})
        self.session_id = data["session_id"]
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
    url, body (template using {message} and {session_id}), reply_path, optional session_path + headers."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.session_id = str(uuid.uuid4())

    def _send(self, message):
        body = _fill(self.cfg.get("body", {"message": "{message}"}),
                     {"message": message, "session_id": self.session_id})
        data = _post(self.cfg["url"], body, _headers(self.cfg))
        if self.cfg.get("session_path"):
            self.session_id = _dig(data, self.cfg["session_path"])
        try:
            return str(_dig(data, self.cfg.get("reply_path", "reply")))
        except (KeyError, IndexError, TypeError):
            raise BotError(f"No reply at '{self.cfg.get('reply_path', 'reply')}' in response: {json.dumps(data)[:300]}")


class SSEChatConversation(Conversation):
    """Streaming (Server-Sent Events) chat API where the client sends the history each turn,
    e.g. the Reliance Digital multi-agent backend: POST /chat/stream {message, provider, history}.
    Config: url, optional body (extra fields), history_field, token_event, error_event."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.history = []

    def _send(self, message):
        body = {**self.cfg.get("body", {}), "message": message,
                self.cfg.get("history_field", "history"): self.history}
        token_event = self.cfg.get("token_event", "token")
        error_event = self.cfg.get("error_event", "error")
        pieces, event = [], None
        try:
            with httpx2.stream("POST", self.cfg["url"], json=body, headers=_headers(self.cfg),
                               timeout=TIMEOUT) as r:
                if r.status_code >= 400:
                    r.read()
                    raise BotError(f"HTTP {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:].strip() or "null")
                        if event == token_event:
                            pieces.append(data.get("text", "") if isinstance(data, dict) else str(data))
                        elif event == error_event:
                            raise BotError(f"Bot error: {data.get('message', data) if isinstance(data, dict) else data}")
        except httpx2.HTTPError as e:
            raise BotError(f"Could not reach {self.cfg['url']}: {e}") from e
        text = "".join(pieces)
        self.history += [{"role": "user", "content": message}, {"role": "assistant", "content": text or "(no reply)"}]
        return text


class SupportFlowConversation(Conversation):
    """SupportFlow AI (Mouni's Flask bot): JWT login, then POST /api/chat {message, conversation_id}.
    The bot continues the customer's latest open conversation, so for this login only one test chat runs
    at a time, and each chat is retired (escalated) when it closes, so the next one starts fresh.
    Config: base_url, email, password."""

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
                r = httpx2.request(method, f"{self.base}{path}", json=body, timeout=TIMEOUT,
                                   headers={"Authorization": f"Bearer {self._token(refresh)}"})
            except httpx2.HTTPError as e:
                raise BotError(f"Could not reach {self.base}: {e}") from e
            if r.status_code not in (401, 422):  # 401/422 = expired or invalid token: log in again once
                break
        if r.status_code >= 400:
            raise BotError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def _retire(self, conversation_id):
        self._call("POST", f"/api/conversations/{conversation_id}/escalate")

    def _send(self, message):
        if not self.held:
            if not self.lock.acquire(timeout=TIMEOUT):
                raise BotError("Another conversation with this bot is still open")
            self.held = True
            if self.key not in self._cleaned:  # chats left open from earlier use would be continued
                for c in self._call("GET", "/api/conversations"):
                    if c["status"] in ("AI_ACTIVE", "WAITING_FOR_CUSTOMER"):
                        self._retire(c["id"])
                self._cleaned.add(self.key)
        data = self._call("POST", "/api/chat", {"message": message, "conversation_id": self.conversation_id})
        self.conversation_id = data["conversation_id"]
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


def open_conversation(cfg) -> Conversation:
    adapter = ADAPTERS.get(cfg["type"])
    if adapter is None:
        raise BotError(f"Unknown bot type '{cfg['type']}'. Use one of: {', '.join(ADAPTERS)}")
    return adapter(cfg)
