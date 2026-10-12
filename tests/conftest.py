import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import governance  # noqa: E402


@pytest.fixture(autouse=True)
def audit_log(monkeypatch, tmp_path):
    """Tests never write to the real audit log."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(governance, "AUDIT_FILE", str(path))
    return path
