"""Scanner-only Docker sandbox. Uploaded programs are never started or imported."""

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path, PureWindowsPath

from ..config import ROOT, RUNTIME


class ToolUnavailable(Exception):
    """Missing daemon/image/database, bounded output or timeout: Not tested."""


def specification() -> dict:
    return json.loads((ROOT / "app/studio/scanners.json").read_text())


def docker_prefix() -> list[str]:
    """Use a configured WSL daemon without exposing a TCP Docker socket."""
    distro = os.getenv("STUDIO_SCANNER_WSL_DISTRO", "")
    if distro:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", distro):
            raise ToolUnavailable("Invalid scanner WSL distribution name.")
        if os.name != "nt" or not shutil.which("wsl"):
            raise ToolUnavailable("Configured WSL scanner runtime is unavailable.")
        return ["wsl", "--distribution", distro, "--user", "root", "--exec", "docker"]
    if not shutil.which("docker"):
        raise ToolUnavailable(
            "Docker scanner sandbox is unavailable; source was not executed on the host."
        )
    return ["docker"]


def mount_path(path: Path) -> str:
    """Translate only explicit Windows drive paths for a WSL bind mount."""
    resolved = str(path.resolve())
    if not os.getenv("STUDIO_SCANNER_WSL_DISTRO"):
        return resolved
    windows = PureWindowsPath(resolved)
    if not re.fullmatch(r"[A-Za-z]:", windows.drive):
        raise ToolUnavailable("WSL scanner mounts require a local Windows drive path.")
    return "/mnt/" + windows.drive[0].lower() + "/" + "/".join(windows.parts[1:])


def database_path(tool: str) -> Path:
    override = os.getenv("STUDIO_SCANNER_OSV_DATABASE", "") if tool == "osv" else ""
    return Path(override) if override else RUNTIME / "scanner-databases" / tool


def osv_scope(data: dict) -> dict | None:
    """A scoped public DB is valid only for every package the scanner inspected."""
    if not os.getenv("STUDIO_SCANNER_OSV_DATABASE", ""):
        return None
    root = database_path("osv")
    manifest = root / "scope.json"
    if not manifest.is_file() or manifest.stat().st_size > 1024**2:
        raise ToolUnavailable("Scoped OSV database has no valid coverage manifest.")
    raw = manifest.read_bytes()
    scope = json.loads(raw)
    if scope.get("version") != "osv-package-scope-v1":
        raise ToolUnavailable("Unsupported OSV database scope manifest.")

    def identity(eco: str, name: str) -> tuple[str, str]:
        return eco, re.sub(r"[-_.]+", "-", name).lower() if eco == "PyPI" else name

    expected = {identity(eco, name) for eco, name in scope["packages"]}
    actual = {
        identity(item["package"]["ecosystem"], item["package"]["name"])
        for result in data.get("results", [])
        for item in result.get("packages", [])
    }
    if not actual or not actual <= expected:
        raise ToolUnavailable(
            "OSV database does not cover every inspected package; provision a matching snapshot."
        )
    for entry in scope["databases"]:
        if entry["ecosystem"] not in ("npm", "PyPI"):
            raise ToolUnavailable("Unsupported scoped database ecosystem.")
        path = root / "osv-scanner" / entry["ecosystem"] / "all.zip"
        if (
            path.stat().st_size > 50 * 1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["filtered_sha256"]
        ):
            raise ToolUnavailable("Scoped OSV database changed after provisioning.")
    if {eco for eco, _ in actual} - {e["ecosystem"] for e in scope["databases"]}:
        raise ToolUnavailable("OSV database is missing an inspected ecosystem.")
    return {
        "scope_sha256": hashlib.sha256(raw).hexdigest(),
        "packages_inspected": len(actual),
        "databases": scope["databases"],
        "method": "All advisories retained by package name, not version or severity; final OSV output coverage verified.",
    }


async def bounded_process(args: list[str], timeout: float, limit: int) -> tuple[int, bytes]:
    if args[0] == "docker":
        args = [*docker_prefix(), *args[1:]]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    output = bytearray()
    try:
        async with asyncio.timeout(timeout):
            while chunk := await process.stdout.read(65536):
                output.extend(chunk)
                if len(output) > limit:
                    raise ToolUnavailable("Scanner output exceeded the bounded limit.")
            await process.wait()
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    return process.returncode, bytes(output)


def command(tool: str, source: Path, name: str, image: str, cache: Path | None = None) -> list[str]:
    spec = specification()["tools"][tool]
    args = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--memory={int(spec.get('memory_mb', 512))}m",
        "--cpus=1",
        "--pids-limit=64",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "--env=HOME=/tmp",
        "--env=SEMGREP_SEND_METRICS=off",
        "--env=SEMGREP_ENABLE_VERSION_CHECK=0",
        "--mount",
        f"type=bind,src={mount_path(source)},dst=/source,readonly",
        "--mount",
        f"type=bind,src={mount_path(ROOT / 'app/assurance/rules')},dst=/rules,readonly",
    ]
    if spec.get("database"):
        database = database_path(spec["database"])
        if not database.is_dir() or not any(database.iterdir()):
            raise ToolUnavailable(
                f"Offline {tool} database missing; provision it before a networkless scan."
            )
        args += [
            "--mount",
            f"type=bind,src={mount_path(database)},dst=/offline/{spec['database']},readonly",
        ]
        if tool == "osv":
            args += ["--env=OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/offline/osv"]
    if cache is not None:
        args += ["--mount", f"type=bind,src={mount_path(cache)},dst=/cache"]
    return [*args, image, *spec["args"]]


def trivy_cache(destination: Path) -> None:
    """Trivy opens BoltDB read/write: copy public DB bytes, never submitted files."""
    database = RUNTIME / "scanner-databases/trivy/db"
    files = [database / "trivy.db", database / "metadata.json"]
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ToolUnavailable("Trivy database or metadata is missing.")
    if sum(p.stat().st_size for p in files) > 2 * 1024**3:
        raise ToolUnavailable("Trivy public database exceeds the 2 GiB private cache limit.")
    destination.chmod(0o777)  # Disposable public DB only, not submitted source.
    (destination / "db").mkdir(mode=0o777)
    (destination / "db").chmod(0o777)
    for path in files:
        copied = destination / "db" / path.name
        shutil.copyfile(path, copied)
        copied.chmod(0o666)


#: Phases reported separately, so a slow run can be attributed before anything is optimised.
#: `database_copy` is the Trivy BoltDB copy, which dominates preparation on modest hardware.
PREPARATION_PHASES = ("image_check", "database_copy", "version_check")


@contextlib.contextmanager
def phase(timings: dict, name: str):
    """Record one phase's wall-clock duration, including when it raises."""
    start = time.monotonic()
    try:
        yield
    finally:
        timings[name] = round(time.monotonic() - start, 3)


def phase_summary(timings: dict) -> dict:
    """Preparation versus scan, so provisioning cost is never read as scan cost."""
    preparation = sum(timings.get(name, 0.0) for name in PREPARATION_PHASES)
    return {
        "phases": dict(timings),
        "preparation_seconds": round(preparation, 3),
        "scan_seconds": timings.get("scan", 0.0),
        "parse_seconds": timings.get("parse", 0.0),
        "note": (
            "Wall-clock measurement on this host. Preparation covers image verification, the "
            "offline database copy and the version check; it is not scan time."
        ),
    }


async def scan(tool: str, source: Path) -> dict:
    docker_prefix()
    config = specification()
    spec = config["tools"][tool]
    name = "studio-scan-" + uuid.uuid4().hex
    resources = contextlib.ExitStack()
    timings: dict[str, float] = {}
    try:
        with phase(timings, "image_check"):
            rc, metadata = await bounded_process(
                ["docker", "image", "inspect", spec["image"], "--format={{.Id}}"], 30, 4096
            )
            if rc != 0 or not metadata.strip().startswith(b"sha256:"):
                raise ToolUnavailable(
                    f"Pinned {tool} {spec['version']} image is not installed; automatic pulls are disabled."
                )
            image_id = metadata.decode().strip()
        cache = None
        if tool == "trivy":
            with phase(timings, "database_copy"):
                cache = Path(
                    resources.enter_context(
                        tempfile.TemporaryDirectory(prefix="trivy-db-", dir=RUNTIME / "work")
                    )
                )
                if not cache.resolve().is_relative_to((RUNTIME / "work").resolve()):
                    raise ToolUnavailable("Invalid private scanner cache directory.")
                # A per-scan private copy: a mutable BoltDB is never shared between Runs.
                await asyncio.to_thread(trivy_cache, cache)
        base = command(tool, source, name, image_id, cache)
        if tool != "controls":
            with phase(timings, "version_check"):
                version_args = {
                    "gitleaks": ["version"],
                    "semgrep": ["semgrep", "--version"],
                    "bandit": ["bandit", "--version"],
                    "osv": ["--version"],
                    "trivy": ["--version"],
                }[tool]
                rc, actual_version = await bounded_process(
                    base[: -len(spec["args"])] + version_args, 45, 8192
                )
                if rc != 0 or spec["version"] not in actual_version.decode(errors="replace"):
                    raise ToolUnavailable(
                        f"{tool} runtime does not match pinned version {spec['version']}."
                    )
        with phase(timings, "scan"):
            # Execute the inspected content ID, preventing a mutable tag race.
            rc, output = await bounded_process(
                base,
                spec.get("timeout_seconds", config["timeout_seconds"]),
                spec.get("output_bytes", config["output_bytes"]),
            )
            if rc not in (0, 1):
                raise ToolUnavailable(f"{tool} could not finish (exit {rc}); no pass was inferred.")
        with phase(timings, "parse"):
            result = json.loads(output)
            snapshot = osv_scope(result) if tool == "osv" else None
        return {
            "data": result,
            "tool": tool,
            "version": spec["version"],
            "image_id": image_id,
            "ruleset": config["version"],
            "timings": phase_summary(timings),
            **({"database_snapshot": snapshot} if snapshot else {}),
        }
    except asyncio.CancelledError:
        raise
    except (TimeoutError, OSError, ValueError) as exc:
        raise ToolUnavailable(f"{tool} unavailable: {type(exc).__name__}; no scan result.") from exc
    finally:
        # Killing docker's client alone can leave a container running. Remove by random name.
        try:
            await bounded_process(["docker", "rm", "-f", name], 5, 4096)
        except (OSError, TimeoutError, ToolUnavailable):
            pass
        await asyncio.to_thread(resources.close)
