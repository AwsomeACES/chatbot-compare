"""T-019: the finding review form is keyboard-usable and the wording is consistent.

The review flow used `prompt()` and `confirm()`, which cannot carry a label, an error message or
a required-length rule. These tests drive the replacement dialog with the keyboard only, and
check that a Gray declaration is never presented as having been found in source.
"""

import socket
import threading
import time
import uuid

import pytest
import uvicorn

from app import database as db
from app.assurance import service
from app.assurance.models import Evidence, Finding
from app.blackbox_app import app

HEADERS = {"X-Studio-Request": "1"}


@pytest.fixture(autouse=True)
def only_this_test_records():
    """Remove records this file creates, so a later test never sees them.

    The suite shares one temporary database. Leftover saved runs changed what auto-resume and
    the history listings found, which failed unrelated tests in a full-suite run.
    """
    kinds = ("blackbox", "assurance")
    before = {kind: {r["id"] for r in db.all_records(kind)} for kind in kinds}
    yield
    for kind in kinds:
        for record in db.all_records(kind):
            if record["id"] not in before[kind]:
                db.delete(kind, record["id"])


def declaration(mode: str, test_id: str, category: str) -> dict:
    row = Finding(
        mode=mode,
        category=category,
        test_id=test_id,
        verdict="exists",
        evidence=[Evidence(kind="configuration", excerpt="The operator states a control exists.")],
        explanation="A control was declared.",
        checked=test_id,
        consequence="A declaration is not proof that the control works.",
        fix="Supply behavioural evidence.",
        confidence="Low",
    )
    row.tool = "fixture"
    return row.model_dump()


def reviewable_failure() -> dict:
    row = Finding(
        mode="white",
        category="secrets",
        test_id="hardcoded_secrets",
        verdict="fail",
        severity="Critical",
        evidence=[Evidence(kind="code", excerpt="FIXTURE_EXCERPT", file="bot.py", line=3)],
        explanation="A credential-shaped literal was matched.",
        checked="hardcoded_secrets",
        consequence="A leaked credential allows account access.",
        fix="Rotate and move it out of source.",
    )
    row.tool = "fixture"
    return row.model_dump()


def seeded_assessment() -> dict:
    run = {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "modes": ["gray", "white"],
        "config": {"targets": [{"name": "Fixture bot"}], "judges": []},
        "findings": [
            reviewable_failure(),
            declaration("gray", "retention", "privacy"),
            declaration("white", "endpoint_controls", "access"),
        ],
        "input_hashes": {},
        "audit": [],
        "upload_retention_days": 0,
    }
    # Sealed by the real checkpoint, so the combiner output and the audit anchor are genuine.
    # A hand-built record fails the integrity check the review endpoint enforces.
    service.checkpoint(run)
    return run


@pytest.fixture(scope="module")
def studio_server():
    """One loopback server for this file. Four servers and four browsers churned enough
    resources to make the page load intermittently slow inside a full-suite run."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as play:
        instance = play.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser):
    """A fresh page per test, so one test's dialog state cannot reach the next."""
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


def open_findings(page, base: str, run: dict, mode: str = "white"):
    """Open the seeded assessment and show one mode's findings.

    Waits for this exact record rather than for status text, because other tests leave their own
    saved assessments in the shared database and the status line could describe one of those.
    """
    page.goto(f"{base}/?assessment={run['id']}")
    try:
        page.wait_for_function(
            "expected => window.AssuranceUI?.current?.id === expected",
            arg=run["id"],
            timeout=30000,
        )
    except Exception:
        # Report what the page actually shows, so a timeout names a cause.
        raise AssertionError(
            "the seeded assessment never loaded. "
            f"url={page.url!r} "
            f"status={page.locator('#assurance-status').inner_text()!r} "
            f"notice={page.locator('#notice').inner_text()!r} "
            f"booted={page.evaluate('() => Boolean(window.AssuranceUI)')} "
            f"labels={page.evaluate('() => Boolean(window.StudioStatus)')} "
            f"selected={page.evaluate('() => window.AssuranceUI?.id ?? null')!r}"
        ) from None
    page.locator(f'[data-assurance-tab="{mode}"]').click()
    page.wait_for_selector("[data-finding]", timeout=30000)


def test_a_gray_declaration_is_not_described_as_found_in_code(studio_server, page):
    run = seeded_assessment()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_findings(page, studio_server, run, mode="gray")
    gray = page.locator('[data-finding="0:gray:retention"]')
    gray.locator("summary").click()
    text = gray.inner_text()
    assert "Found in code" not in text, "a Gray declaration must not claim source evidence"
    assert "Declaration only" in text
    page.locator('[data-assurance-tab="white"]').click()
    page.wait_for_selector('[data-finding="0:white:endpoint_controls"]')
    white = page.locator('[data-finding="0:white:endpoint_controls"]')
    white.locator("summary").click()
    white_text = white.inner_text()
    assert "Declaration only" in white_text, "a declaration is labelled the same way in every mode"
    assert "Found in code" not in white_text, (
        "even a source declaration must not be presented as proven"
    )
    assert "not proof" in white_text or "not verified" in white_text, (
        "the finding must say a declaration is not proof the control works"
    )
    assert not errors, errors


def test_the_review_form_is_completable_with_the_keyboard_only(studio_server, page):
    run = seeded_assessment()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # A browser dialog would block the test instead of being driven by it.
    page.on("dialog", lambda dialog: errors.append(f"browser dialog used: {dialog.type}"))
    open_findings(page, studio_server, run)

    finding = page.locator('[data-finding="0:white:hardcoded_secrets"]')
    finding.locator("summary").click()
    finding.locator("[data-review]").click()
    page.wait_for_selector("#finding-review[open]")

    reason = page.locator("#finding-review-reason")
    assert reason.evaluate("node => node === document.activeElement"), (
        "the reason field should receive focus when the form opens"
    )
    # A labelled field, not an unlabelled browser prompt.
    assert page.locator("label[for=finding-review-reason]").count() == 1

    # Too short: the form must refuse and say why, rather than saving a useless reason.
    page.keyboard.type("too short")
    page.locator("#finding-review-save").click()
    page.wait_for_selector("#finding-review-error:not([hidden])")
    assert "at least 10 characters" in page.locator("#finding-review-error").inner_text()
    assert page.locator("#finding-review[open]").count() == 1

    reason.fill("")
    page.keyboard.type("These are model identifiers rather than credentials.")
    # Choose the false-positive option with the keyboard.
    page.locator("input[name=decision][value=false_positive]").focus()
    page.keyboard.press("Space")
    assert page.locator("input[name=decision][value=false_positive]").is_checked()
    page.locator("#finding-review-save").click()

    try:
        page.wait_for_function(
            "() => !document.getElementById('finding-review').open", timeout=10000
        )
    except Exception:
        raise AssertionError(
            "the review did not save: "
            + page.locator("#finding-review-error").inner_text()
            + " | notice: "
            + page.locator("#notice").inner_text()
        ) from None
    assert not errors, errors

    saved = db.get("assurance", run["id"])
    reviewed = next(f for f in saved["findings"] if f["test_id"] == "hardcoded_secrets")
    assert reviewed["review_reason"].startswith("These are model identifiers")
    assert reviewed["original_finding"]["verdict"] == "fail", "the original Finding is preserved"


def test_escape_closes_the_review_form_without_recording_anything(studio_server, page):
    run = seeded_assessment()
    open_findings(page, studio_server, run)
    finding = page.locator('[data-finding="0:white:hardcoded_secrets"]')
    finding.locator("summary").click()
    finding.locator("[data-review]").click()
    page.wait_for_selector("#finding-review[open]")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.getElementById('finding-review').open")

    saved = db.get("assurance", run["id"])
    unchanged = next(f for f in saved["findings"] if f["test_id"] == "hardcoded_secrets")
    assert unchanged["verdict"] == "fail"
    assert not unchanged.get("overridden")
    assert not unchanged.get("review_reason")


def test_the_matrix_reason_is_reachable_by_keyboard(studio_server, page):
    """A title tooltip alone is not readable without a pointer."""
    run = seeded_assessment()
    open_findings(page, studio_server, run)
    page.locator('[data-assurance-tab="combined"]').click()
    page.locator("#assurance-content details", has_text="Compare all categories").click()
    page.wait_for_selector(".cell-label")
    label = page.locator(".cell-label").first
    assert label.get_attribute("tabindex") == "0"
    described = label.get_attribute("aria-describedby")
    assert described
    assert page.locator(f"#{described}").inner_text().strip(), (
        "the described reason must be real text, not only a tooltip"
    )


def test_one_assessment_without_recorded_modes_does_not_break_the_history_picker(
    studio_server, page
):
    """Found while debugging this file: `r.modes.map` threw on a record with no modes.

    One malformed or legacy row emptied the history picker and left the whole Results screen
    unusable, so every other saved assessment became unreachable.
    """
    broken = {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "config": {"targets": [{"name": "Legacy record"}], "judges": []},
        "findings": [],
        "audit": [],
    }
    broken.pop("modes", None)  # Explicit: this record has no recorded modes.
    db.save("assurance", broken)
    run = seeded_assessment()

    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_findings(page, studio_server, run)

    assert not errors, errors
    options = page.locator("#test-history option").all_inner_texts()
    assert any("Modes not recorded" in text for text in options), (
        "the record with no modes should be listed as such, not crash the picker"
    )
    assert any(run["id"][:8] in text for text in options), (
        "the healthy record must still be selectable"
    )
