"""Check White-box scanner readiness and build package-scoped offline OSV snapshots.

Run this OUTSIDE an evaluation. It never downloads anything, pulls images, or runs
uploaded code: ``check`` inspects local images/databases, and ``scope`` filters an
official OSV ``all.zip`` that a maintainer has already downloaded.

Examples:
    python scripts/prepare_scanner_data.py check --zip path/to/source.zip
    python scripts/prepare_scanner_data.py scope --zip source.zip \
        --full-db PyPI=downloads/PyPI-all.zip --out runtime/scanner-databases/osv-mybot
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assurance import readiness, sandbox  # noqa: E402
from app.assurance.white import CHECKS  # noqa: E402

ECOSYSTEMS = ("PyPI", "npm")
MAX_FULL_DB = 4 * 1024**3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(ecosystem: str, name: str) -> tuple[str, str]:
    """Same normalization as the scan-time coverage check in ``sandbox.osv_scope``."""
    return ecosystem, re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "PyPI" else name


def snapshot_problems(root: Path) -> list[str]:
    """Verify a scoped snapshot's manifest and hashes; an empty list means valid."""
    manifest = root / "scope.json"
    if not manifest.is_file():
        return ["No scope.json; this is a full database or not provisioned."]
    try:
        scope = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return ["scope.json is not valid JSON."]
    if scope.get("version") != "osv-package-scope-v1":
        return ["Unsupported scope.json version."]
    problems = []
    for entry in scope.get("databases", []):
        path = root / "osv-scanner" / entry.get("ecosystem", "?") / "all.zip"
        if not path.is_file():
            problems.append(f"Missing {path}.")
        elif sha256(path) != entry.get("filtered_sha256"):
            problems.append(f"{entry['ecosystem']} database changed after provisioning.")
    return problems


def check(archive: Path | None) -> dict:
    """Readiness of every White scanner, plus OSV coverage for one source ZIP."""
    tools = list(dict.fromkeys(tool for _, tool in CHECKS.values()))
    status = asyncio.run(readiness.tool_status(tools))
    osv_root = sandbox.database_path("osv")
    report = {
        "tools": {tool: reason or "ready" for tool, reason in status.items()},
        "osv_database": str(osv_root),
        "osv_snapshot_problems": snapshot_problems(osv_root)
        if (osv_root / "scope.json").exists()
        else [],
    }
    if archive:
        files = readiness.inventory(archive)
        names = files["exact_packages"] + files["unresolved_packages"]
        report["source"] = {
            "sha256": sha256(archive),
            "lockfiles": files["lockfiles"],
            "packages": len(set(names)),
            "unresolved_versions": files["unresolved_packages"],
            "osv_coverage": readiness.osv_coverage(names) or "covered or unscoped database",
        }
    report["ready"] = all(v == "ready" for v in report["tools"].values()) and not (
        report["osv_snapshot_problems"]
        or (archive and report["source"]["osv_coverage"] != "covered or unscoped database")
    )
    return report


def scope(archive: Path, full: dict[str, Path], out: Path) -> dict:
    """Write a package-scoped OSV snapshot covering every package listed in ``archive``."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new folder (existing data is kept).")
    files = readiness.inventory(archive)
    wanted = {identity(eco, name) for eco, name in files["packages"]}
    if not wanted:
        raise SystemExit("No dependency names found in the ZIP; nothing to scope.")
    missing = {eco for eco, _ in wanted} - set(full)
    if missing:
        raise SystemExit(f"Supply --full-db for: {', '.join(sorted(missing))}.")
    databases = []
    for ecosystem, source in sorted(full.items()):
        if ecosystem not in ECOSYSTEMS:
            raise SystemExit(f"Unsupported ecosystem {ecosystem}.")
        if source.stat().st_size > MAX_FULL_DB:
            raise SystemExit(f"{source} is larger than the 4 GiB limit.")
        target = out / "osv-scanner" / ecosystem / "all.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        retained = 0
        buffer = io.BytesIO()
        with zipfile.ZipFile(source) as bundle, zipfile.ZipFile(buffer, "w") as filtered:
            for item in bundle.infolist():
                if item.is_dir() or not item.filename.endswith(".json"):
                    continue
                advisory = json.loads(bundle.read(item))
                names = {
                    identity(a["package"].get("ecosystem", ""), a["package"].get("name", ""))
                    for a in advisory.get("affected", [])
                    if isinstance(a.get("package"), dict)
                }
                if names & wanted:
                    filtered.writestr(item.filename, json.dumps(advisory))
                    retained += 1
        target.write_bytes(buffer.getvalue())
        databases.append(
            {
                "ecosystem": ecosystem,
                "full_sha256": sha256(source),
                "filtered_sha256": sha256(target),
                "advisories_retained": retained,
            }
        )
    manifest = {
        "version": "osv-package-scope-v1",
        "archive_sha256": sha256(archive),
        "packages": sorted([list(item) for item in wanted]),
        "databases": databases,
        "note": "Covers only these packages. Other bots need their own snapshot.",
    }
    (out / "scope.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="Inspect local scanner readiness.")
    checking.add_argument("--zip", type=Path)
    scoping = commands.add_parser("scope", help="Build a package-scoped OSV snapshot.")
    scoping.add_argument("--zip", type=Path, required=True)
    scoping.add_argument("--full-db", action="append", default=[], metavar="ECOSYSTEM=PATH")
    scoping.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "check":
        report = check(args.zip)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1
    full = {}
    for value in args.full_db:
        ecosystem, _, path = value.partition("=")
        full[ecosystem] = Path(path)
    print(json.dumps(scope(args.zip, full, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
