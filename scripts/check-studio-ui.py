"""Browser check for the CURRENT Studio shell: navigation, report view and Judge calibration.

`check-exact-compare.py` drives the retained legacy `index.html`. This check drives the active
shell (`simple.html`) so the screens the owner actually uses are covered: Evaluate / Results /
Governance navigation, loading a saved report by URL, and the Governance Judge calibration panel
including its sampling controls.

Everything is synthetic: a fabricated completed Black Run in a temporary runtime directory, and a
server bound to loopback. No chatbot, Judge or any other provider is called, and no saved history
is read or written. On failure a screenshot and a Playwright trace are written to the directory
given by `--artifacts` so CI can upload them; they contain only this script's own fixtures.

    python scripts/check-studio-ui.py
    python scripts/check-studio-ui.py --artifacts runtime/ui-artifacts --port 2711
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Stored provider text that must render as characters, never as markup.
HOSTILE = '<img src=x onerror="window.__studioXss=1"><script>window.__studioXss=1</script>'


def synthetic_run(
    runner, studio_engine, Settings, Target, JudgeSelection, *, custom=False, missing=False
):
    """A completed simple-protocol Run with transcripts, so the Studio Results panel renders.

    Uses `simple_mode`, because the current Results panel reads `run["studio"]`, which only the
    simple protocol produces. One repeat per Category keeps the check fast.
    """
    protocol = studio_engine.settings_file()
    categories = [case["category"] for case in protocol["cases"]]
    cfg = Settings(
        targets=[Target(name="Synthetic UI bot", url="http://localhost:8800/chat")],
        simple_mode=not custom,
        categories=["injection"] if custom else categories,
        cases_per_category=1,
        judges=[JudgeSelection(model="synthetic-ui-judge", local=True)],
        consent=True,
        judge_consent=True,
        repeat_counts={category: 1 for category in categories},
    )
    run = runner.make_run(cfg)
    run["status"] = "completed"
    run["stage"] = "Complete"
    for position, case in enumerate(run["cases"]):
        case["completed"] = True
        passed = position % 3 != 0
        for result in case["results"]:
            # Half the Cases record a fallback evaluator, so the Run is a mixed panel and the
            # provenance view has both a requested and an actual evaluator to show.
            fell_back = position % 2 == 1
            result.update(
                status="passed" if passed else "failed",
                score=91.0 if passed else 12.0,
                reason="Synthetic UI assertion only " + HOSTILE,
                seconds=0.1,
                transcript=[
                    {
                        "input": str(turn),
                        "output": ("compliant reply " if passed else "non-compliant reply ")
                        + HOSTILE,
                        "seconds": 0.1,
                    }
                    for turn in (case.get("turns") or ["Fixture prompt"])
                ],
                judges=[
                    {
                        "provenance_version": 1,
                        "model": "synthetic-ui-fallback" if fell_back else "synthetic-ui-judge",
                        "requested_model": "synthetic-ui-judge",
                        "score": 91.0 if passed else 12.0,
                        "reason": "Synthetic UI assertion only",
                        "evidence": ["compliant reply" if passed else "non-compliant reply"],
                        "provider_model": "synthetic-ui-judge-rev-1",
                        "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
                        "provider": "local",
                        "local": True,
                        "family": "unclassified",
                        "fallback": fell_back,
                        "fallback_reasons": (
                            [{"model": "synthetic-ui-judge", "reason": "fixture quota stub"}]
                            if fell_back
                            else []
                        ),
                    }
                ],
            )
    if missing:
        for case in run["cases"]:
            for result in case["results"]:
                result.update(
                    status="not_tested",
                    score=None,
                    reason="Fixture provider HTTP 404",
                    judges=[],
                    transcript=[],
                )
    runner.aggregate(run)
    runner.save(run, cfg)
    return run


def serve(port: int):
    """Start the Studio on loopback and wait for its health endpoint."""
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        start_new_session=os.name != "nt",
        cwd=REPO,
    )
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError(f"Isolated UI server exited with code {process.returncode}.")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
                return process
        except Exception:  # noqa: BLE001 - the server is simply not listening yet
            time.sleep(0.2)
    process.kill()
    raise RuntimeError(f"Isolated UI server did not become healthy on port {port}.")


def panel_visible(page, name: str) -> bool:
    return page.locator(f"[data-panel={name}]").is_visible()


def check_navigation(page, base: str) -> dict:
    """Evaluate / Results / Governance must switch panels and survive Back."""
    page.goto(base + "/", wait_until="networkidle")
    page.wait_for_selector("[data-panel=evaluate]")
    assert panel_visible(page, "evaluate"), "Evaluate is not the default panel"
    for name in ("results", "governance"):
        page.locator(f"nav a[data-view={name}]").click()
        page.wait_for_function(
            "name => !document.querySelector(`[data-panel=${name}]`).hidden", arg=name
        )
        assert panel_visible(page, name), f"{name} panel did not become visible"
        assert not panel_visible(page, "evaluate"), f"Evaluate stayed visible behind {name}"
    page.go_back()
    page.wait_for_function("() => !document.querySelector('[data-panel=results]').hidden")
    assert panel_visible(page, "results"), "Back did not restore the Results panel"
    return {"navigation": "passed"}


def check_saved_report(page, base: str, run: dict) -> dict:
    """A saved report must open from its URL and escape stored provider text."""
    page.goto(f"{base}/?run={run['id']}", wait_until="networkidle")
    page.wait_for_selector("#case-results details")
    assert panel_visible(page, "results"), "A run URL did not open the Results panel"
    label = page.locator("#selected-run").inner_text()
    assert "Synthetic UI bot" in label, f"The selected run is not named in the header: {label!r}"
    page.locator("#case-results details").first.locator("summary").click()
    body = page.locator("#case-results").inner_text()
    assert "compliant reply" in body or "non-compliant reply" in body, (
        "No synthetic transcript text reached the Results panel"
    )
    assert HOSTILE in body, "Stored provider text was not rendered literally"
    assert page.evaluate("() => window.__studioXss === undefined"), (
        "Stored provider markup executed instead of rendering as text"
    )
    assert page.locator("#case-results img").count() == 0, (
        "Stored provider markup produced a real element"
    )
    return {"saved_report": "passed", "escaped_model_output": "passed"}


def check_calibration(page, base: str, run: dict) -> dict:
    """Results must offer the blind-sampling controls; Governance must state alignment."""
    page.goto(f"{base}/?run={run['id']}", wait_until="networkidle")
    page.wait_for_selector("#case-results details")
    page.wait_for_selector("#calibration-heading")
    page.locator("#calibration-panel > summary").click()
    page.wait_for_selector("#cal-size")

    controls = page.locator("#calibration-body").inner_text()
    assert "Spread the sample across Categories" in controls, "Category spreading is not offered"
    assert "Include saved failures as well as successes" in controls, (
        "Outcome balancing is not offered"
    )
    assert "Labeling stays blind" in controls, "The blind-labeling note is missing"
    assert page.locator("#cal-stratify").is_checked(), "Category spreading must default to on"
    assert not page.locator("#cal-balance").is_checked(), "Outcome balancing must default to off"
    eligible = page.locator("#calibration-body .cal-pick").count()
    assert eligible >= 10, f"Only {eligible} eligible conversations reached the picker"

    status = page.locator("#calibration-status").inner_text()
    assert "not calibrated" in status.lower() or "uncalibrated" in status.lower(), (
        f"An unlabeled Studio must report the Judge as uncalibrated, not {status!r}"
    )
    assert "Synthetic UI assertion only" not in controls, (
        "The original Judge's reason leaked into the blind labeling screen"
    )

    page.locator("nav a[data-view=governance]").click()
    page.wait_for_function("() => !document.querySelector('[data-panel=governance]').hidden")
    page.wait_for_function(
        "() => document.querySelector('#gov-human').textContent.trim().length > 0"
    )
    human = page.locator("#gov-human").inner_text()
    assert "uncalibrated" in human.lower() or "not calibrated" in human.lower(), (
        f"Governance does not report human alignment for this Run: {human!r}"
    )
    assert "model-to-model" in human.lower(), (
        "Governance must separate human alignment from model-to-model Judge agreement"
    )
    integrity = page.locator("#gov-integrity").inner_text()
    assert "model vs model" in integrity.lower(), (
        "The Judge agreement metric must say it compares models with each other"
    )
    return {
        "calibration_panel": "passed",
        "eligible_conversations": eligible,
        "governance_alignment": "passed",
    }


def check_provenance(page, base: str, run: dict) -> dict:
    """Results must name the actual evaluator, the fallback reason and the revision caveat."""
    page.goto(f"{base}/?run={run['id']}", wait_until="networkidle")
    page.wait_for_selector("#evaluator-provenance")
    page.locator("#evaluator-provenance > summary").click()
    table = page.locator("#evaluator-provenance").inner_text()
    assert "synthetic-ui-judge" in table, "the requested evaluator is not listed"
    assert "synthetic-ui-fallback" in table, "the fallback evaluator is not listed"
    assert "synthetic-ui-judge-rev-1" in table, "the returned identifier is not shown"
    assert "not guaranteed immutable revisions" in table, "the revision caveat is missing"
    assert "uncalibrated" in table.lower(), "human calibration status is not shown per evaluator"
    assert "not interchangeable" in table.lower(), "a mixed panel is not qualified"

    rows = page.locator("#case-results details")
    for index in range(rows.count()):
        rows.nth(index).locator("summary").click()
    page.wait_for_function(
        "() => document.querySelectorAll('#case-results details[open]').length > 0"
    )
    body = page.locator("#case-results").inner_text()
    assert "Actual evaluator:" in body, "no per-verdict provenance line"
    assert "fixture quota stub" in body or "Fallback evaluator" in body, (
        "a fallback verdict does not say why the requested Judge was not used"
    )
    return {"provenance": "passed"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=2711)
    parser.add_argument(
        "--artifacts",
        default="",
        help="Directory for a failure screenshot and trace. Defaults to the temporary runtime.",
    )
    args = parser.parse_args(argv)
    base = f"http://127.0.0.1:{args.port}"

    with ExitStack() as cleanup:
        runtime = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="studio-shell-ui-"))
        os.environ["STUDIO_RUNTIME"] = runtime
        os.environ.setdefault("STUDIO_AUTO_RESUME", "0")
        sys.path.insert(0, str(REPO))
        from playwright.sync_api import sync_playwright

        from app import database
        from app.blackbox import runner, studio_engine
        from app.blackbox.schema import JudgeSelection, Settings, Target
        from scripts.process_cleanup import stop_process_tree

        cleanup.callback(database.close)
        artifacts = Path(args.artifacts or runtime)
        artifacts.mkdir(parents=True, exist_ok=True)

        run = synthetic_run(runner, studio_engine, Settings, Target, JudgeSelection)
        custom = synthetic_run(runner, studio_engine, Settings, Target, JudgeSelection, custom=True)
        missing = synthetic_run(
            runner, studio_engine, Settings, Target, JudgeSelection, custom=True, missing=True
        )
        process = serve(args.port)
        cleanup.callback(stop_process_tree, process)

        report: dict = {"run_id": run["id"], "artifacts": str(artifacts)}
        with sync_playwright() as play:
            browser = play.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                report |= check_navigation(page, base)
                report |= check_saved_report(page, base, run)
                report |= check_calibration(page, base, run)
                report |= check_provenance(page, base, run)
                check_saved_report(page, base, custom)
                page.locator("#cost-analysis > summary").click()
                page.get_by_text("Bot unit economics", exact=True).wait_for(state="visible")
                assert page.locator('#cost-panel [data-cost-group="category"]').count() == 1
                page.locator("#analysis-details > summary").click()
                page.get_by_text("Request reliability and speed", exact=True).wait_for(
                    state="visible"
                )
                assert page.locator("#charts svg").count() > 0
                page.locator("#comparison-details > summary").click()
                page.get_by_text("Regression checks", exact=True).wait_for(state="visible")
                assert "Expected:" in page.locator("#case-results").inner_text()
                assert page.locator("#case-results .evidence-details img").count() == 0
                report["full_analysis_sections"] = "passed"
                assert "Saved evaluation results" in page.locator("#verdict").inner_text()
                assert "Measured quality" in page.locator("#scores").inner_text()
                page.goto(f"{base}/?run={missing['id']}#evaluate", wait_until="networkidle")
                page.wait_for_function(
                    "() => document.querySelector('#run-label').textContent.includes('scored')"
                )
                assert page.locator("#test-history").is_visible()
                page.get_by_text("View selected run results", exact=True).click()
                page.wait_for_selector("#case-results details")
                assert "Not measured" in page.locator("#scores").inner_text()
                page.locator("#case-results details").first.locator("summary").click()
                page.get_by_text("Fixture provider HTTP 404", exact=True).wait_for(state="visible")
                page.locator("#test-history").select_option("run:" + custom["id"])
                page.wait_for_function(
                    "id => document.querySelector('#verdict').textContent.includes(id)",
                    arg=custom["id"],
                )
                assert "Fixture provider HTTP 404" not in page.locator("#case-results").inner_text()
                report["custom_and_unscored_history"] = "passed"
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(f"{base}/?run={run['id']}", wait_until="networkidle")
                page.wait_for_selector("#case-results details")
                assert page.evaluate(
                    "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                ), "The Results panel scrolls sideways at phone width"
                report["mobile_layout"] = "passed"
                assert not errors, errors
                report["browser_errors"] = errors
            except Exception:
                page.screenshot(path=str(artifacts / "failure.png"), full_page=True)
                context.tracing.stop(path=str(artifacts / "failure-trace.zip"))
                report["browser_errors"] = errors
                print(json.dumps(report, indent=2), file=sys.stderr)
                print(f"Saved failure artifacts to {artifacts}", file=sys.stderr)
                raise
            context.tracing.stop()
            browser.close()
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
