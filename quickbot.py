"""Add a bot by pasting its URL: find out how to talk to it, then save it to bots.quick.json.

detect() sends one "Hi" to the URL and tries, in order:
  openai_compatible  a URL ending in /chat/completions or /v1 (the model comes from /models when not given)
  http               a JSON chat API: the message under a common field name (message, query, question, prompt,
                     input, text) and the reply at a common path (reply, response, answer, ..., choices.0.message.content)
  sse_chat           a streaming (text/event-stream) API: the event that carries the reply's text
  web_widget         a web page with a chat box: a common message box, and the bot's messages found by what appeared
                     after sending (common class names: bot, assistant, response...)
A bare host (http://localhost:5000) is also tried at /api/chat, /chat and /v1/chat/completions. Anything else (a login,
a custom body, a widget with unusual markup) needs the bot written into bots.json by hand; detect() says what it tried.

Quick bots go in bots.quick.json (not bots.json, whose hand-made layout is kept) and have no store profile, so
they run the "Generic chatbot safety and quality" suite.
"""

import json
import os
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx2

from adapters import BotError, bot_key_allowed, normalize_usage, open_conversation, validate

ROOT = os.path.dirname(os.path.abspath(__file__))
QUICK_FILE = os.path.join(ROOT, "bots.quick.json")
TIMEOUT = float(os.environ.get("QUICK_TIMEOUT", "60"))
HELLO = "Hi"
MESSAGE_FIELDS = ["message", "query", "question", "prompt", "input", "text"]
REPLY_PATHS = ["reply", "response", "answer", "message", "text", "output", "content", "result",
               "data.reply", "data.response", "data.answer", "data.message", "data.text",
               "choices.0.message.content", "message.content", "output.text"]
SESSION_FIELDS = ["session_id", "conversation_id", "thread_id", "chat_id", "sessionId", "conversationId", "threadId"]
EXTRA_PATHS = ["/api/chat", "/chat", "/v1/chat/completions"]
INPUT_SELECTORS = ["textarea", "input[type=text]", "input:not([type])", "[contenteditable=true]"]
REPLY_SELECTORS = ['[data-role="assistant"]', '[data-author="bot"]', '[class*="assistant"]', '[class*="bot-message"]',
                   '[class*="bot_message"]', '[class*="message--bot"]', '[class*="from-bot"]', '[class*="bot"]',
                   '[class*="response"]', '[class*="reply"]']


def _dig(data, path):
    for key in path.split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def _reply_path(data):
    for path in REPLY_PATHS:
        try:
            v = _dig(data, path)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if isinstance(v, str) and v.strip():
            return path
    return None


def _headers(api_key_env):
    if api_key_env and not bot_key_allowed(api_key_env):
        raise BotError(f"Name the key variable BOT_... (e.g. BOT_MYBOT_API_KEY) or list it in BOT_KEY_VARS; "
                       f"{api_key_env} can't be sent to a bot added by URL")
    if not api_key_env:
        return {}
    key = os.environ.get(api_key_env, "").strip()
    if not key:
        raise BotError(f"Environment variable {api_key_env} is not set (add it to .env and restart)")
    return {"Authorization": f"Bearer {key}"}


def _with_path(url, path):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, path, "", ""))


def _openai(url, model, api_key_env, client):
    base = re.sub(r"/chat/completions/?$", "", url.rstrip("/"))
    headers = _headers(api_key_env)
    if not model:
        r = client.get(f"{base}/models", headers=headers, timeout=TIMEOUT)
        ids = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)] if r.status_code < 400 else []
        if not ids:
            raise BotError(f"{base}/models listed no model: give the model id")
        model = ids[0]
    cfg = {"type": "openai_compatible", "base_url": base, "model": model,
           **({"api_key_env": api_key_env} if api_key_env else {})}
    return cfg, f"OpenAI-compatible API, model {model}"


def _sse(url, field, body, response_lines):
    """The event whose data carries the text: the most frequent named event with string or {"text"} data."""
    counts, event = {}, None
    for line in response_lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event:
            try:
                data = json.loads(line[5:].strip() or "null")
            except ValueError:
                continue
            if isinstance(data, str) or (isinstance(data, dict) and isinstance(data.get("text"), str)):
                counts[event] = counts.get(event, 0) + 1
    if not counts:
        return None
    token = max(counts, key=counts.get)
    extra = {k: v for k, v in body.items() if k not in (field,)}
    return {"type": "sse_chat", "url": url, "token_event": token, **({"body": extra} if extra else {})}


def _json_api(url, api_key_env, client):
    """POST a greeting under each common field name until a reply comes back. Returns (cfg, how) or None."""
    headers = _headers(api_key_env)
    tried = []
    for field in MESSAGE_FIELDS:
        sid = str(uuid.uuid4())
        body = {field: HELLO, "session_id": sid}
        try:
            with client.stream("POST", url, json=body, headers=headers, timeout=TIMEOUT) as r:
                kind = r.headers.get("content-type", "")
                if r.status_code >= 400:
                    r.read()
                    tried.append(f"{field}: HTTP {r.status_code}")
                    if r.status_code in (401, 403):
                        raise BotError(f"{url} needs authentication (HTTP {r.status_code}): give the environment "
                                       "variable holding its API key")
                    if r.status_code in (404, 405):
                        return None, tried  # no chat endpoint here
                    continue
                if "text/event-stream" in kind:
                    cfg = _sse(url, field, body, list(r.iter_lines()))
                    if cfg:
                        if field != "message":
                            tried.append(f"stream needs '{field}', but sse_chat sends 'message': add it by hand")
                            return None, tried
                        return ({**cfg, **({"api_key_env": api_key_env} if api_key_env else {})},
                                f"streaming (SSE) API, text in '{cfg['token_event']}' events"), tried
                    continue
                r.read()
        except httpx2.HTTPError as e:
            raise BotError(f"Could not reach {url}: {e}") from e
        try:
            data = r.json()
        except ValueError:
            tried.append(f"{field}: not JSON")
            continue
        path = _reply_path(data)
        if not path:
            tried.append(f"{field}: no reply at a known path in {json.dumps(data)[:150]}")
            continue
        session = next((k for k in SESSION_FIELDS if isinstance(data, dict) and data.get(k)), None)
        cfg = {"type": "http", "url": url, "body": {field: "{message}", (session or "session_id"): "{session_id}"},
               "reply_path": path, **({"session_path": session} if session else {}),
               **({"usage_path": "usage"} if isinstance(data, dict) and normalize_usage(data.get("usage")) else {}),
               **({"api_key_env": api_key_env} if api_key_env else {})}
        return (cfg, f"JSON API: message in '{field}', reply at '{path}'"
                + (f", session kept in '{session}'" if session else "")), tried
    return None, tried


def _widget(url):
    """Find a chat box on the page and where the bot's replies appear. Returns (cfg, how) or None."""
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        return None
    path = os.environ.get("CHROME_PATH")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **({"executable_path": path} if path else {}))
        try:
            page = browser.new_page()
            page.goto(url, timeout=int(TIMEOUT * 1000))
            box = next((s for s in INPUT_SELECTORS if page.locator(s).first.is_visible()), None)
            if not box:
                return None
            before = {s: page.locator(s).count() for s in REPLY_SELECTORS}
            page.locator(box).first.fill(HELLO)
            page.locator(box).first.press("Enter")
            for _ in range(int(TIMEOUT * 2)):
                page.wait_for_timeout(500)
                for s in REPLY_SELECTORS:
                    loc = page.locator(s)
                    if loc.count() > before[s] and (loc.last.inner_text() or "").strip():
                        cfg = {"type": "web_widget", "url": url, "input_selector": box, "reply_selector": s,
                               "max_concurrency": 1}
                        return cfg, f"chat widget on a web page (message box {box}, replies {s})"
            return None
        except PlaywrightError:
            return None
        finally:
            browser.close()


def detect(url, model=None, api_key_env=None, client=httpx2, widget=_widget):
    """How to talk to the bot at url: {"config", "how", "reply"}, after a real test message. Raises BotError."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise BotError("Give the bot's full URL, starting with http:// or https://")
    found, tried = None, []
    if re.search(r"/(chat/completions|v1)/?$", url):
        found = _openai(url, model, api_key_env, client)
    else:
        try:
            page = client.get(url, timeout=TIMEOUT, follow_redirects=True)
            is_page = page.status_code < 400 and "text/html" in page.headers.get("content-type", "")
        except httpx2.HTTPError as e:
            raise BotError(f"Could not reach {url}: {e}") from e
        candidates = [url] + ([_with_path(url, p) for p in EXTRA_PATHS] if urlsplit(url).path in ("", "/") else [])
        for c in candidates:
            if c.endswith("/chat/completions"):
                try:
                    found = _openai(c, model, api_key_env, client)
                except (BotError, httpx2.HTTPError, ValueError) as e:
                    tried.append(f"{c}: {e}")
                    continue
            else:
                found, t = _json_api(c, api_key_env, client)
                tried += [f"{c} {x}" for x in t]
            if found:
                break
        if not found and is_page:
            found = widget(url)
            if not found:
                tried.append(f"{url}: a web page, but no chat box and bot replies with common markup were found")
    if not found:
        raise BotError("Could not work out how to chat with this bot. Tried: " + "; ".join(tried or ["nothing answered"])
                       + ". Add it to bots.json by hand (see README, 'Adding another bot').")
    cfg, how = found
    conv = open_conversation({"id": "detect", "label": "detect", **cfg})
    try:
        reply = conv.send(HELLO)
    finally:
        conv.close()
    return {"config": cfg, "how": how, "reply": reply.text[:300], "latency_ms": reply.latency_ms}


def load():
    try:
        with open(QUICK_FILE) as f:
            return json.load(f).get("bots", [])
    except FileNotFoundError:
        return []


def _write(bots):
    tmp = QUICK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"_about": "Bots added from the dashboard by URL (quickbot.py). Edit or move them into bots.json.",
                   "bots": bots}, f, indent=2)
        f.write("\n")
    os.replace(tmp, QUICK_FILE)


def add(label, cfg, taken_ids):
    """Save a detected bot. Returns its bots.json-style entry."""
    label = (label or "").strip()[:60]
    if not label:
        raise BotError("Give the bot a name")
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "bot"
    bot_id, n = f"quick-{slug}", 2
    while bot_id in taken_ids:
        bot_id, n = f"quick-{slug}-{n}", n + 1
    allowed = {"type", "url", "base_url", "model", "api_key_env", "body", "reply_path", "session_path", "usage_path",
               "token_event", "input_selector", "reply_selector", "max_concurrency"}
    bot = {"id": bot_id, "label": label, **{k: v for k, v in cfg.items() if k in allowed},
           "description": "Added by URL from the dashboard", "quick": True}
    validate(bot)
    if bot.get("api_key_env") and not bot_key_allowed(bot["api_key_env"]):
        raise BotError(f"Name the key variable BOT_... or list it in BOT_KEY_VARS, not {bot['api_key_env']}")
    _write(load() + [bot])
    return bot


def remove(bot_id):
    bots = load()
    if not any(b["id"] == bot_id for b in bots):
        raise KeyError(bot_id)
    _write([b for b in bots if b["id"] != bot_id])
