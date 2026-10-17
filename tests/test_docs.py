"""Offline regressions for the documentation checker; no product data is touched."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "studio_check_docs", Path(__file__).resolve().parents[1] / "scripts" / "check_docs.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def make_doc_root(tmp_path):
    """Minimal complete document set with links, anchors and requirement coverage."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in checker.DOCUMENTS:
        (docs / name).write_text("# Title\n\n## Scope\n", encoding="utf-8")
    (docs / "PRD.md").write_text(
        "# PRD\n\nFR-01 NFR-01\n[Tasks](tasks.md#scope)\n", encoding="utf-8"
    )
    (docs / "tasks.md").write_text("# Tasks\n\n## Scope\nFR-01 NFR-01\n", encoding="utf-8")
    return tmp_path


def test_valid_docs_and_external_links(tmp_path):
    """Remote links and code examples do not cause network work or false failures."""
    doc_root = make_doc_root(tmp_path)
    (doc_root / "AGENTS.md").write_text(
        "[Rules](docs/Rules.md) [remote](https://example.invalid)\n"
        "```md\n[example](nonexistent.md)\n```\n",
        encoding="utf-8",
    )
    assert checker.check_docs(doc_root) == []


def test_missing_document_is_reported(tmp_path):
    doc_root = make_doc_root(tmp_path)
    (doc_root / "docs" / "Design.md").unlink()
    assert any("Missing document" in e for e in checker.check_docs(doc_root))


def test_missing_and_unknown_requirements(tmp_path):
    doc_root = make_doc_root(tmp_path)
    (doc_root / "docs" / "tasks.md").write_text("# Tasks\n\n## Scope\nFR-02\n", encoding="utf-8")
    errors = checker.check_docs(doc_root)
    assert "Requirement not referenced in tasks.md: FR-01" in errors
    assert "Requirement not referenced in tasks.md: NFR-01" in errors
    assert "Unknown requirement in tasks.md: FR-02" in errors


def test_broken_paths_and_anchors(tmp_path):
    doc_root = make_doc_root(tmp_path)
    (doc_root / "docs" / "Design.md").write_text(
        "# Design\n[bad](gone.md) [anchor](Rules.md#absent)\n", encoding="utf-8"
    )
    errors = checker.check_docs(doc_root)
    assert any("broken relative link gone.md" in e for e in errors)
    assert any("missing heading anchor Rules.md#absent" in e for e in errors)


def test_reference_links_and_encoded_paths(tmp_path):
    doc_root = make_doc_root(tmp_path)
    (doc_root / "docs" / "with space.md").write_text("# Detail\n", encoding="utf-8")
    design = doc_root / "docs" / "Design.md"
    design.write_text(
        "# Design\n[detail][source]\n[source]: with%20space.md#detail\n",
        encoding="utf-8",
    )
    assert checker.check_docs(doc_root) == []
    design.write_text("# Design\n[detail][missing]\n", encoding="utf-8")
    assert any("undefined Markdown reference missing" in e for e in checker.check_docs(doc_root))


def test_duplicate_and_punctuated_heading_ids():
    assert checker.heading_ids("# Phase 0 — Black-box fixes\n## Scope\n## Scope\n") == {
        "phase-0--black-box-fixes",
        "scope",
        "scope-1",
    }


if __name__ == "__main__":
    # Keep the standalone checker tests usable before project dependencies install.
    suite = unittest.TestSuite()
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):

            def isolated(operation=test):
                with tempfile.TemporaryDirectory(prefix="studio-docs-test-") as folder:
                    if operation.__code__.co_argcount:
                        operation(Path(folder))
                    else:
                        operation()

            suite.addTest(unittest.FunctionTestCase(isolated, description=name))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
