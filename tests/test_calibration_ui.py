"""Isolated browser checks for the calibration UI: synthetic data, mocked Judge, no providers."""

import json
import socket
import threading
import time

import pytest
import uvicorn
from test_bias_governance import run_fixture
from test_judge_calibration import (
    Provider,
    clean_state,  # noqa: F401 - autouse isolation fixture
    request,
    run_eval,
)

from app import database as db
from app.blackbox import judge_calibration as cal
from app.blackbox.calibration_models import LabelUpdate, Sample, Selection, SourceRef
from app.blackbox.runner import save
from app.blackbox_app import app

XSS = 'GOOD <img src=x onerror="window.__xss=1"><script>window.__xss=1</script> reply'


@pytest.fixture
def server():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    uv = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert uv.started
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(5)


@pytest.fixture
def seeded():
    """A saved simple-mode Run with injected markup, a labeled set and a completed evaluation."""
    cfg, run = run_fixture()
    for index, case in enumerate(run["cases"]):
        output = XSS if index == 0 else ("GOOD reply" if index % 2 == 0 else "BAD reply")
        for turn in case["results"][0]["transcript"]:
            turn["output"] = output
    run["status"] = "completed"
    save(run, cfg)
    stored = db.get("blackbox", run["id"])
    created = cal.create_set(
        "UI set",
        Selection(source=SourceRef(kind="blackbox_run", id=run["id"]), sample=Sample(size=40)),
    )
    ident = created["set"]["id"]
    for item in cal.get_set(ident)["draft"]["items"]:
        good = "GOOD" in item["payload"]["transcript"][0]["output"]
        cal.save_label(
            ident,
            item["id"],
            LabelUpdate(
                expected_revision=0, verdict="pass" if good else "fail", rationale="because"
            ),
        )
    cal.freeze(ident, cal.get_set(ident)["revision"])
    provider = Provider(flip=("BAD reply",), fail=("zzz",))
    evaluation = run_eval(ident, request(model="judge-ui"), provider)
    return {"run": stored, "set": ident, "evaluation": evaluation}


def with_browser(server, work):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        work(page, errors)
        browser.close()


def test_warning_stays_visible_on_evaluate_and_governance(server, seeded):
    def work(page, errors):
        page.goto(f"{server}/")
        page.locator("#calibration-status .alignment").wait_for(state="visible")
        text = page.locator("#calibration-status").inner_text()
        assert "unverified" in text or "calibrat" in text.lower()
        page.goto(f"{server}/?run={seeded['run']['id']}#governance")
        page.locator("#gov-human .alignment").first.wait_for(state="visible")
        human = page.locator("#gov-human").inner_text()
        assert "model-to-model" in human
        assert "Judge agreement (model vs model)" in page.locator("#gov-integrity").inner_text()
        assert not errors

    with_browser(server, work)


def test_status_follows_model_changes_and_ignores_stale_responses(server, seeded):
    def work(page, errors):
        held = []

        def handler(route):
            body = json.loads(route.request.post_data)
            if body["model"] == "slow-model":
                held.append(route)  # answer later, after the newer selection has won
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "state": "stale",
                            "warnings": ["Existing calibration applies to a different Judge."],
                            "stale_reasons": ["Judge model changed."],
                        }
                    ),
                )

        page.route("**/judge-calibration/compatibility", handler)
        page.goto(f"{server}/")
        page.wait_for_function("document.querySelector('.judge [data-model]')")
        page.evaluate(
            """() => { const row = document.querySelector('.judge');
              row.querySelector('[data-enabled]').checked = true;
              document.getElementById('judge-options').open = true;
              row.querySelector('details').open = true; }"""
        )
        model = page.locator(".judge [data-model]").first
        model.fill("slow-model")
        for _ in range(40):
            if held:
                break
            page.wait_for_timeout(100)
        assert held
        model.fill("fast-model")
        page.locator('#calibration-status [data-state="stale"]').wait_for(timeout=5000)
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"state": "meets", "warnings": ["Meets configured calibration criteria."]}
            ),
        )
        page.wait_for_timeout(400)
        assert (
            page.locator("#calibration-status [data-state]").get_attribute("data-state") == "stale"
        )
        assert "Judge model changed." in page.locator("#calibration-status").inner_text()
        assert not errors

    with_browser(server, work)


def test_labeling_disagreements_escaping_and_keyboard(server, seeded):
    def work(page, errors):
        page.goto(f"{server}/?run={seeded['run']['id']}#results")
        page.locator("#calibration-panel summary").click()
        page.locator("#cal-sets").wait_for()
        page.select_option("#cal-sets", seeded["set"])
        page.locator("#cal-open").click()
        page.locator(".cal-item").first.wait_for()
        assert page.evaluate("window.__xss") is None  # transcript markup stayed inert text
        # Labels shown come from the owner's saved revisions, never from Judge output.
        shown = page.locator(".cal-item").filter(has_text="onerror").first.text_content()
        assert "<script>" in shown and "judge says" not in shown
        # Keyboard-only revision: focus a radio, toggle with the keyboard, save with Enter.
        first = page.locator(".cal-item").first
        first.locator("input[value=fail]").focus()
        page.keyboard.press("Space")
        first.locator("[data-reason]").fill("Re-read the expected criterion.")
        first.locator("[data-save]").focus()
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.getElementById('calibration-message').textContent.includes('new revision')"
        )
        saved = cal.get_set(seeded["set"])["draft"]["items"]
        assert any(len(i["labels"]) == 2 for i in saved)
        # Stale edit from another tab/user fails clearly and reloads.
        target = next(i for i in saved if len(i["labels"]) == 2)
        cal.save_label(
            seeded["set"],
            target["id"],
            LabelUpdate(
                expected_revision=2, verdict="pass", change_reason="Second reviewer changed."
            ),
        )
        card = page.locator(f'[data-item="{target["id"]}"]')
        card.locator("[data-reason]").fill("Trying to save over a newer revision.")
        card.locator("input[value=fail]").check()
        card.locator("[data-save]").click()
        page.wait_for_function(
            "document.getElementById('calibration-message').textContent.includes('stale')"
        )
        # The 409 reloads the set with the newer revision; wait for that before moving on.
        page.wait_for_function(
            "id => document.querySelector(`[data-item=\"${id}\"]`)?.dataset.revision === '3'",
            arg=target["id"],
        )
        # Evaluation results: counts, denominators and every disagreement are inspectable.
        page.select_option("#cal-evals", seeded["evaluation"])
        page.locator("#cal-view").click()
        page.locator("#cal-result .cal-table").first.wait_for()
        result = page.locator("#cal-result").inner_text()
        for phrase in (
            "Total selected",
            "Validly judged",
            "Not tested",
            "Confusion matrix",
            "False acceptance",
        ):
            assert phrase in result
        assert page.locator(".cal-disagreement").count() >= 1
        assert page.evaluate("window.__xss") is None
        assert not errors

    with_browser(server, work)
