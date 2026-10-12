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


def test_voltkart_with_no_tool_calls_retrieved_nothing(http):
    _, queue = http
    queue.append(FakeResponse(data={"session_id": "s", "reply": "Hello!", "trace": {"tools": []}}))
    assert open_conversation({**VOLTKART, "trace": True}).send("hi").trace == {"tools": [], "context": ""}


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
    db = tmp_path / "support.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, status TEXT, closed_at TEXT)")
        c.executemany("INSERT INTO conversations (id, status) VALUES (?, 'AI_ACTIVE')", [(7,), (8,)])
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
        assert c.execute("SELECT id, status FROM conversations").fetchall() == [(7, "CLOSED"), (8, "CLOSED")]


def test_supportflow_offline_fallback_counts_as_blocked(http, fresh_supportflow):
    _, queue = http
    adapters.SupportFlowConversation._cleaned.add(("http://sf", "e"))
    queue += [FakeResponse(data={"token": "jwt"}),
              FakeResponse(data={"conversation_id": 1, "reply": "Here is what I found", "model_used": "auto:mock"})]
    with pytest.raises(BotError, match="fallback reply"):
        open_conversation(SUPPORTFLOW).send("price of Pulse Pro?")
