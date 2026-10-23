"""Dependency locks (T-033): every lock is complete, hash-verified and agrees with its manifest.

These checks run on any platform without `uv`, so CI validates the committed locks even though
regenerating them is a maintenance step. They verify the lock *files*, not that an install
succeeded: a clean hash-verified installation is recorded separately in PROGRESS.md.
"""

from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent

PAIRS = {
    "requirements.txt": "requirements.lock",
    "requirements-dev.txt": "requirements-dev.lock",
    "requirements-evaluation.txt": "requirements-evaluation.lock",
}
OPTIONAL = {"requirements-evaluation.lock"}


def manifest_requirements(name: str) -> list[Requirement]:
    """Direct requirements of one manifest, following a single `-r` include level."""
    rows: list[Requirement] = []
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            rows.extend(manifest_requirements(line.split(maxsplit=1)[1].strip()))
            continue
        if line.startswith("-"):
            continue
        rows.append(Requirement(line))
    return rows


def lock_entries(name: str) -> dict[str, dict]:
    """Parse `name==version` entries with their `--hash` values and environment marker."""
    entries: dict[str, dict] = {}
    current = None
    for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.strip().removesuffix("\\").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            assert current, f"{name}: a hash appears before any requirement"
            entries[current]["hashes"].append(line.removeprefix("--hash="))
            continue
        assert "==" in line, f"{name}: requirement is not pinned with ==: {raw!r}"
        spec, _, marker = line.partition(";")
        package, _, version = spec.strip().partition("==")
        current = canonicalize_name(package)
        assert current not in entries, f"{name}: {package} is listed twice"
        entries[current] = {
            "version": version.strip(),
            "marker": marker.strip(),
            "hashes": [],
        }
    return entries


@pytest.mark.parametrize("lock", sorted(PAIRS.values()))
def test_lock_exists_and_declares_how_to_install_it(lock):
    text = (ROOT / lock).read_text(encoding="utf-8")
    assert "scripts/lock_dependencies.py" in text, "the lock must name its generator"
    assert "--require-hashes" in text, "the lock must state the verifying install command"
    assert "Windows, Linux and macOS" in text, "the lock must state its platform scope"


@pytest.mark.parametrize("lock", sorted(PAIRS.values()))
def test_every_locked_package_is_pinned_and_hashed(lock):
    entries = lock_entries(lock)
    assert entries, f"{lock} has no requirements"
    for package, row in entries.items():
        Version(row["version"])  # raises on a range, a wildcard or a local version scheme
        assert row["hashes"], f"{lock}: {package} has no hash, so pip cannot verify it"
        for value in row["hashes"]:
            algorithm, _, digest = value.partition(":")
            assert algorithm == "sha256", f"{lock}: {package} uses {algorithm}, not sha256"
            assert len(digest) == 64, f"{lock}: {package} has a malformed sha256 digest"


@pytest.mark.parametrize("lock", sorted(PAIRS.values()))
def test_locks_carry_no_local_paths_or_direct_urls(lock):
    """A committed lock must not leak a developer's filesystem or bypass the index."""
    text = (ROOT / lock).read_text(encoding="utf-8")
    for needle in ("file://", " @ ", "C:\\", "C:/", "/Users/", "/home/", "/tmp/", "--index-url"):
        assert needle not in text, f"{lock} contains {needle!r}"


@pytest.mark.parametrize("manifest,lock", sorted(PAIRS.items()))
def test_lock_satisfies_every_declared_requirement(manifest, lock):
    """Catches a manifest edited without regenerating its lock, and an unsatisfiable manifest.

    `filelock>=4.0.9` once sat in requirements-dev.txt while litellm capped it below 4.0, which
    made a clean development install impossible; this is the check that fails on that state.
    """
    entries = lock_entries(lock)
    for requirement in manifest_requirements(manifest):
        name = canonicalize_name(requirement.name)
        assert name in entries, f"{manifest} requires {requirement.name}, absent from {lock}"
        version = entries[name]["version"]
        assert requirement.specifier.contains(version, prereleases=True), (
            f"{manifest} requires {requirement.name}{requirement.specifier} but {lock} pins "
            f"{version}. Regenerate the lock, or the manifest is unsatisfiable."
        )


def test_one_version_satisfies_every_manifest_that_declares_a_package():
    """A package required by two manifests must have a single version both accept.

    The locked version is the witness, so this fails either when two manifests contradict each
    other or when one of them was edited without regenerating its lock.
    """
    wanted: dict[str, list[tuple[str, Requirement]]] = {}
    for manifest in PAIRS:
        for requirement in manifest_requirements(manifest):
            wanted.setdefault(canonicalize_name(requirement.name), []).append(
                (manifest, requirement)
            )
    resolved = {
        name: row["version"] for lock in PAIRS.values() for name, row in lock_entries(lock).items()
    }
    for name, rows in wanted.items():
        if len(rows) < 2:
            continue
        version = resolved.get(name)
        assert version, f"{name} is declared by a manifest but absent from every lock"
        unmet = [
            f"{manifest} wants {requirement.name}{requirement.specifier}"
            for manifest, requirement in rows
            if not requirement.specifier.contains(version, prereleases=True)
        ]
        assert not unmet, (
            f"No single version of {name} satisfies every manifest; the locks resolved "
            f"{version} and " + "; ".join(unmet)
        )


def test_runtime_and_development_locks_agree_on_shared_packages():
    """The development lock must extend the runtime lock, never silently reversion it."""
    runtime = lock_entries("requirements.lock")
    development = lock_entries("requirements-dev.lock")
    for package, row in runtime.items():
        assert package in development, f"{package} is missing from the development lock"
        assert development[package]["version"] == row["version"], (
            f"{package}: runtime pins {row['version']}, development pins "
            f"{development[package]['version']}"
        )


def test_optional_evaluation_lock_states_that_it_is_unverified():
    text = (ROOT / "requirements-evaluation.lock").read_text(encoding="utf-8")
    assert "Unverified" in text
    assert "not installed or exercised" in text


def test_platform_specific_packages_keep_their_markers():
    """A universal lock must carry markers, or a Windows-only wheel is demanded everywhere."""
    entries = lock_entries("requirements.lock")
    assert "colorama" in entries, "colorama is expected in this resolution"
    assert "sys_platform" in entries["colorama"]["marker"], (
        "colorama is Windows-only here and must stay behind an environment marker"
    )


def test_launchers_and_ci_install_from_the_locks():
    """Wiring the locks in is part of the lock, so a regression here must fail a test."""
    checks = {
        "start.sh": "--require-hashes -r requirements.lock",
        "run.ps1": "--require-hashes -r requirements.lock",
        "Dockerfile": "--require-hashes -r requirements.lock",
        ".github/workflows/quality.yml": "--require-hashes -r requirements-dev.lock",
    }
    for path, needle in checks.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        assert needle in text, f"{path} does not install from its lock ({needle})"
        assert "pip install -r requirements" not in text, f"{path} still installs unpinned ranges"
