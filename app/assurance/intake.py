"""Bounded source intake. No imports, subprocesses or execution of uploaded code."""

import hashlib
import io
import json
import os
import stat
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .. import database as db
from ..config import RUNTIME
from .privacy import policy_rules, safe, trace_rows

LIMITS = {
    "max_bytes": 20 * 1024 * 1024,
    "expanded_bytes": 50 * 1024 * 1024,
    "max_entries": 2000,
    "file_bytes": 2 * 1024 * 1024,
    "seconds": 10,
}
UNLOCKS = {"system_prompt": 2, "config": 1, "tools": 1, "knowledge": 3, "logs": 6, "code": 14}


def root() -> Path:
    path = RUNTIME / "assurance-inputs"
    path.mkdir(exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def unpack(raw: bytes, destination: Path) -> None:
    """No extractall: validate every member and enforce actual streamed byte limits."""
    if len(raw) > LIMITS["max_bytes"]:
        raise ValueError("ZIP exceeds 20 MB source-only limit.")
    started, total, seen = time.monotonic(), 0, set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > LIMITS["max_entries"]:
            raise ValueError("ZIP has too many entries.")
        for item in archive.infolist():
            name = item.filename.replace("\\", "/")
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (
                path.is_absolute()
                or any(x in ("..", ".") for x in path.parts)
                or ":" in name
                or "\x00" in name
                or not path.parts
                or item.flag_bits & 1
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
            ):
                raise ValueError("Unsafe, encrypted or linked ZIP member.")
            normalized = str(path).casefold()
            if normalized in seen:
                raise ValueError("Duplicate ZIP path.")
            seen.add(normalized)
            target = (destination / str(path)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("ZIP path escapes source directory.")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if (
                item.file_size > LIMITS["file_bytes"]
                or item.file_size / max(item.compress_size, 1) > 200
            ):
                raise ValueError("ZIP expansion or member size limit exceeded.")
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(item) as source, target.open("xb") as output:
                while chunk := source.read(65536):
                    written += len(chunk)
                    total += len(chunk)
                    if (
                        written > LIMITS["file_bytes"]
                        or total > LIMITS["expanded_bytes"]
                        or time.monotonic() - started > LIMITS["seconds"]
                    ):
                        raise ValueError("Source size or extraction time limit exceeded.")
                    output.write(chunk)


def store(kind: str, raw: bytes, name: str) -> dict:
    if kind not in UNLOCKS or not raw or len(raw) > LIMITS["max_bytes"]:
        raise ValueError("Unknown input type, empty input, or upload larger than 20 MB.")
    if kind != "code" and len(raw) > (2 * 1024 * 1024 if kind == "logs" else 128 * 1024):
        raise ValueError("Private text/config limit is 128 KB; structured logs limit is 2 MB.")
    ident = str(uuid.uuid4())
    metadata = {}
    if kind == "code":
        # Validate before storing; source remains private and is never sent to a judge.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="validate-source-") as folder:
            unpack(raw, Path(folder))
        path = root() / (ident + ".zip")
        path.write_bytes(raw)
    else:
        if kind == "logs":
            data, metadata = trace_rows(raw)
        elif kind in ("config", "tools"):
            text = raw.decode("utf-8-sig")
            if name.lower().endswith((".yml", ".yaml")):
                import yaml

                if any(
                    isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
                    for t in yaml.scan(text)
                ):
                    raise ValueError(
                        "YAML anchors and aliases are unsupported; supply plain configuration."
                    )
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)
            data = safe(data)
        else:
            data = safe(raw.decode("utf-8-sig"))
        if (kind in ("config", "tools") and not data) or (
            isinstance(data, str) and not data.strip()
        ):
            raise ValueError("Supply a non-empty private input.")
        if kind == "system_prompt":
            policy_rules(str(data))
        path = root() / (ident + ".json")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    record = {
        "id": ident,
        "kind": kind,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "name": str(safe(Path(name).name))[:200],
        "unlocks": (len(policy_rules(str(data))) + 1 if kind == "system_prompt" else UNLOCKS[kind]),
        "created_at": time.time(),
        "metadata": metadata,
    }
    db.save("assurance_input", record)
    return record


def load(ident: str, kind: str) -> tuple[object, dict]:
    # Never accept a caller-provided filesystem path.
    ident = str(uuid.UUID(ident))
    record = db.get("assurance_input", ident)
    if not record or record["kind"] != kind:
        raise ValueError("Input was removed or has the wrong type; upload it again.")
    path = root() / (ident + (".zip" if kind == "code" else ".json"))
    if kind == "code":
        return path, record
    return json.loads(path.read_text(encoding="utf-8")), record


def remove(ident: str) -> None:
    ident = str(uuid.UUID(ident))
    for suffix in (".json", ".zip"):
        (root() / (ident + suffix)).unlink(missing_ok=True)
    db.delete("assurance_input", ident)
