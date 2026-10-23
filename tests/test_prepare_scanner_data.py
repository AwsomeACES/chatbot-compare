"""Offline scanner provisioning: scoped OSV snapshots never cover unrelated packages."""

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.assurance import readiness, sandbox

SCRIPT = Path(__file__).parents[1] / "scripts/prepare_scanner_data.py"
spec = importlib.util.spec_from_file_location("prepare_scanner_data", SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def write_zip(path: Path, files: dict[str, str]) -> Path:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    path.write_bytes(data.getvalue())
    return path


def advisory(ident: str, name: str) -> str:
    return json.dumps({"id": ident, "affected": [{"package": {"ecosystem": "PyPI", "name": name}}]})


def test_scope_filters_advisories_and_scan_time_coverage_matches(tmp_path, monkeypatch):
    full = write_zip(
        tmp_path / "PyPI-all.zip",
        {
            "A-1.json": advisory("A-1", "FastAPI"),
            "A-2.json": advisory("A-2", "httpx"),
            "A-3.json": advisory("A-3", "unrelated-package"),
        },
    )
    source = write_zip(
        tmp_path / "bot.zip", {"bot-main/requirements.txt": "fastapi==0.115.0\nhttpx\n"}
    )
    out = tmp_path / "osv-bot"
    manifest = prepare.scope(source, {"PyPI": full}, out)
    assert manifest["databases"][0]["advisories_retained"] == 2
    assert manifest["packages"] == [["PyPI", "fastapi"], ["PyPI", "httpx"]]
    assert prepare.snapshot_problems(out) == []

    monkeypatch.setenv("STUDIO_SCANNER_OSV_DATABASE", str(out))
    assert readiness.osv_coverage(["fastapi", "httpx"]) == ""
    assert "requests" in readiness.osv_coverage(["fastapi", "requests"])

    def report(*names):
        return {
            "results": [
                {"packages": [{"package": {"ecosystem": "PyPI", "name": n}} for n in names]}
            ]
        }

    assert sandbox.osv_scope(report("fastapi", "httpx"))["packages_inspected"] == 2
    with pytest.raises(sandbox.ToolUnavailable):
        sandbox.osv_scope(report("fastapi", "requests"))

    (out / "osv-scanner/PyPI/all.zip").write_bytes(b"tampered")
    assert "changed after provisioning" in prepare.snapshot_problems(out)[0]
    with pytest.raises(SystemExit):
        prepare.scope(source, {"PyPI": full}, out)


def test_scope_refuses_missing_inputs(tmp_path):
    empty = write_zip(tmp_path / "empty.zip", {"README.md": "no dependencies"})
    with pytest.raises(SystemExit, match="No dependency names"):
        prepare.scope(empty, {}, tmp_path / "a")
    npm = write_zip(
        tmp_path / "npm.zip",
        {
            "package-lock.json": json.dumps(
                {"packages": {"node_modules/left-pad": {"version": "1"}}}
            )
        },
    )
    with pytest.raises(SystemExit, match="Supply --full-db for: npm"):
        prepare.scope(npm, {}, tmp_path / "b")


def test_check_reports_unavailable_tools_without_docker(tmp_path, monkeypatch):
    monkeypatch.delenv("STUDIO_SCANNER_WSL_DISTRO", raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    source = write_zip(tmp_path / "bot.zip", {"requirements.txt": "fastapi\n"})
    report = prepare.check(source)
    assert report["ready"] is False
    assert all("Docker" in reason for reason in report["tools"].values())
    assert report["source"]["unresolved_versions"] == ["fastapi"]
