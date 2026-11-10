# Changelog

Notable changes to AI Agent Studio. Dates are release-candidate dates, not
published release dates. This project has not had a tagged public release yet.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
loosely; versions are not yet semantic because no public API is promised.

## Unreleased — release candidate 0.1.0-rc.1 (2026-11-09)

First candidate prepared for an open-source release. The application itself was
already developed over the preceding commits; this entry records the work done
to make it distributable and honestly described.

### Added

- `LICENSE`: MIT, copyright 2026 Moinuddeen Hussain.
- `CHANGELOG.md`, issue templates and a pull request template.
- `docs/open-source-readiness.md`: the release gate ledger with evidence.
- `docs/release-checklist.md` and `docs/troubleshooting.md`.
- Packaging tests that export the **real** repository and assert the archive
  contains the launchers, hash-locked requirements and the license.

### Fixed

- The source packager omitted `requirements*.lock`, `start.sh`, `Dockerfile`,
  `Dockerfile.scanners`, `compose.yaml` and `.dockerignore`, so an extracted
  archive could not follow its own documented setup instructions.
- The README quality badge pointed at an unrelated repository and branch.
- `docs/api-keys.md` contained an absolute workstation path into a separate
  local project; it now uses a portable placeholder.
- The shipped README linked internal working history that the source archive
  deliberately excludes.

### Known limitations

See [docs/open-source-readiness.md](docs/open-source-readiness.md) for the full
gate status. In short: Judges are **uncalibrated** against human labels, native
Linux and macOS startup is **not qualified**, and no live provider smoke test
was run for this candidate.
