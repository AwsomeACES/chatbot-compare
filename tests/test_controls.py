"""Budget, LiteLLM prices, consent, adding a bot by URL, PDF export and the new test categories."""
import json
from types import SimpleNamespace

import pytest

import evaluator
import export
import governance
import prices
import quickbot
from adapters import BotError
from test_evaluator import BOT_A, BOT_B, SUITE, FakeConversation

SNAPSHOT = {"source": "LiteLLM", "date": "2026-10-12", "models": {
    "gpt-5-mini": {"input": 0.25, "output": 2.0},
    "gemini/gemini-2.5-flash": {"input": 0.3, "output": 2.5},
    "vertex_ai/gemini-2.5-flash-long": {"input": 9.0, "output": 9.0}}}


# ---------- LiteLLM prices ----------

def test_the_catalogue_is_parsed_to_usd_per_million_chat_models_only():
    raw = {"sample_spec": {"mode": "chat", "input_cost_per_token": 0, "output_cost_per_token": 0},
           "gpt-5-mini": {"mode": "chat", "input_cost_per_token": 2.5e-07, "output_cost_per_token": 2e-06,
                          "cache_read_input_token_cost": 2.5e-08},
           "text-embedding-3": {"mode": "embedding", "input_cost_per_token": 1e-08},
           "no-output-price": {"mode": "chat", "input_cost_per_token": 1e-06}}
    assert prices.parse(raw) == {"gpt-5-mini": {"input": 0.25, "output": 2.0, "cache_read": 0.025}}


def test_lookup_matches_exact_then_provider_prefixed_ids():
    assert prices.lookup("gpt-5-mini", SNAPSHOT)["input"] == 0.25
    p = prices.lookup("Gemini-2.5-Flash", SNAPSHOT)
    assert p["input"] == 0.3 and "gemini/gemini-2.5-flash" in p["source"] and "2026-10-12" in p["source"]
    assert prices.lookup("unknown-model", SNAPSHOT) is None and prices.lookup("gpt-5-mini", None) is None


def test_update_saves_a_dated_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "PRICES_DIR", str(tmp_path))
    raw = {"m": {"mode": "chat", "input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06}}
    info = prices.update(fetch=lambda url: SimpleNamespace(status_code=200, json=lambda: raw))
    assert info["models"] == 1 and prices.latest()["models"] == {"m": {"input": 1.0, "output": 2.0}}
    with pytest.raises(RuntimeError):
        prices.update(fetch=lambda url: SimpleNamespace(status_code=503))


def test_bots_json_prices_win_over_the_catalogue():
    assert evaluator.priced_config({"id": "x", "model": "gpt-5-mini"}, SNAPSHOT)["pricing"]["output"] == 2.0
    free = {"input": 0, "output": 0, "source": "free tier"}
    assert evaluator.priced_config({"id": "x", "model": "gpt-5-mini", "pricing": free}, SNAPSHOT)["pricing"] == free
    assert "pricing" not in evaluator.priced_config({"id": "x"}, SNAPSHOT)


def test_judge_pricing_adds_catalogue_prices_after_bots_json_and_never_for_a_local_judge(monkeypatch):
    remote = SimpleNamespace(base_url="https://api.example.com/v1", models=["gpt-5-mini", "gemini-2.5-flash"])
    local = SimpleNamespace(base_url="http://localhost:11434/v1", models=["qwen2.5:3b"])
    monkeypatch.setattr(evaluator, "_judge_endpoints", lambda second: [remote, local])
    monkeypatch.setattr(evaluator, "judge_pricing", lambda: [{"model": "gemini-*", "input": 0, "output": 0}])
    out = evaluator.pinned_judge_pricing(SNAPSHOT)
    assert out[0]["model"] == "gemini-*" and [p["model"] for p in out[1:]] == ["gpt-5-mini"]
    assert evaluator.price_of("gemini-2.5-flash", out)["input"] == 0  # the free tier, not the list price
    assert evaluator.unpriced([{"id": "a", "label": "A"}], out, True, False) == ["A"]


# ---------- Budget ----------

def _run_in_this_thread(monkeypatch, tmp_path, replies=("Rs 100",)):
    monkeypatch.setattr(evaluator, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(evaluator, "open_conversation", lambda cfg: FakeConversation(list(replies) * 10))
    monkeypatch.setattr(evaluator, "load_suite", lambda _: SUITE)
    monkeypatch.setattr(evaluator, "SUITES_DIR", str(tmp_path))
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setattr(evaluator, "threading", SimpleNamespace(
        Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)), get_ident=lambda: 0))
    monkeypatch.setattr(evaluator.prices, "latest", lambda: None)


def test_a_budget_needs_a_price_for_every_bot(monkeypatch, tmp_path):
    _run_in_this_thread(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="no price for: B"):
        evaluator.start_run([{**BOT_A, "pricing": {"input": 1, "output": 1}}, BOT_B], "t", False, budget_usd=1)
    with pytest.raises(ValueError, match="more than"):
        evaluator.start_run([BOT_A, BOT_B], "t", False, budget_usd=0)


def test_reaching_the_budget_stops_new_chats_and_leaves_them_out_of_the_score(monkeypatch, tmp_path):
    _run_in_this_thread(monkeypatch, tmp_path, replies=["x" * 4000])  # ~1000 output tokens per reply
    monkeypatch.setattr(evaluator, "CONCURRENCY", 1)
    dear = {"input": 1000.0, "output": 1000.0}  # USD per million: ~$1 per reply
    bots = [{**BOT_A, "pricing": dear, "max_concurrency": 1}, {**BOT_B, "pricing": dear, "max_concurrency": 1}]
    run = evaluator.start_run(bots, "t", False, repeats=3, budget_usd=1.5)
    b = run["budget"]
    assert b["reached"] and b["spent_usd"] >= 1.5 and b["estimated_usd"] == b["spent_usd"]  # no tokens reported
    stopped = [r for r in run["results"] if r.get("budget_blocked")]
    asked = [r for r in run["results"] if r["turns"]]
    assert stopped and asked and all(r["blocked"] and "Budget limit reached" in r["error"] for r in stopped)
    assert run["status"] == "over_budget" and "over_budget" in evaluator.RESUMABLE
    with pytest.raises(ValueError, match="higher budget"):  # resuming needs more money
        evaluator.resume_run(run["id"], bots)


def test_parallel_chats_cannot_all_start_past_the_budget(monkeypatch, tmp_path):
    suite = {**SUITE, "cases": [{**SUITE["cases"][0], "id": f"price{i}"} for i in range(12)]}
    _run_in_this_thread(monkeypatch, tmp_path, replies=["x" * 4000])  # ~$1 per reply at this price
    monkeypatch.setattr(evaluator, "load_suite", lambda _: suite)
    dear = {"input": 1000.0, "output": 1000.0}
    bots = [{**BOT_A, "pricing": dear, "max_concurrency": 6}, {**BOT_B, "pricing": dear, "max_concurrency": 6}]
    run = evaluator.start_run(bots, "t", False, budget_usd=5)
    b = run["budget"]
    asked = sum(1 for r in run["results"] if r["turns"])
    # Without reservations all 12 parallel slots would start at once; now only what fits does (one chat may be
    # under way when the limit is crossed, so at most one chat's worth over).
    assert asked <= 6 and b["spent_usd"] <= 5 + 1.1 and b["in_flight"] == 0 and b["reserved_usd"] == 0
    assert run["status"] == "over_budget"


def test_the_budget_counts_reported_tokens_judge_calls_and_unpriced_calls_stop_it():
    run = {"bot_configs": [{"id": "a", "pricing": {"input": 1.0, "output": 1.0}}],
           "judge_pricing": [{"model": "paid", "input": 2.0, "output": 2.0}], "budget": evaluator.new_budget(10)}
    r = {"bot_id": "a", "error": None, "turns": [{"user": "q", "bot": "a", "usage": {"input_tokens": 1_000_000}}],
         "judge": {"model": "paid", "usage": {"input_tokens": 500_000}}}
    evaluator.charge(run, *evaluator.result_spend(run, r))
    assert run["budget"]["spent_usd"] == pytest.approx(2.0) and run["budget"]["estimated_usd"] == 0
    evaluator.charge(run, *evaluator.result_spend(run, {**r, "judge": {"model": "mystery", "usage": {"input_tokens": 1}}}))
    assert run["budget"]["reached"] and "no price" in run["budget"]["stopped_by"]


# ---------- Consent ----------

def test_data_leaving_the_machine_needs_its_own_yes():
    local_bot = {"id": "l", "label": "Local", "base_url": "http://localhost:8000"}
    cloud_bot = {"id": "c", "label": "Cloud", "url": "https://bot.example.com/chat"}
    judge = SimpleNamespace(base_url="https://generativelanguage.googleapis.com/v1beta/openai", models=["gemini-x"])
    with pytest.raises(governance.ConsentError, match="send test messages to Cloud"):
        governance.check_consent([local_bot, cloud_bot], [], {})
    with pytest.raises(governance.ConsentError, match="share the conversations"):
        governance.check_consent([local_bot], [judge], {"send_to_bots": True})
    ok = governance.check_consent([local_bot, cloud_bot], [judge], {"send_to_bots": True, "share_with_judge": True})
    assert ok["given_by"] == "dashboard" and ok["remote_bots"] == ["Cloud"] and ok["remote_judges"] == ["gemini-x"]
    assert governance.check_consent([local_bot], [], {})["remote_bots"] == []  # nothing leaves: nothing to ask
    assert governance.check_consent([cloud_bot], [judge], None)["given_by"] == "script"
    assert governance.remote_bots([{"id": "b", "label": "Bedrock", "type": "claude_bedrock"}]) == ["Bedrock"]


def test_the_dashboard_cannot_start_a_cloud_judged_run_without_consent(monkeypatch):
    from fastapi.testclient import TestClient
    import app
    bot = {"id": "l", "label": "L", "type": "http", "url": "http://localhost:9/chat"}
    monkeypatch.setattr(app, "load_bots", lambda: [bot, {**bot, "id": "m", "label": "M"}])
    monkeypatch.setattr(evaluator.llm.JUDGE, "base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    c = TestClient(app.app, base_url="http://localhost")
    r = c.post("/api/runs", json={"bots": ["l", "m"], "suite": "generic_support", "judge": True})
    assert r.status_code == 400 and "share the conversations" in r.json()["detail"]
    r = c.post("/api/bots/detect", json={"url": "https://bot.example.com/chat"})
    assert r.status_code == 400 and "not on this machine" in r.json()["detail"]


# ---------- Adding a bot by URL ----------

class FakeResponse:
    def __init__(self, status=200, data=None, kind="application/json", lines=()):
        self.status_code, self.data, self.lines = status, data, list(lines)
        self.headers = {"content-type": kind}
        self.text = json.dumps(data)

    def json(self):
        if self.data is None:
            raise ValueError("no json")
        return self.data

    def read(self):
        return b""

    def iter_lines(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeClient:
    """Answers like a bot API: posts go to handler(url, body) -> FakeResponse; gets return a JSON 404 page."""

    HTTPError = quickbot.httpx2.HTTPError

    def __init__(self, handler, get=None):
        self.handler, self.posts = handler, []
        self.get = get or (lambda url, **kw: FakeResponse(404, {"detail": "Not Found"}))

    def stream(self, method, url, json=None, **kw):
        self.posts.append((url, json))
        return self.handler(url, json)


def test_detect_finds_the_message_field_reply_path_and_session(monkeypatch):
    def handler(url, body):
        if "question" not in body:
            return FakeResponse(422, {"detail": "question required"})
        return FakeResponse(data={"data": {"answer": "Hello!"}, "conversation_id": "c1", "usage": {"prompt_tokens": 3}})
    client = FakeClient(handler)
    monkeypatch.setattr(quickbot, "open_conversation", lambda cfg: SimpleNamespace(
        send=lambda m: SimpleNamespace(text="Hello!", latency_ms=50), close=lambda: None))
    out = quickbot.detect("http://localhost:7000/ask", client=client, widget=lambda url: None)
    assert out["config"] == {"type": "http", "url": "http://localhost:7000/ask",
                             "body": {"question": "{message}", "conversation_id": "{session_id}"},
                             "reply_path": "data.answer", "session_path": "conversation_id", "usage_path": "usage"}
    assert "question" in out["how"] and out["reply"] == "Hello!"


def test_detect_tries_common_paths_on_a_bare_host_and_finds_a_stream(monkeypatch):
    def handler(url, body):
        if not url.endswith("/api/chat"):
            return FakeResponse(404, {"detail": "Not Found"})
        return FakeResponse(kind="text/event-stream", lines=[
            "event: meta", 'data: {"agent": "sales"}', "event: token", 'data: {"text": "Hel"}',
            "event: token", 'data: {"text": "lo"}', "event: done", "data: {}"])
    monkeypatch.setattr(quickbot, "open_conversation", lambda cfg: SimpleNamespace(
        send=lambda m: SimpleNamespace(text="Hello", latency_ms=50), close=lambda: None))
    out = quickbot.detect("http://localhost:8001", client=FakeClient(handler), widget=lambda url: None)
    assert out["config"]["type"] == "sse_chat" and out["config"]["url"] == "http://localhost:8001/api/chat"
    assert out["config"]["token_event"] == "token"


def test_detect_reads_the_model_from_an_openai_style_api(monkeypatch):
    get = lambda url, **kw: FakeResponse(data={"data": [{"id": "llama3"}]})
    monkeypatch.setattr(quickbot, "open_conversation", lambda cfg: SimpleNamespace(
        send=lambda m: SimpleNamespace(text="Hi there", latency_ms=5), close=lambda: None))
    out = quickbot.detect("http://localhost:11434/v1", client=FakeClient(None, get=get))
    assert out["config"] == {"type": "openai_compatible", "base_url": "http://localhost:11434/v1", "model": "llama3"}


def test_detect_explains_what_it_tried_and_asks_for_a_key_on_401():
    with pytest.raises(BotError, match="Tried"):
        quickbot.detect("http://localhost:7000/x", client=FakeClient(lambda u, b: FakeResponse(500, {"e": 1})),
                        widget=lambda url: None)
    with pytest.raises(BotError, match="needs authentication"):
        quickbot.detect("http://localhost:7000/x", client=FakeClient(lambda u, b: FakeResponse(401, {"e": 1})))
    with pytest.raises(BotError, match="full URL"):
        quickbot.detect("localhost:7000")


def test_quick_bots_are_saved_apart_from_bots_json(monkeypatch, tmp_path):
    monkeypatch.setattr(quickbot, "QUICK_FILE", str(tmp_path / "bots.quick.json"))
    cfg = {"type": "http", "url": "http://localhost:7000/ask", "reply_path": "reply", "headers": {"X": "secret"}}
    bot = quickbot.add("My Test Bot", cfg, taken_ids={"quick-my-test-bot"})
    assert bot["id"] == "quick-my-test-bot-2" and bot["quick"] and "headers" not in bot  # only known fields kept
    assert [b["id"] for b in quickbot.load()] == ["quick-my-test-bot-2"]
    with pytest.raises(BotError):
        quickbot.add("", cfg, set())
    quickbot.remove(bot["id"])
    assert quickbot.load() == []
    with pytest.raises(KeyError):
        quickbot.remove(bot["id"])


# ---------- PDF and the report ----------

def _done_run():
    return {"id": "20261012-000000-abcd", "created_at": "2026-10-12T10:00:00", "suite": "t", "suite_name": "t",
            "status": "done", "bots": [{"id": "a", "label": "A"}], "bot_configs": [{"id": "a"}], "results": [],
            "comparisons": [], "summary": {"bots": []}, "budget": {**evaluator.new_budget(2), "spent_usd": 0.5},
            "price_catalog": {"source": "LiteLLM", "date": "2026-10-12"},
            "consent": {"given_by": "dashboard", "by": "dashboard", "send_to_bots": True, "share_with_judge": True,
                        "remote_bots": [], "remote_judges": ["gemini-x"]}}


def test_the_report_shows_budget_prices_and_consent():
    html = "".join(export._controls_html(_done_run()))
    assert "$0.5000 of $2.0000 spent" in html and "LiteLLM snapshot of 2026-10-12" in html
    assert "share with the AI judge yes" in html and "cloud judge: gemini-x" in html


def test_the_report_prints_as_a_pdf(monkeypatch):
    monkeypatch.setattr(export, "report_html", lambda run: "<html><body><h1>Report</h1></body></html>")
    try:
        pdf = export.report_pdf(_done_run())
    except export.PdfUnavailable as e:
        pytest.skip(str(e))
    assert pdf.startswith(b"%PDF")


# ---------- New test categories ----------

def test_prompt_leakage_counts_as_safety_and_the_other_new_skills_as_accuracy():
    assert "prompt-leakage" in evaluator.SAFETY
    for cat in ("consistency", "calibration", "over-refusal"):
        assert cat not in evaluator.NON_FACTUAL


@pytest.mark.parametrize("suite_id", ["store_support", "generic_support"])
def test_every_new_case_fills_all_its_placeholders(suite_id):
    import re
    suite = evaluator.load_suite(suite_id)
    new = [c for c in suite["cases"] if c["category"] in ("prompt-leakage", "over-refusal", "consistency", "calibration")]
    assert len(new) >= 10
    for profile in (suite.get("profiles") or {"generic": {"vars": {}}}).values():
        for c in new:
            rendered = evaluator.render({k: c[k] for k in ("turns", "variants", "expect", "rubric") if k in c}, profile["vars"])
            assert not re.findall(r"\{\w+\}", json.dumps(rendered)), c["id"]


def test_rejudge_keeps_cases_a_budget_stopped_blocked(monkeypatch, tmp_path):
    """A case the budget never asked must stay blocked (left out), not turn into a failed case on a re-grade."""
    import sys
    import rejudge
    monkeypatch.setattr(evaluator, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(evaluator, "load_suite", lambda _: SUITE)
    monkeypatch.setattr(rejudge, "ROOT", str(tmp_path))
    (tmp_path / "bots.json").write_text(json.dumps({"bots": [BOT_A]}))
    stopped = {"case_id": "price", "bot_id": "a", "repeat": 0, "category": "products", "turns": [], "judge": None,
               "error": "Budget limit reached ($1.0000 of $1.0000 spent): not asked.", "blocked": True,
               "budget_blocked": True, "unsupported": False, "checks": None, "check_failures": []}
    run = {"id": "r1", "suite": "t", "status": "over_budget", "judge": False, "bots": [{"id": "a", "label": "A"}],
           "bot_configs": [BOT_A], "results": [stopped]}
    (tmp_path / "r1.json").write_text(json.dumps(run))
    monkeypatch.setattr(sys, "argv", ["rejudge.py", "r1", "--checks-only"])
    rejudge.main()
    saved = json.loads((tmp_path / "r1.json").read_text())
    assert saved["results"][0]["blocked"] is True
    assert evaluator.outcome(saved["results"][0]) == "blocked"
