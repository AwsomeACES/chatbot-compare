"""Freeze the prior 800-case protocol for backward-compatibility tests."""

import json
from pathlib import Path

from app.config import ROOT


def snapshot():
    protocol = json.loads((Path(__file__).parent / "fixtures/protocol-v3.json").read_text())
    protocol["scenario_sets"] = json.loads((ROOT / "app/studio/scenarios.json").read_text())
    return protocol
