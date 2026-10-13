import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluator  # noqa: E402
import governance  # noqa: E402


@pytest.fixture(autouse=True)
def audit_log(monkeypatch, tmp_path):
    """Tests never write to the real audit log."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(governance, "AUDIT_FILE", str(path))
    monkeypatch.setattr(governance, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("AUDIT_KEY", raising=False)
    return path


@pytest.fixture(autouse=True)
def no_timing_pass(monkeypatch):
    """Runs in tests skip the timing pass (it would add calls the tests count); test_timing_pass turns it back on."""
    monkeypatch.setattr(evaluator, "TIMING_N", 0)
