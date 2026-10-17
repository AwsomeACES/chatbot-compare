"""Export a source-only Studio ZIP without local configuration or runtime data.

Standard library only. The archive is verified before publication; existing
outputs are never overwritten. This is a packaging safeguard, not key revocation.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SOURCE_DIRS = {"app", "scripts", "tests", "sample_project", "docs", ".github"}
ROOT_FILES = {
    "README.md",
    "DECISIONS.md",
    "SECURITY.md",
    "run.ps1",
    "pytest.ini",
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "CONTRIBUTING.md",
    "BACKLOG.md",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    ".prettierrc.json",
    ".prettierignore",
    ".editorconfig",
}
PRIVATE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "runtime",
    "runs",
    "archives",
    "logs",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "cache",
    "caches",
    "build",
    "dist",
    "out",
    "target",
    "coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".aws",
    ".ssh",
    ".azure",
    ".gcloud",
    "secrets",
    "secret",
    "credentials",
    "credential",
    "private",
    "certificates",
}
PRIVATE_SUFFIXES = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".log",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".keystore",
    ".jks",
    ".crt",
    ".cer",
    ".bak",
    ".tmp",
}
PRIVATE_PATTERNS = (
    "secrets.*",
    "secret.*",
    "credentials.*",
    "credential.*",
    "service-account*",
    "service_account*",
    "client_secret*",
    "id_rsa*",
    "id_ed25519*",
    "*.sqlite-*",
    "*.sqlite3-*",
    "*.db-*",
    ".coverage*",
    "coverage.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "*.min.js.map",
)
MAX_FILES = 10_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
CREDENTIAL_NAME = re.compile(
    r"(?:^|_)(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?)(?:_|$)", re.I
)


class PackagingError(ValueError):
    """A safe error that never includes file contents or credential values."""


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _credential_name(name: str) -> bool:
    return name.upper() != "STUDIO_JUDGE_KEY_NAME" and bool(CREDENTIAL_NAME.search(name))


def _assignments(data: bytes):
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PackagingError("Environment files must use UTF-8; export cancelled.") from None
    for line in source.splitlines():
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        name, value = match.groups()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0:
                raise PackagingError(
                    "Multiline or unterminated environment values need manual cleanup."
                )
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        yield name, value


def _placeholder(value: str) -> bool:
    compact = re.sub(r"[\s_-]", "", value).casefold()
    return (
        not value
        or compact
        in {"changeme", "replaceme", "placeholder", "example", "dummy", "test", "none", "null"}
        or compact.startswith(
            ("yourapikey", "yourkeyhere", "yourtokenhere", "insertapikey", "pasteapikey")
        )
        or (value.startswith("<") and value.endswith(">"))
        or (value.startswith("${") and value.endswith("}"))
    )


def _read_source(path: Path, root: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    """Read regular files only; reject links, path escapes and source changes."""
    try:
        if _is_link(path) or not path.resolve().is_relative_to(root):
            raise PackagingError("A source link or path escape was detected; export cancelled.")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise PackagingError(
                "A source file is unsupported or exceeds the packaging size limit."
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise PackagingError("Source changed during export; retry after edits finish.")
            data = handle.read(limit + 1)
        if len(data) > limit or _is_link(path) or not path.resolve().is_relative_to(root):
            raise PackagingError(
                "Source changed or exceeded the packaging limit; export cancelled."
            )
        return data
    except PackagingError:
        raise
    except OSError:
        raise PackagingError("Could not safely read a source file; export cancelled.") from None


def _secrets(root: Path) -> tuple[bytes, ...]:
    env = root / ".env"
    if not env.exists() and not env.is_symlink():
        return ()
    values = []
    for name, value in _assignments(_read_source(env, root)):
        if _credential_name(name) and not _placeholder(value):
            values.extend(
                value.encode(encoding) for encoding in ("utf-8", "utf-16-le", "utf-16-be")
            )
    return tuple(set(values))


def _allowed_name(name: str) -> bool:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        return False
    parts = path.parts
    # Only the reviewed workflow is exported, not arbitrary GitHub metadata.
    if parts[0] == ".github" and name != ".github/workflows/quality.yml":
        return False
    if len(parts) == 1:
        if name not in ROOT_FILES and not fnmatch.fnmatchcase(name, "requirements*.txt"):
            return False
    elif parts[0] not in SOURCE_DIRS:
        return False
    for part in parts:
        lower = part.casefold()
        if (
            lower in PRIVATE_DIRS
            or lower == ".env"
            or (lower.startswith(".env.") and part != ".env.example")
        ):
            return False
        if any(fnmatch.fnmatchcase(lower, pattern) for pattern in PRIVATE_PATTERNS):
            return False
    return path.suffix.casefold() not in PRIVATE_SUFFIXES


def _check_content(name: str, data: bytes, secrets: tuple[bytes, ...]) -> None:
    if any(value in data for value in secrets):
        raise PackagingError(
            "Credential material detected in an export file; export cancelled. Remove it locally and retry."
        )
    if PurePosixPath(name).name == ".env.example":
        if any(_credential_name(key) and value for key, value in _assignments(data)):
            raise PackagingError(
                "Credential assignments in .env.example must be blank; export cancelled."
            )


def _sources(root: Path):
    for item in sorted(root.iterdir()):
        if _is_link(item):
            continue
        if item.is_file() and _allowed_name(item.name):
            yield item, item.name
        elif item.is_dir() and item.name in SOURCE_DIRS:
            for current, dirs, files in os.walk(item, followlinks=False):
                directory = Path(current)
                dirs[:] = sorted(
                    name
                    for name in dirs
                    if not _is_link(directory / name)
                    and (
                        (directory / name).relative_to(root).as_posix() == ".github/workflows"
                        or _allowed_name(
                            (directory / name / "file.py").relative_to(root).as_posix()
                        )
                    )
                )
                for name in sorted(files):
                    candidate = directory / name
                    relative = candidate.relative_to(root).as_posix()
                    if not _is_link(candidate) and _allowed_name(relative):
                        yield candidate, relative


def validate_archive(path: Path, secrets: tuple[bytes, ...] = ()) -> tuple[int, int]:
    """Validate names, contents and expansion bounds without extracting files."""
    count = total = 0
    names = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                normalized = entry.filename.casefold()
                if (
                    not _allowed_name(entry.filename)
                    or normalized in names
                    or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                ):
                    raise PackagingError(
                        "Archive validation rejected a private, unsafe or duplicate entry."
                    )
                names.add(normalized)
                count += 1
                total += entry.file_size
                if count > MAX_FILES or entry.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise PackagingError("Archive exceeds the packaging limits.")
                _check_content(entry.filename, archive.read(entry), secrets)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        raise PackagingError("Archive verification failed; no release was published.") from None
    if count == 0:
        raise PackagingError("No allowed source files were found; no release was published.")
    return count, total


def package_release(root: Path | str, output: Path | str) -> dict:
    root = Path(root).absolute()
    output = Path(output).absolute()
    if not root.is_dir() or _is_link(root):
        raise PackagingError("The source root must be an existing directory, not a link.")
    root = root.resolve()
    if output.suffix.casefold() != ".zip":
        raise PackagingError("The output filename must end in .zip.")
    if output.exists() or output.is_symlink():
        raise PackagingError(
            "Output already exists. Choose a new filename; existing archives are never overwritten."
        )
    if not output.parent.is_dir():
        raise PackagingError("The output directory must already exist.")
    secrets = _secrets(root)
    fd, temporary = tempfile.mkstemp(prefix=".studio-release-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        count = total = 0
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for path, name in _sources(root):
                data = _read_source(path, root)
                count += 1
                total += len(data)
                if count > MAX_FILES or total > MAX_TOTAL_BYTES:
                    raise PackagingError("Source exceeds the packaging limits.")
                _check_content(name, data, secrets)
                archive.writestr(name, data)
        count, total = validate_archive(temporary, secrets)
        # Windows rename is atomic and refuses an existing destination. POSIX
        # rename overwrites, so use atomic no-clobber hard-link publication there.
        try:
            if os.name == "nt":
                os.rename(temporary, output)
            else:
                os.link(temporary, output)
                temporary.unlink()
        except FileExistsError:
            raise PackagingError(
                "Output appeared during export; existing archive was preserved."
            ) from None
        return {"output": str(output), "files": count, "source_bytes": total, "verified": True}
    except PackagingError:
        raise
    except OSError:
        raise PackagingError("Packaging failed; no existing archive was overwritten.") from None
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = package_release(args.root, args.output)
    except PackagingError as exc:
        print(f"Export refused: {exc}", file=sys.stderr)
        return 1
    print(f"Verified source ZIP created: {result['output']} ({result['files']} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
