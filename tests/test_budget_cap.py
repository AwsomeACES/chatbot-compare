"""MAX_RUN_BUDGET_USD: a run with a paid bot never gets a bigger budget than the server allows."""
import app

FREE = {"id": "free", "pricing": {"input": 0, "output": 0}}
PAID = {"id": "paid", "pricing": {"input": 2.0, "output": 10.0}}
UNPRICED = {"id": "unpriced"}


def test_paid_bots(monkeypatch):
    monkeypatch.setattr(app.prices, "latest", lambda: {})
    assert app.paid([FREE]) == []
    assert app.paid([FREE, PAID]) == [PAID]
    assert app.paid([UNPRICED]) == [UNPRICED]  # unknown price counts as paid: the budget then refuses it


def test_cap_applies_only_to_paid_runs(monkeypatch):
    monkeypatch.setattr(app.prices, "latest", lambda: {})
    monkeypatch.setattr(app, "MAX_RUN_BUDGET_USD", 5.0)
    assert app.capped_budget([FREE], None) is None
    assert app.capped_budget([FREE], 50) == 50
    assert app.capped_budget([FREE, PAID], None) == 5.0
    assert app.capped_budget([PAID], 50) == 5.0
    assert app.capped_budget([PAID], 2) == 2


def test_no_cap_configured(monkeypatch):
    monkeypatch.setattr(app.prices, "latest", lambda: {})
    monkeypatch.setattr(app, "MAX_RUN_BUDGET_USD", None)
    assert app.capped_budget([PAID], None) is None
    assert app.capped_budget([PAID], 50) == 50


def test_start_run_passes_the_capped_budget(monkeypatch):
    from fastapi.testclient import TestClient
    got = {}
    monkeypatch.setattr(app.prices, "latest", lambda: {})
    monkeypatch.setattr(app, "MAX_RUN_BUDGET_USD", 5.0)
    monkeypatch.setattr(app, "find_bots", lambda ids: [PAID if i == "paid" else FREE for i in ids])
    monkeypatch.setattr(app.evaluator, "load_suite", lambda s: {"cases": []})

    def fake_start(bots, suite, judge, **kw):
        got.update(kw)
        return {"id": "r1"}

    monkeypatch.setattr(app.evaluator, "start_run", fake_start)
    r = TestClient(app.app, base_url="http://localhost").post("/api/runs", json={"bots": ["paid", "free"], "suite": "x", "budget_usd": 999})
    assert r.status_code == 200, r.text
    assert got["budget_usd"] == 5.0
