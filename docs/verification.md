# Ticket 89 verification record

Date: 2026-10-13. Scope: maintained source, development checks and documentation.
All evaluation tests use local/synthetic fixtures; no chatbot quality benchmark
or paid provider request is claimed.

## Checks

| Check                      | Result                                                                                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dependency consistency     | `pip check`: no broken requirements                                                                                                                       |
| Python format and lint     | Ruff format/check passed for maintained Python files                                                                                                      |
| Frontend/docs formatting   | Prettier check passed                                                                                                                                     |
| JavaScript syntax          | 21 files parsed successfully without executing helper scripts                                                                                             |
| Startup script             | PowerShell parser accepted `run.ps1`                                                                                                                      |
| Case-builder compatibility | Generated case payloads identical to the pre-refactor app in eight configurations spanning judge on/off, references and legacy-variation settings         |
| Literal wrapping           | Python AST compared before/after wrapping to preserve literal values                                                                                      |
| Isolated browser           | Four-target setup, exact preview, matrix, evidence details, baseline saving, concurrency controls and starting another run passed; zero JavaScript errors |

Final regression suite: **123 passed, 1 skipped, 1 dependency deprecation warning**
in 101.66 seconds. Python format/lint checks cover 41 maintained files. The
initial 121-test pass preceded the additional packaging and entry-point checks.

## Corrections found during verification

- Ruff's unused-import cleanup removed the public `app.main` export. Browser
  startup caught this before deployment. The export is now explicit (`app as app`),
  with a production-entry-point regression test.
- The browser check now fails explicitly if its isolated server exits or never
  becomes healthy, rather than continuing with an unavailable URL. Its working
  directory is explicit.
- A session/pacing fixture hit its unrelated two-second timeout under simultaneous
  browser/test load. Its timeout allowance is now 30 seconds; the actual pacing
  and latency assertions remain, with additional assertions requiring all four
  turns to complete without errors. Production timeouts were not changed.
- Release packaging now includes reviewed CI/dev/doc files while rejecting other
  GitHub metadata. A regression test covers both inclusion and exclusion.

## Dependency audit

The installed core environment reported FastAPI 0.142.2, Uvicorn 0.54.0, HTTPX
0.28.1, pytest 9.1.1, Playwright 1.63.0, ReportLab 5.0.1, LiteLLM 1.105.0 and Ruff
0.14.1. These are observed local versions, not a new runtime lockfile.

DeepEval, DeepTeam, Garak and Transformers were absent. Torch 2.14.1 was present;
this alone establishes neither HHEM nor QwenGuard availability. Their real engine
integration is tracked in MAINT-02. No historical install log is used as current
proof of successful installation.

## Limits of this verification

- Local fixtures verify interface behavior, not universal connector compatibility.
- One Windows symlink test needs permission to create symlinks and is skipped
  when that permission is unavailable.
- The installed FastAPI/Starlette test client emits an HTTPX deprecation warning;
  it is not a failed application check.
- The GitHub Actions workflow is configured, but its hosted run requires publishing
  the change. No commit, push or remote CI success is claimed by this record.
- Historical source, reports and old notes are preserved; optional capabilities
  remain explicitly tracked in `BACKLOG.md` rather than advertised as complete.

## Deployment

Applied reviewed files to the live Studio and existing `hussain-code` checkout.
The idle server on port 2708 restarted successfully. Health returned OK; the live
setup page returned HTTP 200 with zero JavaScript errors. Source backups were
kept outside the project; local credentials and existing runtime data were not
copied or replaced. Git whitespace checks passed. Git attributes now retain LF
for formatter-managed files on Windows and in CI; editor defaults document the
same indentation rules.

## Recovery and visible controls — 14 October 2026

- Before quota-pause additions: 131 platform tests passed, 1 skipped. Ruff
  check and formatting passed; 22 JavaScript files passed syntax checks.
- Browser checks: all 509 imported cases retained, all 16 categories selected,
  Kimi endpoint selection correct, key input remains a password field, slow
  mode sets 30-second gaps and a 720-minute ceiling. No console errors observed.
- Live provider diagnostics are blockers, not quality failures: both Gemini
  keys hit the same daily limit; Kimi returned insufficient balance. Full
  chatbot coverage is not claimed. Known recorded subtotal is $0.018593, but
  final cost is unknown because failed attempts have incomplete billing data.

## 2026-10-24 — Verification categories recorded separately (T-032)

These five categories are deliberately kept apart. Passing one is not evidence for another: a Linux container or a WSL shell does not qualify native macOS, and a committed CI configuration file is not evidence that a remote job ran.

| Category                             | What it covers                                                                                                | Exercised on                                                   | Result                                                                            | Not exercised                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Unit and integration tests**       | `python -m pytest` with synthetic fixtures and mocked providers                                               | Windows 11, Python 3.12.3, project `.venv`                     | See the dated run in PROGRESS.md                                                  | Native Linux and macOS runs                                                       |
| **Dependency locks**                 | Clean hash-verified install from `requirements-dev.lock`, then `pip check` and the full suite                 | Windows 11, a fresh virtual environment outside the repository | 78 packages, no broken requirements, suite passed                                 | Native Linux and macOS installs; the optional evaluation lock was never installed |
| **Browser tests**                    | `scripts/check-studio-ui.py` (current shell) and `scripts/check-exact-compare.py` (retained legacy interface) | Headless Chromium on Windows 11                                | Both passed locally                                                               | Firefox and WebKit; any browser on Linux or macOS                                 |
| **Launcher verification**            | `start.sh`, `run.ps1`, `Dockerfile`, `compose.yaml` creating an environment and serving Studio                | `run.ps1` on Windows 11 only                                   | Windows launcher used throughout this work                                        | `start.sh` on native Linux or macOS; a container build and run                    |
| **Native scanner qualification**     | Docker or WSL scanner images, offline databases, read-only mounts, no-network sandbox                         | Not exercised in this task                                     | No scan was run                                                                   | Every target OS; image and database provisioning                                  |
| **Local and cloud model validation** | A real local Judge (Ollama) or an authorised cloud provider answering real requests                           | Not exercised in this task                                     | No provider call was made; every test used mocked providers or synthetic fixtures | All providers; no paid call was authorised or made                                |

Two further boundaries, so a reader does not over-read the table:

- **Human-label calibration** is implemented and tested with synthetic fixtures, but no representative human labels exist, so every Judge reports **uncalibrated**. See [judge-validation.md](judge-validation.md).
- **CI** is configured for Windows, Ubuntu and macOS, installs Linux browser system dependencies and keeps failure traces. That configuration has not been executed on a remote runner as part of this work, so CI behaviour on Linux and macOS is configured but not observed.
