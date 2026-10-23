"""The verification scripts CI actually runs (Phase D of the 2026-10-23 review).

The review found that CI's only real browser check drove the retained legacy `index.html`, while
eleven `scripts/check-*.cjs` files could not run from a clean checkout at all. Configuration
silently drifting away from the current UI is the failure mode these tests guard.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/quality.yml"

#: Removed on 2026-10-23: they required Playwright from the gitignored runtime directory,
#: hardcoded one machine's chrome.exe path and deleted run identifiers, and asserted retired
#: selectors. PROGRESS.md records the per-file reasons.
REMOVED = (
    "check-blackbox.cjs",
    "check-category-labels.cjs",
    "check-comparison.cjs",
    "check-easy-setup.cjs",
    "check-import-selection.cjs",
    "check-judge-experience.cjs",
    "check-judge-providers.cjs",
    "check-large-upload.cjs",
    "check-readability.cjs",
    "check-scoring.cjs",
    "check-simple-ui.cjs",
)


def steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["quality"]["steps"]


def commands() -> str:
    return "\n".join(str(step.get("run", "")) for step in steps())


def test_ci_runs_the_current_shell_browser_check():
    assert "scripts/check-studio-ui.py" in commands(), (
        "CI must run the browser check for the current shell, not only the legacy interface"
    )


def test_ci_still_runs_the_retained_legacy_browser_check():
    """The legacy interface stays served, so its coverage must not be dropped silently."""
    assert "scripts/check-exact-compare.py" in commands()


def test_ci_installs_linux_browser_system_dependencies():
    """Chromium needs its shared libraries on the Ubuntu runner."""
    text = commands()
    assert "--with-deps chromium" in text, "Linux browser system dependencies are not installed"
    assert "$IsLinux" in text, "the --with-deps install must be conditional on Linux"


def test_ci_keeps_browser_failure_artifacts():
    upload = [s for s in steps() if "upload-artifact" in str(s.get("uses", ""))]
    assert upload, "CI must keep a trace or screenshot when a browser check fails"
    assert any(step.get("if") == "failure()" for step in upload), (
        "artifacts should be uploaded on failure, not on every run"
    )


def test_ci_covers_every_supported_platform():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["quality"]["strategy"]["matrix"]["os"]
    assert set(matrix) == {"windows-latest", "ubuntu-latest", "macos-latest"}


def test_the_current_browser_check_is_self_contained():
    """It must bring its own server and fixtures, so CI needs no running Studio."""
    text = (ROOT / "scripts/check-studio-ui.py").read_text(encoding="utf-8")
    assert "tempfile.TemporaryDirectory" in text, "it must use a temporary runtime directory"
    assert "STUDIO_RUNTIME" in text, "it must not touch the owner's saved history"
    assert "uvicorn" in text, "it must start its own server"
    assert "127.0.0.1" in text, "the server must stay on loopback"
    assert "runtime/ui-check" not in text, "it must not load Playwright from the runtime directory"
    assert "Program Files" not in text, "it must not hardcode a browser path"
    assert "data-view=" in text and "data-panel=" in text, "it must drive the shell navigation"
    for view in ("evaluate", "results", "governance"):
        assert view in text, f"the {view} view is not exercised"
    assert "#calibration-panel" in text, "Judge calibration is not exercised"
    assert "#gov-human" in text, "Governance human alignment is not exercised"


def test_removed_browser_checks_are_gone_and_unreferenced():
    for name in REMOVED:
        assert not (ROOT / "scripts" / name).exists(), f"{name} came back"
    searched = [
        *ROOT.glob("*.md"),
        *ROOT.glob("*.json"),
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / ".github/workflows").glob("*.yml"),
        *(ROOT / "scripts").iterdir(),
    ]
    allowed = {"PROGRESS.md", "legacy-guide.md", "test_verification_wiring.py"}
    for path in searched:
        if not path.is_file() or path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in REMOVED:
            assert name not in text, f"{path.name} still references the removed {name}"


def test_no_tracked_script_loads_playwright_from_the_runtime_directory():
    """`runtime/` is gitignored, so anything requiring it cannot run from a clean checkout."""
    offenders = []
    for path in (ROOT / "scripts").iterdir():
        if path.is_file() and path.suffix in {".py", ".cjs", ".js"}:
            if re.search(r"runtime/ui-check", path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(path.name)
    assert not offenders, f"these load Playwright from the gitignored runtime: {offenders}"
