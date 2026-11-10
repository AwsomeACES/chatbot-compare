# Release checklist

Purpose: a repeatable, portable procedure for cutting a release candidate.
Last updated: 2026-11-09.

Run every command from the repository root using the project environment. Record the actual output in [verification.md](verification.md) — not a summary of what you expected.

On Windows use `.\.venv\Scripts\python.exe`; on macOS and Linux use `.venv/bin/python`. The examples below use the Windows form.

## 1. Confirm the candidate identity

```powershell
git status --short
git log -1 --format="%H %ci %s"
git diff --check
```

A dirty tree is allowed for a candidate, but the artifact must then be identified by its own manifest and hash, **never attributed to HEAD alone**.

## 2. Quality gates

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts sample_project
.\.venv\Scripts\python.exe -m ruff check app tests scripts sample_project
npm run format:check
npm run check:js
npm run test:ui
.\.venv\Scripts\python.exe scripts/check_docs.py
.\.venv\Scripts\python.exe -m pytest -q
```

Run `pytest` **serially on an otherwise idle machine**. It contains the real-time benchmark, whose measurement is only valid under those conditions. Never run a parallel stress harness at the same time, and never raise the benchmark threshold or shrink its workload to obtain a pass — profile and fix, or record the regression.

## 3. Browser and interface checks

```powershell
.\.venv\Scripts\python.exe scripts/check-studio-ui.py --artifacts runtime/ui-artifacts
.\.venv\Scripts\python.exe scripts/check-exact-compare.py
.\.venv\Scripts\python.exe scripts/check_contrast.py
```

Keep artifacts only from synthetic or redacted fixtures. A text search is not a substitute for a real browser check.

## 4. Build the source archive

Build into an ignored output directory, never into the working tree:

```powershell
.\.venv\Scripts\python.exe scripts/package_release.py --root . --output runtime/release/ai-agent-studio-<version>.zip
```

The packager refuses to overwrite an existing archive, refuses credential material, and validates the archive before publishing it. If it refuses, fix the cause locally; do not widen the manifest to silence it.

## 5. Prove the archive installs on its own

Extract to a **fresh directory outside the repository**, then install from the archive's own files:

```powershell
Expand-Archive runtime/release/ai-agent-studio-<version>.zip -DestinationPath $env:TEMP\studio-verify
cd $env:TEMP\studio-verify
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

A passing in-place development checkout does **not** satisfy this step. Verify at least once with a path containing a space.

Then confirm the failure paths give actionable errors: a missing Python, an occupied port, a missing browser library, and an unavailable optional tool.

## 6. Record the manifest and hashes

Record the candidate commit and tree identity, version, artifact SHA-256, the platform matrix with what was actually qualified, and the test evidence. Compute the hash of the **final** artifact, not an earlier build:

```powershell
Get-FileHash runtime/release/ai-agent-studio-<version>.zip -Algorithm SHA256
```

## 7. Update the documents

- [CHANGELOG.md](../CHANGELOG.md) — added, fixed and known limitations.
- [verification.md](verification.md) — commands, dates, environment, revision, observed results and untested limits.
- [open-source-readiness.md](open-source-readiness.md) — gate status and blocking decisions.
- [tasks.md](tasks.md) — acceptance evidence for every affected task.
- Root `PROGRESS.md`, `HANDOFF.md` and `DECISIONS.md` — append; never overwrite history.

## 8. Gate before publishing

Publication is a separate, explicitly authorized action. Before it:

- [ ] The license and distribution rights are confirmed by the owner in writing.
- [ ] The private-material review is current for this exact candidate.
- [ ] Every claim in the README matches a recorded result.
- [ ] Unqualified platforms and uncalibrated Judges are stated, not implied.
- [ ] A reviewer can read the manifest, hashes, limitations and rollback steps before approving.

## Rollback

The release artifact is a source archive; it installs into its own directory and writes nothing outside it.

- **Undo a candidate:** delete the extracted verification directory and the archive from `runtime/release/`. Nothing in the working tree changes.
- **Undo local repository changes:** the candidate branch is separate from `master`. `git switch master` restores the previous state; no history is rewritten.
- **A published release:** retract the tag and release, keep the commit, and record the reason in `DECISIONS.md`. Do not rewrite published history; publish a corrected version instead.
- **Runtime data is never part of a rollback.** Saved evaluations live in the ignored `runtime/` directory and are the owner's data. Deleting a candidate must not touch them.
