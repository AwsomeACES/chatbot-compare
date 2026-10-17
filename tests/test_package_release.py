"""Synthetic fixtures only: never read the developer's actual .env."""

import importlib.util
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "package_release", Path(__file__).parents[1] / "scripts" / "package_release.py"
)
packager = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(packager)


def write(root, name, data="source\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def source(tmp_path):
    root = tmp_path / "studio"
    root.mkdir()
    write(root, "app/main.py", "print('hello')\n")
    write(root, "README.md", "Studio source\n")
    write(root, ".env.example", "STUDIO_JUDGE_API_KEY=\nSTUDIO_JUDGE_KEY_NAME=GEMINI_API_KEY\n")
    return root


def test_safe_archive_verified_and_private_files_excluded(tmp_path):
    root = source(tmp_path)
    private = [
        ".env",
        ".env.production",
        "app/.env",
        "app/nested/.env.local",
        "app/nested/.ENV",
        "app/credentials.json",
        "app/key.pem",
        "app/data.sqlite",
        "app/data.sqlite-wal",
        "app/debug.log",
        "app/archive.zip",
        "app/__pycache__/x.pyc",
        "runtime/result.json",
        "runs/result.json",
        ".git/config",
        ".venv/data.py",
        "app/node_modules/private.js",
        "app/secrets/token.txt",
        "app/dist/bundle.js",
        "scripts/.aws/config",
        "personal-notes.txt",
    ]
    for name in private:
        write(root, name, "PRIVATE_FIXTURE_DATA")
    write(root, "tests/test_example.py", "def test_ok(): pass\n")
    write(root, "sample_project/main.py", "print('sample')\n")
    write(root, "requirements-dev.txt", "pytest\n")
    output = tmp_path / "release.zip"
    result = packager.package_release(root, output)
    assert result["verified"] is True
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == result["files"] == 6
        assert not set(private).intersection(names)
        assert {
            ".env.example",
            "app/main.py",
            "tests/test_example.py",
            "sample_project/main.py",
        } <= set(names)
        assert not any(b"PRIVATE_FIXTURE_DATA" in archive.read(name) for name in names)
    assert packager.validate_archive(output)[0] == 6


def test_release_includes_quality_tools_but_not_arbitrary_github_files(tmp_path):
    root = source(tmp_path)
    included = [
        "pyproject.toml",
        ".editorconfig",
        "package.json",
        "package-lock.json",
        "requirements-dev.txt",
        ".prettierrc.json",
        ".prettierignore",
        "CONTRIBUTING.md",
        "BACKLOG.md",
        "docs/verification.md",
        ".github/workflows/quality.yml",
    ]
    for name in included:
        write(root, name)
    write(root, ".github/private-notes.txt")
    write(root, ".github/workflows/unreviewed.yml")
    write(root, ".github/workflows/file.py")
    write(root, "docs/.env", "PRIVATE_FIXTURE_DATA")
    output = tmp_path / "release.zip"
    packager.package_release(root, output)
    with zipfile.ZipFile(output) as archive:
        assert set(included) <= set(archive.namelist())
        assert ".github/private-notes.txt" not in archive.namelist()
        assert ".github/workflows/unreviewed.yml" not in archive.namelist()
        assert ".github/workflows/file.py" not in archive.namelist()
        assert "docs/.env" not in archive.namelist()


def test_embedded_local_credential_blocks_publication_without_value_in_error(tmp_path, capsys):
    root = source(tmp_path)
    credential = "fixture-credential-only-123456789-no-provider"
    write(root, ".env", f"STUDIO_JUDGE_API_KEY={credential}\n")
    write(root, "app/accidental.txt", f"copied={credential}")
    output = tmp_path / "release.zip"
    assert packager.main(["--root", str(root), "--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert "Credential material detected" in captured.err
    assert credential not in captured.err + captured.out
    assert not output.exists()
    assert not list(tmp_path.glob(".studio-release-*"))


@pytest.mark.parametrize(
    "assignment",
    ["GEMINI_API_KEY=fixture-secret", "ANTHROPIC_API_KEY='your-key-here'", "PASSWORD=abc"],
)
def test_template_credentials_must_be_blank(tmp_path, assignment):
    root = source(tmp_path)
    write(root, ".env.example", assignment)
    with pytest.raises(packager.PackagingError, match="must be blank"):
        packager.package_release(root, tmp_path / "release.zip")
    assert not (tmp_path / "release.zip").exists()


def test_placeholder_and_key_variable_name_are_not_credentials(tmp_path):
    root = source(tmp_path)
    write(
        root,
        ".env",
        "STUDIO_JUDGE_API_KEY=your-api-key-here\nSTUDIO_JUDGE_KEY_NAME=GEMINI_API_KEY\n",
    )
    write(root, "README.md", "Use GEMINI_API_KEY; replace your-api-key-here locally.\n")
    assert packager.package_release(root, tmp_path / "release.zip")["verified"]


def test_existing_output_is_not_overwritten(tmp_path):
    root = source(tmp_path)
    output = tmp_path / "release.zip"
    output.write_bytes(b"existing archive sentinel")
    with pytest.raises(packager.PackagingError, match="already exists"):
        packager.package_release(root, output)
    assert output.read_bytes() == b"existing archive sentinel"


def test_symlink_escape_is_skipped(tmp_path):
    root = source(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("PRIVATE_OUTSIDE_SOURCE", encoding="utf-8")
    try:
        (root / "app" / "escape.txt").symlink_to(outside)
        (root / "scripts").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows account cannot create symlinks")
    output = tmp_path / "release.zip"
    packager.package_release(root, output)
    with zipfile.ZipFile(output) as archive:
        assert "app/escape.txt" not in archive.namelist()
        assert not any(name.startswith("scripts/") for name in archive.namelist())


def test_archive_validation_rejects_private_entries(tmp_path):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("app/.env", "SHOULD_NEVER_EXPORT=fixture")
    with pytest.raises(packager.PackagingError, match="unsafe"):
        packager.validate_archive(path)


def test_size_limits_fail_without_publishing(tmp_path, monkeypatch):
    root = source(tmp_path)
    monkeypatch.setattr(packager, "MAX_TOTAL_BYTES", 5)
    with pytest.raises(packager.PackagingError, match="limits"):
        packager.package_release(root, tmp_path / "release.zip")
    assert not (tmp_path / "release.zip").exists()


def test_output_race_preserves_newly_created_output(tmp_path, monkeypatch):
    root = source(tmp_path)
    output = tmp_path / "release.zip"
    original_validate = packager.validate_archive

    def raced_validate(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        output.write_bytes(b"concurrent output")
        return result

    monkeypatch.setattr(packager, "validate_archive", raced_validate)
    with pytest.raises(packager.PackagingError, match="appeared"):
        packager.package_release(root, output)
    assert output.read_bytes() == b"concurrent output"
