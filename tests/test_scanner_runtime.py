"""WSL transport keeps the existing networkless container sandbox intact."""

import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.assurance import intake, sandbox
from app.assurance.white import WhiteEngine, parse


def runtime(monkeypatch, distro="Ubuntu", platform="nt"):
    monkeypatch.setattr(
        sandbox, "os", SimpleNamespace(name=platform, getenv=lambda key, default="": distro)
    )
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: name)


def test_wsl_uses_argument_vector_without_network_daemon(monkeypatch):
    runtime(monkeypatch)
    assert sandbox.docker_prefix() == [
        "wsl",
        "--distribution",
        "Ubuntu",
        "--user",
        "root",
        "--exec",
        "docker",
    ]


@pytest.mark.parametrize("distro", ["Ubuntu; echo bad", "../Ubuntu", "Ubuntu with spaces"])
def test_invalid_distro_is_rejected(monkeypatch, distro):
    runtime(monkeypatch, distro)
    with pytest.raises(sandbox.ToolUnavailable):
        sandbox.docker_prefix()


def test_native_docker_stays_default(monkeypatch):
    runtime(monkeypatch, distro="", platform="posix")
    assert sandbox.docker_prefix() == ["docker"]


def test_windows_drive_mount_preserves_spaces(monkeypatch):
    runtime(monkeypatch)
    path = SimpleNamespace(resolve=lambda: r"C:\Users\Test User\source")
    assert sandbox.mount_path(path) == "/mnt/c/Users/Test User/source"


def test_wsl_does_not_accept_network_share_mount(monkeypatch):
    runtime(monkeypatch)
    with pytest.raises(sandbox.ToolUnavailable):
        sandbox.mount_path(SimpleNamespace(resolve=lambda: r"\\server\share\source"))


def test_wsl_transport_keeps_all_sandbox_flags(monkeypatch, tmp_path):
    runtime(monkeypatch)
    monkeypatch.setattr(sandbox, "mount_path", lambda p: "/mnt/c/scanner-source")
    args = sandbox.command("gitleaks", Path(tmp_path), "test", "sha256:test")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--user=65534:65534"):
        assert flag in args
    assert sum("readonly" in arg for arg in args) == 2


def scoped_db(monkeypatch, tmp_path):
    root = tmp_path / "osv"
    root.mkdir()
    path = root / "osv-scanner/PyPI/all.zip"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"public database fixture")
    manifest = {
        "version": "osv-package-scope-v1",
        "packages": [["PyPI", "foo-bar"]],
        "databases": [
            {"ecosystem": "PyPI", "filtered_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ],
    }
    (root / "scope.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("STUDIO_SCANNER_OSV_DATABASE", str(root))
    return root, path


def package(name="foo_bar"):
    return {"results": [{"packages": [{"package": {"ecosystem": "PyPI", "name": name}}]}]}


def test_scoped_db_covers_all_inspected_packages(monkeypatch, tmp_path):
    scoped_db(monkeypatch, tmp_path)
    assert sandbox.osv_scope(package())["packages_inspected"] == 1


def test_scoped_db_rejects_uncovered_package(monkeypatch, tmp_path):
    scoped_db(monkeypatch, tmp_path)
    with pytest.raises(sandbox.ToolUnavailable, match="every inspected package"):
        sandbox.osv_scope(package("other-package"))


def test_scoped_db_rejects_changed_database(monkeypatch, tmp_path):
    _, path = scoped_db(monkeypatch, tmp_path)
    path.write_bytes(b"tampered")
    with pytest.raises(sandbox.ToolUnavailable, match="changed"):
        sandbox.osv_scope(package())


def test_trivy_uses_disposable_public_db_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "RUNTIME", tmp_path)
    database = tmp_path / "scanner-databases/trivy/db"
    database.mkdir(parents=True)
    for name in ("trivy.db", "metadata.json"):
        (database / name).write_bytes(b"public fixture")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sandbox.trivy_cache(scratch)
    (scratch / "db/trivy.db").write_bytes(b"temporary writes")
    assert (database / "trivy.db").read_bytes() == b"public fixture"


def test_no_control_match_records_scan_completion_without_a_pass(tmp_path):
    finding = parse(
        "guardrail_path",
        {
            "data": {"files": 1, "hits": {}},
            "version": "fixture",
            "image_id": "sha256:fixture",
            "ruleset": "fixture",
        },
        tmp_path,
        0,
    )
    assert finding.verdict == "not_tested" and finding.score is None
    assert finding.details["scanner_completed"] and finding.tool == "controls"


def test_white_progress_persists_first_tool_before_next_starts(monkeypatch):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("bot.py", "print('static fixture')")
    record = intake.store("code", raw.getvalue(), "fixture.zip")
    progress = []

    async def scan(tool, source):
        if tool == "semgrep":
            assert progress == [["hardcoded_secrets"]]
        return {
            "data": [] if tool == "gitleaks" else {"results": []},
            "version": "fixture",
            "image_id": "sha256:fixture",
            "ruleset": "fixture",
        }

    monkeypatch.setattr(sandbox, "scan", scan)
    engine = WhiteEngine(
        on_progress=lambda findings: progress.append([f.test_id for f in findings])
    )
    results = asyncio.run(engine.run(engine.plan({"code": record["id"]})[:2]))
    assert [f.test_id for f in results] == ["hardcoded_secrets", "unsafe_patterns"]
    assert len(progress) == 2


# --- phase timings (T-028 measurement, not optimisation) --------------------------------------


def test_scan_reports_preparation_and_scan_time_separately(monkeypatch, tmp_path):
    """A slow run must be attributable before any concurrency change is considered."""
    import asyncio
    import json as json_module

    monkeypatch.setattr(sandbox, "RUNTIME", tmp_path)
    (tmp_path / "work").mkdir(parents=True)
    database = tmp_path / "scanner-databases/trivy/db"
    database.mkdir(parents=True)
    for name in ("trivy.db", "metadata.json"):
        (database / name).write_bytes(b"public fixture")
    monkeypatch.setattr(sandbox, "docker_prefix", lambda: ["docker"])
    monkeypatch.setattr(
        sandbox,
        "specification",
        lambda: {
            "version": "fixture-rules",
            "timeout_seconds": 60,
            "output_bytes": 1 << 20,
            "tools": {
                "trivy": {
                    "image": "fixture/trivy:1",
                    "version": "1.0.0",
                    "args": ["scan"],
                    "database": "trivy",
                }
            },
        },
    )
    monkeypatch.setattr(sandbox, "command", lambda *a, **k: ["docker", "run", "scan"])

    calls = []

    async def fake_process(args, timeout, limit):
        calls.append(args)
        if "image" in args:
            return 0, b"sha256:" + b"a" * 64
        if "--version" in args:
            return 0, b"Version: 1.0.0"
        return 0, json_module.dumps({"Results": []}).encode()

    monkeypatch.setattr(sandbox, "bounded_process", fake_process)
    result = asyncio.run(sandbox.scan("trivy", tmp_path))

    timings = result["timings"]
    assert set(timings["phases"]) == {
        "image_check",
        "database_copy",
        "version_check",
        "scan",
        "parse",
    }
    assert timings["preparation_seconds"] == pytest.approx(
        timings["phases"]["image_check"]
        + timings["phases"]["database_copy"]
        + timings["phases"]["version_check"],
        abs=0.01,
    )
    assert timings["scan_seconds"] == timings["phases"]["scan"]
    # The database copy is preparation, so it must not be counted as scan time.
    note = timings["note"].lower()
    assert "preparation covers" in note and "not scan time" in note
    assert timings["phases"]["database_copy"] not in (None,)


def test_phase_timings_are_recorded_even_when_a_phase_fails():
    timings = {}
    with pytest.raises(ValueError):
        with sandbox.phase(timings, "database_copy"):
            raise ValueError("copy failed")
    assert "database_copy" in timings, "a failed phase must still report how long it took"


def test_phase_summary_never_counts_preparation_as_scan_time():
    summary = sandbox.phase_summary(
        {"image_check": 0.5, "database_copy": 9.0, "version_check": 0.5, "scan": 2.0, "parse": 0.1}
    )
    assert summary["preparation_seconds"] == 10.0
    assert summary["scan_seconds"] == 2.0
    assert summary["parse_seconds"] == 0.1


def test_a_tool_without_a_database_reports_no_copy_phase(monkeypatch, tmp_path):
    import asyncio
    import json as json_module

    monkeypatch.setattr(sandbox, "RUNTIME", tmp_path)
    monkeypatch.setattr(sandbox, "docker_prefix", lambda: ["docker"])
    monkeypatch.setattr(
        sandbox,
        "specification",
        lambda: {
            "version": "fixture-rules",
            "timeout_seconds": 60,
            "output_bytes": 1 << 20,
            "tools": {
                "gitleaks": {"image": "fixture/gitleaks:1", "version": "1.0.0", "args": ["d"]}
            },
        },
    )
    monkeypatch.setattr(sandbox, "command", lambda *a, **k: ["docker", "run", "d"])

    async def fake_process(args, timeout, limit):
        if "image" in args:
            return 0, b"sha256:" + b"b" * 64
        if "version" in args:
            return 0, b"1.0.0"
        return 0, json_module.dumps([]).encode()

    monkeypatch.setattr(sandbox, "bounded_process", fake_process)
    result = asyncio.run(sandbox.scan("gitleaks", tmp_path))
    assert "database_copy" not in result["timings"]["phases"]
    assert "scan" in result["timings"]["phases"]


def test_findings_carry_the_timings_without_becoming_a_score(tmp_path):
    finding = parse(
        "guardrail_path",
        {
            "data": {"files": 1, "hits": {}},
            "version": "fixture",
            "image_id": "sha256:fixture",
            "ruleset": "fixture",
            "timings": {"preparation_seconds": 9.0, "scan_seconds": 2.0, "phases": {}},
        },
        tmp_path,
        0,
    )
    assert finding.details["timings"]["preparation_seconds"] == 9.0
    assert finding.verdict == "not_tested"
    assert finding.score is None, "a timing must never become a measured score"
