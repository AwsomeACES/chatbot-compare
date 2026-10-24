"""Consistent status wording and measured contrast (T-019).

Two things are locked in here: every screen reads one shared label map rather than keeping its
own copy, and the active stylesheet's text colours are measured against WCAG 2.2 AA rather than
declared accessible.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app/blackbox_static"
LABELS = STATIC / "status-labels.js"

SCREENS = ("simple.js", "assurance.js", "governance.js", "calibration.js")

#: The wording the review asked to be consistent across screens.
REQUIRED = ("Not tested", "Declaration only", "Estimated", "Unknown", "Needs review")


def labels_source() -> str:
    return LABELS.read_text(encoding="utf-8")


# --- one source of wording ---------------------------------------------------------------------


@pytest.mark.parametrize("phrase", REQUIRED)
def test_every_required_label_is_defined_once_in_the_shared_map(phrase):
    source = labels_source()
    assert f'"{phrase}"' in source, f"{phrase!r} is not defined in status-labels.js"


def test_the_shared_labels_load_before_the_screens_that_read_them():
    html = (STATIC / "simple.html").read_text(encoding="utf-8")
    shared = html.index('src="/status-labels.js"')
    for name in SCREENS:
        tag = f'src="/{name}"'
        if tag in html:
            assert shared < html.index(tag), f"status-labels.js must load before {name}"


def without_comments(source: str) -> str:
    """Drop comments, so wording explained in a comment is not read as a second copy."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def test_no_screen_keeps_its_own_copy_of_the_result_wording():
    """A second copy is how Gray declarations came to say "Found in code"."""
    for name in SCREENS:
        source = without_comments((STATIC / name).read_text(encoding="utf-8"))
        for phrase in ("Not tested", "Declaration only"):
            literal = source.count(f'"{phrase}"') + source.count(f"'{phrase}'")
            assert literal == 0, (
                f"{name} hard-codes {phrase!r}; read it from window.StudioStatus instead"
            )


def test_no_screen_renders_a_raw_machine_status():
    """`not_tested` must never reach the page with only its underscores replaced."""
    for name in SCREENS:
        source = (STATIC / name).read_text(encoding="utf-8")
        assert 'status.replaceAll("_", " ")' not in source, (
            f"{name} prints a raw machine status; use window.StudioStatus.label()"
        )


def test_found_in_code_is_gone_from_every_screen():
    for path in STATIC.glob("*.js"):
        if path.name in ("app.js", "dashboard.js", "comparison.js", "costs.js", "controls.js"):
            continue  # Retained legacy interface; unchanged on purpose.
        assert "Found in code" not in path.read_text(encoding="utf-8"), (
            f"{path.name} still claims a declaration was found in code"
        )


def test_an_unknown_state_is_humanised_rather_than_invented():
    source = labels_source()
    assert 'replaceAll("_", " ")' in source, "an unmapped state should read as words"
    assert "RESULT[key] || QUALIFIER[key] || friendly(key)" in source


def test_unknown_cost_is_never_rendered_as_zero():
    source = labels_source()
    assert "if (microUsd == null) return QUALIFIER.unknown;" in source
    assert '"$0 (no calls)"' in source, "only a known no-call case may read as zero"
    position = source.index("cost(microUsd")
    assert source.index("noCalls") < source.index("microUsd == null", position), (
        "the known-zero case must be decided before the unknown case"
    )


def test_each_qualification_can_explain_itself():
    source = labels_source()
    for key in ("not_tested", "exists", "estimated", "low_confidence", "needs_review", "unknown"):
        assert re.search(rf"\b{key}:", source), f"{key} has no wording"
    assert "This is not a failed answer" in source
    assert "does not show that it works" in source
    assert "Unknown never means zero" in source


# --- measured contrast -------------------------------------------------------------------------


def test_the_stylesheet_meets_wcag_aa_for_text():
    """Measured, not asserted: scripts/check_contrast.py computes every ratio it can resolve."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_contrast.py"), "--failures"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, f"contrast failures:\n{result.stdout}\n{result.stderr}"
    assert "0 failing" in result.stdout
    assert "0 skipped" in result.stdout, (
        "a colour the checker cannot resolve is unmeasured, not passing"
    )


def test_the_contrast_checker_states_the_standard_it_measures_against():
    source = (ROOT / "scripts/check_contrast.py").read_text(encoding="utf-8")
    assert "WCAG 2.2 AA" in source
    assert "NORMAL_TEXT = 4.5" in source
    assert "LARGE_TEXT = 3.0" in source
    assert "it does not decide whether a colour is tasteful" in source


def test_the_contrast_checker_detects_a_failing_colour():
    """A checker that cannot fail is not a check."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cc", ROOT / "scripts/check_contrast.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert module.ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    # A mid grey on white is a real-world near miss and must not be reported as passing.
    assert module.ratio("#8791a5", "#ffffff") < module.NORMAL_TEXT
