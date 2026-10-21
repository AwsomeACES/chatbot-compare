"""Browser regressions for saved comparison evidence, with all HTTP mocked."""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "blackbox_static"
RUN_ID = "11111111-1111-4111-8111-111111111111"
BOT_NAME = 'Bot <img src=x onerror="window.injected=true">'
JUDGE_NAME = 'Judge <svg onload="window.injected=true">'
REVIEW_REASON = "Review <b>untrusted</b> judge evidence."


def _saved_run() -> dict:
    """Supply a completed report without creating runs or contacting providers."""
    category = {"id": "memory", "category": "memory", "name": "Conversation memory"}
    bots = []
    results = []
    for name, score in [(BOT_NAME, 95), ("Second bot", 90)]:
        bots.append(
            {
                "name": name,
                "score": score,
                "tested": 1,
                "planned": 1,
                "categories": [
                    {**category, "score": score, "quality": score, "tested": 1, "planned": 1}
                ],
            }
        )
        results.append(
            {
                "status": "passed",
                "score": score,
                "reason": "Remembered the supplied preference.",
                "transcript": [{"input": "What colour?", "output": "Blue", "seconds": 0.01}],
                "judges": [{"model": JUDGE_NAME, "score": score, "evidence": ["Blue"]}],
            }
        )
    return {
        "id": RUN_ID,
        "status": "completed",
        "stage": "Done",
        "progress": 100,
        "config": {
            "simple_mode": True,
            "repeat_counts": {"memory": 1},
            "policy": "",
            "scope": "",
        },
        "targets": [{"name": bot["name"], "url": "http://unused.invalid"} for bot in bots],
        "categories": ["memory"],
        "protocol_snapshot": {"cases": [category], "tie_margin": 2},
        "cases": [
            {
                "id": "memory-1",
                "name": "Remember a preference",
                "category": "memory",
                "repeat": 1,
                "completed": True,
                "results": results,
            }
        ],
        "studio": {
            "bots": bots,
            "winner": None,
            "confidence_note": "Human review required before declaring a winner.",
            "warnings": [],
            "formula": "Weighted measured outcomes.",
        },
        "audit": [],
    }


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        instance = runtime.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def comparison_page(browser):
    """Load real frontend files; reject any unmocked or write request."""
    context = browser.new_context()
    page = context.new_page()
    errors = []
    unexpected = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def load(run: dict) -> None:
        settings = {
            "cases": run["protocol_snapshot"]["cases"],
            "tie_margin": 99,
            "default_repeats": 3,
            "saved_judge": {"configured": False},
            "judges": [],
            "ollama_models": [],
            "execution": {},
        }

        def respond(route) -> None:
            request = route.request
            parsed = urlparse(request.url)
            path = parsed.path
            if parsed.hostname != "studio.test" or request.method != "GET":
                unexpected.append((request.method, request.url))
                route.abort()
            elif path == "/api/studio/settings":
                route.fulfill(json=settings)
            elif path == "/api/blackbox/runs":
                route.fulfill(json=[run])
            elif path == "/api/assurance/runs":
                route.fulfill(json=[])
            elif path == f"/api/blackbox/runs/{RUN_ID}":
                route.fulfill(json=run)
            elif path == f"/api/studio/runs/{RUN_ID}/events":
                payload = {"active_seconds": 1, "status": "completed", "bots": []}
                route.fulfill(
                    content_type="text/event-stream", body=f"data: {json.dumps(payload)}\n\n"
                )
            elif path == "/":
                route.fulfill(path=STATIC / "simple.html", content_type="text/html")
            elif path.count("/") == 1 and (STATIC / path[1:]).is_file():
                content_type = "text/css" if path.endswith(".css") else "text/javascript"
                route.fulfill(path=STATIC / path[1:], content_type=content_type)
            else:
                unexpected.append((request.method, request.url))
                route.abort()

        context.route("**/*", respond)
        page.goto(f"http://studio.test/?run={RUN_ID}#results")
        page.wait_for_function("!document.getElementById('start').disabled")
        page.locator("#scores table tbody tr").wait_for()

    yield page, load
    context.close()
    assert not errors, errors
    assert not unexpected, unexpected


def test_comparison_evidence_and_review_checks_escape_model_and_bot_text(comparison_page):
    page, load = comparison_page
    run = _saved_run()
    run["studio"]["comparison"] = {
        "method_note": "Paired scenarios; repeats are not independent evidence.",
        "tie_margin": 2,
        "policy": {"min_scenarios": 10, "min_scenarios_per_category": 2, "confidence": 0.95},
        "pairs": [
            {
                "a": 0,
                "b": 1,
                "scenarios": 4,
                "difference": 5,
                "low": None,
                "high": None,
                "reason": "Insufficient independent scenarios.",
            }
        ],
        "readiness": [
            {"bot": 0, "meets_checks": False, "reasons": [REVIEW_REASON]},
            {"bot": 1, "meets_checks": True, "reasons": []},
        ],
        "category_results": {"memory": {"leaders": [0], "reason": "Higher category score."}},
    }
    load(run)
    page.get_by_text("Comparison evidence and review checks", exact=True).click()
    evidence = page.locator("#verdict details").filter(has=page.locator("table"))
    assert "Saved tie margin: 2 points" in evidence.inner_text()
    assert "Confidence target across all bot pairs: 95%" in evidence.inner_text()
    pair = evidence.locator("table").nth(0).locator("tbody tr")
    assert pair.locator("td").all_text_contents() == [
        f"{BOT_NAME} vs Second bot",
        "4",
        "5",
        "Insufficient evidence",
        "Insufficient independent scenarios.",
    ]
    review = evidence.locator("table").nth(1).locator("tbody tr")
    assert review.nth(0).locator("td").all_text_contents() == [
        BOT_NAME,
        "Review required",
        REVIEW_REASON,
    ]
    assert "Meets configured checks" in review.nth(1).inner_text()
    assert "do not certify production readiness" in evidence.inner_text()
    assert page.locator("#scores tbody tr td").last.inner_text() == BOT_NAME
    assert page.locator("#verdict h3").inner_text() == "Comparison summary"

    page.locator("#case-results summary").click()
    page.locator(".judge-reason").first.wait_for()
    assert JUDGE_NAME in page.locator(".judge-reason").first.inner_text()
    assert page.locator("#verdict img, #verdict b, #scores img, #case-results svg").count() == 0
    assert page.evaluate("window.injected === undefined")


@pytest.mark.parametrize(
    ("saved_margin", "expected"),
    [(2, BOT_NAME), (10, "Tie"), (None, "Saved comparison policy unavailable")],
)
def test_legacy_comparison_uses_saved_tie_margin_not_live_settings(
    comparison_page, saved_margin, expected
):
    page, load = comparison_page
    run = _saved_run()
    if saved_margin is None:
        run["protocol_snapshot"].pop("tie_margin")
    else:
        run["protocol_snapshot"]["tie_margin"] = saved_margin
    load(run)
    assert page.locator("#scores tbody tr td").last.inner_text() == expected
    assert page.get_by_text("Comparison evidence and review checks", exact=True).count() == 0
