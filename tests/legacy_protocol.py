"""Freeze the prior 800-case protocol for backward-compatibility tests."""

import json
from pathlib import Path

from app.config import ROOT


def snapshot(suite: str = ""):
    """The frozen prior protocol. `suite` matches `studio_engine.settings_file`'s signature.

    A frozen snapshot has one fixed scenario set by definition, so a suite name is accepted and
    ignored: these tests assert that an old protocol still plans exactly as it used to.
    """
    del suite
    protocol = json.loads((Path(__file__).parent / "fixtures/protocol-v3.json").read_text())
    protocol["scenario_sets"] = json.loads((ROOT / "app/studio/scenarios.json").read_text())
    return protocol
