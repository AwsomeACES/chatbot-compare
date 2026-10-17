"""Isolated browser smoke: synthetic target, no real bot/provider conversations."""

import copy
import os
import socket
import threading
import time

import pytest
import uvicorn

from app.blackbox_app import app


def test_white_only_setup_and_combined_results():
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#start").wait_for(state="visible")
            page.wait_for_function("!document.getElementById('start').disabled")
            assert page.locator("html").get_attribute("lang") == "en"
            assert page.locator("#assurance-hinglish").count() == 0
            assert not page.locator('[data-private="code"]').is_visible()
            assert page.locator("#advanced-settings").get_attribute("open") is None
            assert not page.locator(".remove-bot").is_visible()
            page.locator("#repeat-all").fill("2")
            page.locator("#repeat-all").press("Tab")
            assert page.locator("[data-repeat]").evaluate_all(
                "fields => fields.every(field => field.value === '2')"
            )
            page.get_by_text("View tests and customize repeats", exact=True).click()
            page.locator("[data-repeat]").first.fill("4")
            assert page.locator("#repeat-all").input_value() == ""
            page.get_by_text("View tests and customize repeats", exact=True).click()
            for _ in range(3):
                page.locator("#add-bot").click()
            assert page.locator(".bot").count() == 4
            assert page.locator("#add-bot").is_disabled()
            for _ in range(3):
                page.locator(".remove-bot").last.click()
            assert page.locator(".bot").count() == 1
            assert not page.locator(".remove-bot").is_visible()
            page.locator('[data-field="name"]').fill("OFFLINE UI TEST — no bot called")
            page.locator('[data-field="url"]').fill("http://localhost:9999/fixture")
            page.locator('[data-mode="black"]').uncheck()
            page.locator('[data-mode="white"]').check()
            assert page.locator('[data-private="code"]').is_visible()
            assert not page.locator('[data-field="url"]').is_visible()
            assert not page.locator("#judge-section").is_visible()
            assert not page.locator("#chat-test-options").is_visible()
            assert not page.locator("#judge-consent-row").is_visible()
            page.locator('[data-mode="gray"]').check()
            assert page.locator('[data-private="knowledge"]').is_visible()
            assert page.locator("#judge-section").is_visible()
            page.locator('[data-mode="gray"]').uncheck()
            assert not page.locator('[data-private="knowledge"]').is_visible()
            page.locator("#ownership").check()
            page.locator("#start").click()
            page.wait_for_function(
                "document.getElementById('assurance-status').textContent.includes('completed')",
                timeout=20000,
            )
            assert page.locator('[data-assurance-tab="black"]').is_disabled()
            page.locator('[data-assurance-tab="white"]').click()
            assert "Upload a source ZIP" in page.locator("#assurance-content").text_content()
            assert "Unknown" in page.locator("#assurance-content").text_content()
            assert page.locator(".result-stats").is_visible()
            assert not page.locator("#run-toolbar").is_visible()
            assert not page.locator("#assurance-stop").is_visible()
            assert not page.locator("#assurance-delete").is_visible()
            # Hold one response while switching to another. The newer selection
            # must render immediately; the late response must never replace it.
            from urllib.parse import parse_qs, urlparse

            ident = parse_qs(urlparse(page.url).query)["assessment"][0]
            saved = page.request.get(f"http://127.0.0.1:{port}/api/assurance/runs/{ident}").json()
            slow_id = "11111111-1111-4111-8111-111111111111"
            fast_id = "22222222-2222-4222-8222-222222222222"
            fast = copy.deepcopy(saved)
            fast["id"] = fast_id
            fast["combined"]["reason"] = "LATEST TEST RESULT"
            fast["ai_source_review"] = {
                "model": "OFFLINE SYNTHETIC JUDGE",
                "summary": "AI summary <img src=x onerror=alert(1)>",
                "checks": [
                    {
                        "test_id": fast["findings"][0]["test_id"],
                        "assessment": "not_tested",
                        "explanation": "Synthetic AI explanation with <b>literal evidence</b>.",
                        "fix": "Supply the missing source input.",
                    }
                ],
            }
            slow = copy.deepcopy(saved)
            slow["id"] = slow_id
            slow["combined"]["reason"] = "OLD DELAYED RESULT"
            held = []
            page.route(f"**/api/assurance/runs/{slow_id}", lambda route: held.append(route))
            page.route(
                f"**/api/assurance/runs/{fast_id}",
                lambda route: route.fulfill(json=fast),
            )
            page.route(
                "**/api/assurance/runs",
                lambda route: route.fulfill(
                    json=[
                        {"id": slow_id, "modes": ["white"], "status": "completed"},
                        {"id": fast_id, "modes": ["white"], "status": "completed"},
                    ]
                ),
            )
            page.locator("#refresh-history").click()
            page.wait_for_function(
                "document.querySelector('#test-history option[value=\"assessment:"
                + fast_id
                + "\"]') !== null"
            )
            page.locator("#test-history").select_option("assessment:" + slow_id)
            page.wait_for_function(
                "document.getElementById('assurance-status').textContent.includes('Loading')"
            )
            page.locator("#test-history").select_option("assessment:" + fast_id)
            page.get_by_text("LATEST TEST RESULT", exact=True).wait_for(timeout=3000)
            assert "AI summary <img" in page.locator("#assurance-content").inner_text()
            assert page.locator("#assurance-content img").count() == 0
            assert page.locator("#assurance-content b").count() == 0
            assert page.locator('[aria-label="AI source review"]').is_visible()
            assert held
            for route in held:
                route.fulfill(json=slow)
            page.wait_for_timeout(100)
            assert "LATEST TEST RESULT" in page.locator("#assurance-content").inner_text()
            assert "OLD DELAYED RESULT" not in page.locator("#assurance-content").inner_text()
            page.locator("#test-history").select_option("")
            assert page.locator("#results-empty").is_visible()
            assert not page.locator("#assurance-results").is_visible()
            page.locator("#test-history").select_option("assessment:" + fast_id)
            page.get_by_text("LATEST TEST RESULT", exact=True).wait_for(timeout=3000)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
            page.locator('nav [data-view="governance"]').click()
            assert page.locator("#assurance-governance").is_visible()
            assert "Assessment" in page.locator("#assurance-governance").text_content()
            # Retention/deletion in another tab must evict cached evidence on refresh.
            page.route(
                "**/api/assurance/runs/" + fast_id,
                lambda route: route.fulfill(status=404, json={"detail": "Not found"}),
            )
            page.locator("#refresh-history").click()
            page.get_by_text(
                "This test is no longer available. Choose another test or start a new one.",
                exact=True,
            ).wait_for(timeout=3000)
            page.locator('nav [data-view="results"]').click()
            assert page.locator("#results-empty").is_visible()
            assert not page.locator("#assurance-results").is_visible()
            assert "assessment=" not in page.url
            if os.getenv("STUDIO_UI_SCREENSHOT"):
                page.screenshot(path=os.environ["STUDIO_UI_SCREENSHOT"], full_page=True)
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
