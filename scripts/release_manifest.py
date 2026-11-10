"""Describe a built release artifact so a reviewer can check it before publication.

Standard library only. Reads the artifact and the repository state; writes a
Markdown manifest next to the artifact. It records what is true of **this
build**: the artifact's own hash, the commit it was built from, whether the
working tree was dirty, and the platform and evidence claims supplied by the
caller.

A dirty working tree is allowed, and is reported. The artifact is then
identified by its own hash and content digest, never attributed to the commit
alone, because the commit does not describe uncommitted changes.

Usage:

    python scripts/release_manifest.py --artifact runtime/release/<name>.zip \\
        --version 0.1.0-rc.1 --evidence docs/verification.md
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    """Return trimmed Git output, or an explicit marker when unavailable."""
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return done.stdout.decode("utf-8", "replace").strip()


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def content_digest(path: Path) -> tuple[str, int]:
    """Hash the archive's member names and contents, ignoring timestamps.

    Two archives built from identical sources compare equal here even when
    their ZIP metadata differs, so this identifies the content rather than
    the build moment.
    """
    sha = hashlib.sha256()
    count = 0
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            sha.update(name.encode("utf-8"))
            sha.update(archive.read(name))
            count += 1
    return sha.hexdigest(), count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--evidence",
        default="docs/verification.md",
        help="Document holding the recorded test evidence for this candidate.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact = args.artifact.resolve()
    if not artifact.is_file():
        print(f"No such artifact: {artifact}", file=sys.stderr)
        return 1
    try:
        archive_digest, members = content_digest(artifact)
    except (OSError, zipfile.BadZipFile):
        print("The artifact is not a readable ZIP archive.", file=sys.stderr)
        return 1

    status = git("status", "--short")
    dirty = bool(status) and status != "unavailable"
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    described = (
        "the artifact's own SHA-256 below" if dirty else f"commit `{commit}` (clean working tree)"
    )

    lines = [
        f"# Release manifest — {args.version}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')} by "
        "`scripts/release_manifest.py`. This describes one build. It is not an approval, "
        "a signature, or a statement that publication was authorized.",
        "",
        "## Artifact",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| File | `{artifact.name}` |",
        f"| Size | {artifact.stat().st_size} bytes |",
        f"| SHA-256 | `{digest(artifact)}` |",
        f"| Content digest (names + contents) | `{archive_digest}` |",
        f"| Members | {members} |",
        "",
        "## Candidate identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Branch | `{branch}` |",
        f"| Commit | `{commit}` |",
        f"| Tree | `{tree}` |",
        f"| Working tree | {'**dirty** — uncommitted changes present' if dirty else 'clean'} |",
        f"| This artifact is identified by | {described} |",
        "",
    ]
    if dirty:
        lines += [
            "> The working tree was **dirty** when this artifact was built, so the commit "
            "above does **not** describe its contents. Identify this artifact by its "
            "SHA-256 and content digest. Do not attribute it to the commit alone, and do "
            "not assume a rebuild from that commit reproduces it.",
            "",
            "Uncommitted paths at build time:",
            "",
            "```text",
            status,
            "```",
            "",
        ]
    lines += [
        "## Evidence",
        "",
        f"Recorded test and verification evidence: `{args.evidence}`.",
        "",
        "A manifest cannot establish that those checks passed. Read the evidence document "
        "and the release gate ledger (`docs/open-source-readiness.md`) before authorizing "
        "publication.",
        "",
        "## Verify this artifact",
        "",
        "```powershell",
        f"Get-FileHash {artifact.name} -Algorithm SHA256",
        "```",
        "",
        "```sh",
        f"sha256sum {artifact.name}",
        "```",
        "",
    ]

    output = args.output or artifact.with_suffix(".manifest.md")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Manifest written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
