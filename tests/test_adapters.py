"""Adapters against fake bot servers: request shape, trace capture, error handling."""

import json

import pytest

import adapters
from adapters import BotError, make_trace, open_conversation, validate


class FakeResponse:
    def __init__(self, status_code=200, data=None, lines=()):
        self.status_code, self._data, self._lines = status_code, data, list(lines)
        self.text = json.dumps(data) if data is not None else ""

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def iter_lines(self):
        return iter(self._lines)

    def read(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def http(monkeypatch):
    """Records requests and replies with whatever the test queues up."""
    calls, queue = [], []

    def respond(method, url, json=None, **kw):
        calls.append({"method": method, "url": url, "json": json, "headers": kw.get("headers")})
        r = queue.pop(0)
        return r(json) if callable(r) else r

    monkeypatch.setattr(adapters.httpx2, "post", lambda url, json=None, **kw: respond("POST", url, json, **kw))
    monkeypatch.setattr(adapters.httpx2, "request", lambda method, url, json=None, **kw: respond(method, url, json, **kw))
    monkeypatch.setattr(adapters.httpx2, "stream", lambda method, url, json=None, **kw: respond(method, url, json, **kw))
    return calls, queue


VOLTKART = {"id": "v", "label": "V", "type": "voltkart", "base_url": "http://bot", "model": "m"}


def test_validate_names_the_problem():
    with pytest.raises(BotError, match="unknown type"):
        validate({"id": "x", "label": "X", "type": "nope"})
    with pytest.raises(BotError, match="missing: model"):
        validate({"id": "x", "label": "X", "type": "voltkart", "base_url": "http://b"})
    with pytest.raises(BotError, match="max_concurrency"):
        validate({**VOLTKART, "max_concurrency": 0})


def test_make_trace_drops_hidden_keys_and_truncates_context():
    assert make_trace() is None
    assert make_trace(route="sales_agent") == {"route": "sales_agent"}
    assert make_trace(context="")["context"] == ""  # "retrieved nothing" is kept
    long = make_trace(context="x" * (adapters.MAX_CONTEXT + 50))["context"]
    assert len(long) == adapters.MAX_CONTEXT + len(" [...]")


def test_voltkart_keeps_the_session_and_sends_no_debug_by_default(http):
    calls, queue = http
    queue += [FakeResponse(data={"session_id": "s1", "reply": "Hi"}),
              FakeResponse(data={"session_id": "s1", "reply": "Rs 47,990"})]
    conv = open_conversation(VOLTKART)
    assert conv.send("hello").trace is None
    conv.send("price?")
    assert calls[0]["json"] == {"message": "hello", "session_id": None, "model": "m"}
    assert calls[1]["json"]["session_id"] == "s1"


def test_voltkart_white_box_trace(http):
    calls, queue = http
    steps = [{"id": "t1", "name": "search_products", "input": {"query": "tv"}, "output": [{"price": 47990}]}]
    queue.append(FakeResponse(data={"session_id": "s", "reply": "Rs 47,990", "trace": {"tools": steps}}))
    reply = open_conversation({**VOLTKART, "trace": True}).send("price?")
    assert calls[0]["json"]["debug"] is True
    assert reply.trace["tools"] == [{"name": "search_products", "input": {"query": "tv"}}]
    assert "47990" in reply.trace["context"]


def test_voltkart_gray_box_route_without_debug(http):
    calls, queue = http
    queue.append(FakeResponse(data={"session_id": "s", "reply": "Out for delivery", "route": "order"}))
    reply = open_conversation(VOLTKART).send("where is ORD10002?")
    assert "debug" not in calls[0]["json"]
    assert reply.trace == {"route": "order"}


def test_voltkart_with_no_tool_calls_retrieved_nothing(http):
    _, queue = http
    queue.append(FakeResponse(data={"session_id": "s", "reply": "Hello!", "trace": {"tools": []}}))
    assert open_conversation({**VOLTKART, "trace": True}).send("hi").trace == {"tools": [], "context": ""}


def test_voltkart_sends_back_its_owner_cookie_on_later_turns_and_reset(http):
    """AIRM-166: VoltKart ties a conversation to the chat_owner cookie it sets; without it turn 2 and reset are 404."""
    calls, queue = http
    first = FakeResponse(data={"session_id": "s1", "reply": "Hi"})
    first.cookies = {"chat_owner": "abc"}
    queue += [first, FakeResponse(data={"session_id": "s1", "reply": "Rs 47,990"}), FakeResponse(data={"ok": True})]
    conv = open_conversation(VOLTKART)
    conv.send("hello")
    conv.send("price?")
    conv.close()
    assert "Cookie" not in (calls[0]["headers"] or {})
    assert calls[1]["headers"]["Cookie"] == "chat_owner=abc"
    assert calls[2]["url"].endswith("/api/reset") and calls[2]["headers"]["Cookie"] == "chat_owner=abc"


def test_voltkart_white_box_sends_the_debug_token_header(http, monkeypatch):
    calls, queue = http
    monkeypatch.setenv("VK_TOKEN", "t0k")
    queue += [FakeResponse(data={"session_id": "s", "reply": "x", "trace": {"tools": []}})] * 2
    open_conversation({**VOLTKART, "trace": True, "debug_token_env": "VK_TOKEN"}).send("hi")
    assert calls[0]["headers"]["X-Debug-Token"] == "t0k"
    open_conversation({**VOLTKART, "debug_token_env": "VK_TOKEN"}).send("hi")  # trace off: no token sent
    assert "X-Debug-Token" not in (calls[1]["headers"] or {})


def test_voltkart_warns_when_trace_is_on_but_no_tool_calls_come_back(http, caplog):
    _, queue = http
    queue += [FakeResponse(data={"session_id": "s", "reply": "x"})] * 2
    conv = open_conversation({**VOLTKART, "trace": True, "debug_token_env": "UNSET_TOKEN_VAR"})
    with caplog.at_level("WARNING", logger="adapters"):
        conv.send("a")
        conv.send("b")
    assert [r.message for r in caplog.records].count(
        "v: trace is on but VoltKart sent no tool calls; set UNSET_TOKEN_VAR to the server's DEBUG_TOKEN") == 1


def test_voltkart_logs_a_failed_reset(http, caplog):
    _, queue = http
    queue += [FakeResponse(data={"session_id": "s", "reply": "x"}), FakeResponse(404, {"detail": "gone"})]
    conv = open_conversation(VOLTKART)
    conv.send("a")
    with caplog.at_level("WARNING", logger="adapters"):
        conv.close()
    assert "HTTP 404" in caplog.text


def test_fallback_reply_is_an_error_not_an_answer(http):
    _, queue = http
    queue.append(FakeResponse(data={"session_id": "s", "reply": "Please tell me the issue and I'll help."}))
    conv = open_conversation({**VOLTKART, "fallback_replies": ["please tell me the issue"]})
    with pytest.raises(BotError, match="fallback reply"):
        conv.send("hi")


def test_http_errors_and_bad_json_become_bot_errors(http):
    _, queue = http
    queue += [FakeResponse(429, {"detail": "rate limited"}), FakeResponse(200, None)]
    with pytest.raises(BotError, match="HTTP 429: rate limited"):
        open_conversation(VOLTKART).send("a")
    with pytest.raises(BotError, match="non-JSON"):
        open_conversation(VOLTKART).send("a")


def test_generic_http_adapter_follows_paths(http):
    calls, queue = http
    queue.append(FakeResponse(data={"data": {"answer": "yes", "conversation_id": "c9"}}))
    cfg = {"id": "h", "label": "H", "type": "http", "url": "http://b/chat",
           "body": {"text": "{message}", "conversation_id": "{session_id}"},
           "reply_path": "data.answer", "session_path": "data.conversation_id"}
    conv = open_conversation(cfg)
    assert conv.send("q").text == "yes" and conv.session_id == "c9"
    assert calls[0]["json"]["text"] == "q"


SSE = {"id": "t", "label": "T", "type": "sse_chat", "url": "http://b/chat/stream", "body": {"provider": "gemini"}}


def sse(*events):
    lines = []
    for name, data in events:
        lines += [f"event: {name}", f"data: {json.dumps(data)}", ""]
    return FakeResponse(lines=lines)


def test_sse_gray_box_route_comes_from_meta(http):
    calls, queue = http
    queue.append(sse(("start", {"provider": "gemini"}), ("meta", {"agent": "sales_agent", "provider": "gemini"}),
                     ("token", {"text": "Rs "}), ("token", {"text": "129,999"}), ("done", {"ok": True})))
    conv = open_conversation(SSE)
    reply = conv.send("price?")
    assert reply.text == "Rs 129,999"
    assert reply.trace == {"route": "sales_agent"}
    assert "debug" not in calls[0]["json"]
    assert conv.history[-1] == {"role": "assistant", "content": "Rs 129,999"}


def test_sse_white_box_trace_event(http):
    calls, queue = http
    queue.append(sse(("meta", {"agent": "rag_agent"}),
                     ("trace", {"agent": "rag_agent", "route_source": "deterministic", "retrieved": "Returns: 7 days"}),
                     ("token", {"text": "7 days"})))
    reply = open_conversation({**SSE, "trace": True}).send("return policy?")
    assert calls[0]["json"]["debug"] is True
    assert reply.trace == {"route": "rag_agent", "context": "Returns: 7 days", "route_source": "deterministic"}


def test_sse_error_event(http):
    _, queue = http
    queue.append(sse(("error", {"message": "429 RESOURCE_EXHAUSTED"})))
    with pytest.raises(BotError, match="RESOURCE_EXHAUSTED"):
        open_conversation(SSE).send("hi")


SUPPORTFLOW = {"id": "m", "label": "M", "type": "supportflow", "base_url": "http://sf", "email": "e", "password": "p"}


@pytest.fixture
def fresh_supportflow(monkeypatch):
    for attr in ("_tokens", "_locks"):
        monkeypatch.setattr(adapters.SupportFlowConversation, attr, {})
    monkeypatch.setattr(adapters.SupportFlowConversation, "_cleaned", set())


def test_supportflow_trace_and_cleanup(http, fresh_supportflow):
    calls, queue = http
    queue += [
        FakeResponse(data={"token": "jwt"}),                                       # login
        FakeResponse(data=[{"id": 7, "status": "AI_ACTIVE"}]),                     # old open chat...
        FakeResponse(data={"status": "WAITING_FOR_AGENT"}),                        # ...is retired
        FakeResponse(data={"conversation_id": 8, "reply": "Your order is out for delivery", "intent": "ORDER_STATUS",
                           "escalate": False, "priority": "LOW", "sentiment": "Neutral",
                           "trace": {"context": "Verified order #1001: delivery_status=OUT_FOR_DELIVERY"}}),
        FakeResponse(data={"status": "WAITING_FOR_AGENT"}),                        # close retires chat 8
    ]
    conv = open_conversation({**SUPPORTFLOW, "trace": True})
    reply = conv.send("Where is my order #1001?")
    conv.close()
    assert reply.trace == {"route": "ORDER_STATUS", "escalated": False, "priority": "LOW", "sentiment": "Neutral",
                           "context": "Verified order #1001: delivery_status=OUT_FOR_DELIVERY"}
    assert calls[3]["json"] == {"message": "Where is my order #1001?", "conversation_id": None, "debug": True}
    assert [c["url"] for c in calls if c["url"].endswith("/escalate")] == \
        ["http://sf/api/conversations/7/escalate", "http://sf/api/conversations/8/escalate"]
    assert not conv.lock.locked()


def test_supportflow_handoff_is_visible_in_the_trace(http, fresh_supportflow):
    _, queue = http
    adapters.SupportFlowConversation._cleaned.add(("http://sf", "e"))
    queue += [FakeResponse(data={"token": "jwt"}),
              FakeResponse(data={"conversation_id": 1, "reply": None, "intent": "HUMAN_AGENT_REQUEST",
                                 "escalate": True, "priority": "HIGH", "status": "WAITING_FOR_AGENT"})]
    reply = open_conversation(SUPPORTFLOW).send("human please")
    assert reply.text.startswith("(no reply: the chat was handed to a human")
    assert reply.trace["escalated"] is True and reply.trace["route"] == "HUMAN_AGENT_REQUEST"


def test_supportflow_logs_in_again_when_the_token_expires(http, fresh_supportflow):
    calls, queue = http
    adapters.SupportFlowConversation._cleaned.add(("http://sf", "e"))
    queue += [FakeResponse(data={"token": "old"}), FakeResponse(401, {"msg": "expired"}),
              FakeResponse(data={"token": "new"}), FakeResponse(data={"conversation_id": 1, "reply": "hi"})]
    assert open_conversation(SUPPORTFLOW).send("hi").text == "hi"
    assert calls[-1]["headers"]["Authorization"] == "Bearer new"


def test_supportflow_without_escalate_closes_chats_in_its_db(http, fresh_supportflow, tmp_path):
    import sqlite3
    db = tmp_path / "support-test.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        c.executemany("INSERT INTO users (id, email) VALUES (?, ?)", [(1, SUPPORTFLOW["email"]), (2, "real@x.com")])
        c.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, closed_at TEXT)")
        c.executemany("INSERT INTO conversations (id, customer_id, status) VALUES (?, ?, 'AI_ACTIVE')",
                      [(7, 1), (8, 1), (9, 2)])
    calls, queue = http
    queue += [FakeResponse(data={"token": "jwt"}),
              FakeResponse(data=[{"id": 7, "status": "AI_ACTIVE"}]),           # old open chat: closed in the DB
              FakeResponse(data={"conversation_id": 8, "reply": "Out for delivery", "intent": "ORDER_STATUS",
                                 "escalate": False, "model_used": "gemini:gemini-3.6-flash"})]
    conv = open_conversation({**SUPPORTFLOW, "db_path": str(db), "handoff": False})
    reply = conv.send("Where is my order RD100234?")
    conv.close()
    assert reply.trace == {"route": "ORDER_STATUS"}  # no hand-off in this version, so no "escalated" to check
    assert not [c for c in calls if c["url"].endswith("/escalate")]
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT id, status FROM conversations").fetchall() == [(7, "CLOSED"), (8, "CLOSED"),
                                                                                (9, "AI_ACTIVE")]


def test_supportflow_closes_chats_with_its_close_endpoint(http, fresh_supportflow):
    calls, queue = http
    queue += [FakeResponse(data={"token": "jwt"}),
              FakeResponse(data=[{"id": 7, "status": "WAITING_FOR_AGENT"}]),   # a handed-off chat left open
              FakeResponse(data={"status": "CLOSED"}),
              FakeResponse(data={"conversation_id": 8, "reply": "hi"}),
              FakeResponse(data={"status": "CLOSED"})]
    conv = open_conversation({**SUPPORTFLOW, "close_path": "/api/conversations/{id}/close"})
    conv.send("hi")
    conv.close()
    assert [c["url"] for c in calls if c["url"].endswith("/close")] == \
        ["http://sf/api/conversations/7/close", "http://sf/api/conversations/8/close"]


def test_supportflow_puts_back_what_a_chat_changed(http, fresh_supportflow, monkeypatch, tmp_path):
    import sqlite3
    monkeypatch.setattr(adapters.SupportFlowConversation, "_snapshots", {})
    adapters.SupportFlowConversation._cleaned.add(("http://sf", "e"))
    db = tmp_path / "compare-test.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, order_status TEXT)")
        c.execute("CREATE TABLE returns (id INTEGER PRIMARY KEY, order_id INTEGER)")
        c.execute("INSERT INTO orders VALUES (1, 'SHIPPED')")
    _, queue = http
    queue += [FakeResponse(data={"token": "jwt"}), FakeResponse(data={"conversation_id": 8, "reply": "Cancelled"}),
              FakeResponse(data={"status": "CLOSED"})]
    conv = open_conversation({**SUPPORTFLOW, "close_path": "/api/conversations/{id}/close", "db_path": str(db),
                              "restore_tables": ["orders", "returns"]})
    conv.send("cancel my order")
    with sqlite3.connect(db) as c:  # what the bot did during the chat
        c.execute("UPDATE orders SET order_status = 'CANCELLED'")
        c.execute("INSERT INTO returns VALUES (1, 1)")
    conv.close()
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT * FROM orders").fetchall() == [(1, "SHIPPED")]
        assert c.execute("SELECT * FROM returns").fetchall() == []


def test_supportflow_only_writes_to_a_test_database(http, fresh_supportflow, tmp_path):
    conv = open_conversation({**SUPPORTFLOW, "db_path": str(tmp_path / "production.db"), "handoff": False})
    with pytest.raises(BotError, match="test database"):
        conv._retire(8)


def test_supportflow_password_can_come_from_the_environment(http, fresh_supportflow, monkeypatch):
    calls, queue = http
    adapters.SupportFlowConversation._cleaned.add(("http://sf", SUPPORTFLOW["email"]))
    monkeypatch.setenv("BOT_SF_PASSWORD", "from-env")
    cfg = {k: v for k, v in SUPPORTFLOW.items() if k != "password"} | {"password_env": "BOT_SF_PASSWORD"}
    queue += [FakeResponse(data={"token": "jwt"}), FakeResponse(data={"conversation_id": 1, "reply": "hi"})]
    open_conversation(cfg).send("hi")
    assert calls[0]["json"]["password"] == "from-env"


def test_supportflow_offline_fallback_counts_as_blocked(http, fresh_supportflow):
    _, queue = http
    adapters.SupportFlowConversation._cleaned.add(("http://sf", "e"))
    queue += [FakeResponse(data={"token": "jwt"}),
              FakeResponse(data={"conversation_id": 1, "reply": "Here is what I found", "model_used": "auto:mock"})]
    with pytest.raises(BotError, match="fallback reply"):
        open_conversation(SUPPORTFLOW).send("price of Pulse Pro?")
