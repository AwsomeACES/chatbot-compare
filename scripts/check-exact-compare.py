"""Isolated UI verification: synthetic fixtures, no target/judge provider calls."""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with ExitStack() as cleanup:
    runtime = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="studio-compare-ui-"))
    os.environ["STUDIO_RUNTIME"] = runtime
    from playwright.sync_api import sync_playwright

    from app import database
    from app.blackbox import runner
    from app.blackbox.schema import Settings, Target
    from app.blackbox_app import exact_case_set
    from scripts.process_cleanup import stop_process_tree

    cleanup.callback(database.close)

    cfg = Settings(
        targets=[
            Target(name=f"Synthetic UI bot {i + 1}", url=f"http://localhost:{8800 + i}")
            for i in range(4)
        ],
        categories=["injection"],
        judge_enabled=False,
        custom_cases=[
            dict(
                category="injection",
                name=f"Fixture scenario {i}",
                turns=[f"Fixture {i}"],
                expected="Do not emit marker",
                checks={"canary": "marker"},
            )
            for i in range(10)
        ],
    )
    run = runner.make_run(cfg)
    run["status"] = "completed"
    for c in run["cases"]:
        c["completed"] = True
        for i, r in enumerate(c["results"]):
            r.update(
                status="passed" if i == 0 else "failed",
                score=100 if i == 0 else 0,
                reason="Synthetic UI assertion only",
                seconds=0.1,
                transcript=[
                    {
                        "input": "Fixture",
                        "output": "safe" if i == 0 else "marker",
                        "seconds": 0.1,
                    }
                ],
                deterministic_checks=[{"kind": "forbidden", "term": "marker", "met": i == 0}],
            )
        c["pairs"] = {
            f"{a}:{b}": {
                "status": "judged",
                "winner": 0 if a == 0 else "tie",
                "reason": "Synthetic UI comparison",
            }
            for a in range(4)
            for b in range(a + 1, 4)
        }
    runner.aggregate(run)
    runner.save(run, cfg)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "2710",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        start_new_session=os.name != "nt",
        cwd=Path(__file__).resolve().parents[1],
    )
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f"Isolated UI server exited with code {proc.returncode}.")
            try:
                with urllib.request.urlopen("http://127.0.0.1:2710/api/health", timeout=1):
                    pass
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Isolated UI server did not become healthy on port 2710.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(
                "http://127.0.0.1:2710/index.html?run=" + run["id"],
                wait_until="networkidle",
            )
            page.wait_for_selector("#comparison table")
            assert "Head-to-head matrix" in page.locator("#comparison").inner_text()
            assert page.locator("#summaries [data-baseline]").count() == 4
            page.locator("#cases details").first.locator("summary").click()
            assert "Exact checks" in page.locator("#cases details").first.inner_text()
            page.evaluate("render()")
            assert page.locator("#cases details").first.get_attribute("open") is not None
            page.locator("#summaries [data-baseline]").first.click()
            page.wait_for_function(
                "document.querySelector('#notice').textContent.includes('Saved for future runs')"
            )
            page.select_option("#mode", "compare4")
            assert page.locator("#targets .basic-target:visible").count() == 4
            page.select_option("#evaluation-method", "exact")
            page.check("#consent")
            page.check("#ownership")
            for i in range(4):
                page.fill(f"#url-{i}", f"http://localhost:{8800 + i}")
            page.locator("#advanced > summary").click()
            page.get_by_text("Import test cases (JSON)", exact=True).click()
            page.set_input_files(
                "#case-set-file",
                {
                    "name": "synthetic-exact.json",
                    "mimeType": "application/json",
                    "buffer": json.dumps(exact_case_set()).encode(),
                },
            )
            page.wait_for_function(
                "document.querySelector('#case-set-status').textContent.includes('Loaded 2')"
            )
            page.get_by_text("AI judge and run limits", exact=True).click()
            page.fill("#case-concurrency", "3")
            page.fill("#target-concurrency", "2")
            page.fill("#judge-concurrency", "3")
            page.fill("#target-pause", "0.5")
            page.fill("#judge-pause", "0.75")
            payloads = []

            def capture(route):
                payloads.append(route.request.post_data_json)
                route.fulfill(
                    status=422,
                    content_type="application/json",
                    body=json.dumps({"detail": "UI verification only; no chatbot requests sent."}),
                )

            page.route("**/api/blackbox/easy-run", capture)
            page.locator("#start").click()
            page.wait_for_selector("#readiness-preview[open]")
            text = page.locator("#readiness-body").inner_text()
            assert (
                "Hallucination testing (answer accuracy): Ready" in text
                and "Prompt injection: Ready" in text
            )
            page.locator("#readiness-go").click()
            page.wait_for_selector("#cost-preview[open]")
            assert "(0 judge requests)" in page.locator("#cost-preview-body").inner_text()
            page.locator("#cost-preview-go").click()
            page.wait_for_function(
                "document.querySelector('#notice').textContent.includes('UI verification only')"
            )
            assert len(payloads[0]["targets"]) == 4 and payloads[0]["judge_enabled"] is False
            assert set(payloads[0]["categories"]) == {"hallucination", "injection"}
            assert [
                payloads[0][k]
                for k in (
                    "case_concurrency",
                    "target_concurrency",
                    "judge_concurrency",
                    "request_pause_seconds",
                    "judge_pause_seconds",
                )
            ] == [3, 2, 3, 0.5, 0.75]
            page.evaluate("current.status='running';render()")
            assert page.locator("#start").is_enabled()
            assert not errors, errors
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(
                path=str(Path(runtime) / "ui-mobile-check.png"),
                full_page=False,
            )
            print(
                json.dumps(
                    {
                        "browser_errors": errors,
                        "four_target_setup": "passed",
                        "exact_only_preview": "passed",
                        "cost_preview": "0 judge requests",
                        "matrix_and_case_details": "passed",
                        "baseline_save": "passed",
                        "concurrency_controls": "passed",
                        "start_another_run": "passed",
                        "provider_calls": 0,
                    }
                )
            )
            browser.close()
    finally:
        stop_process_tree(proc)
