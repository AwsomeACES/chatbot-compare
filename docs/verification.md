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

## 2026-11-09 — Open-source release candidate 0.1.0-rc.1 (T-046 to T-052)

Environment: Windows 11 Home Single Language 10.0.26300, Python 3.12.3, Node 24.18.0,
pip 24.0. Repository `AI-Agent-Testing-Studio`, branch `codex/open-source-release`,
based on commit `cfbe8de`. Every check below used synthetic fixtures and mocked
providers. **No provider credential was used and no paid or cloud call was made.**

A note on provenance: the working tree used for the earlier reliability work lived on a
removable `D:` volume that disconnected mid-session, and Windows logged NTFS delayed-write
failures against it. Because that tree was clean and its HEAD matched the published
`master`, the source was recovered byte-for-byte by cloning the remote, and the recovered
inventory matched the lost tree at **184 of 184** source files. The lost volume's
git-ignored `runtime/` directory was **not** recovered and is not part of any artifact.

### Regression suite

| Check                        | Command                                             | Result                                           |
| ---------------------------- | --------------------------------------------------- | ------------------------------------------------ |
| Dependency consistency       | `python -m pip check`                               | No broken requirements                           |
| Full suite, before this work | `python -m pytest -q`                               | **803 passed, 2 failed, 1 skipped** in 195.65 s  |
| Bounded PDF rendering        | `python -m pytest tests/test_report_bounds.py -q`   | 9 passed                                         |
| Synthetic demo               | `python -m pytest tests/test_demo.py -q`            | 12 passed                                        |
| Packaging                    | `python -m pytest tests/test_package_release.py -q` | 14 passed, 1 skipped                             |
| Documents                    | `python scripts/check_docs.py`                      | Passed across every maintained Markdown document |

The two failures in the pre-work run were the newly added packaging tests, which
correctly reported that `LICENSE`, `CHANGELOG.md` and the `.github` templates were not
yet tracked and that the README linked two documents the archive excludes. Both causes
were fixed rather than the assertions relaxed. The final suite result for this candidate
is recorded in the summary row at the end of this section.

The 1 skip is `test_symlink_escape_is_skipped`, which skips on a Windows account that
cannot create symlinks. It is not a disabled failure.

### Release candidate packaging

| Step                               | Result                                                                                                                                                                           |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Archive build                      | `scripts/package_release.py` produced a verified ZIP of **229 files**                                                                                                            |
| Required setup files present       | All three lockfiles, `run.ps1`, `start.sh`, `Dockerfile`, `Dockerfile.scanners`, `compose.yaml`, `.dockerignore`, `LICENSE`, `CHANGELOG.md` and the reviewed `.github` templates |
| Fresh extraction                   | Extracted to a directory **whose path contains spaces**, outside the repository                                                                                                  |
| Locked install from the archive    | `pip install --require-hashes -r requirements.lock` succeeded; **75 packages**; `pip check` clean                                                                                |
| Resolved versions                  | fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, litellm 1.105.0, reportlab 5.0.1, playwright 1.63.0, PyYAML 6.0.3                                                                 |
| Start with the documented launcher | `powershell -ExecutionPolicy Bypass -File .\run.ps1 -Port 2811` served **HTTP 200**, 20941 bytes, in **6.9 s**                                                                   |
| `.env` bootstrap                   | The launcher copied `.env.example` to `.env` in the fresh directory                                                                                                              |
| Occupied port                      | Refused with `[Errno 10048] error while attempting to bind`, then shut down cleanly. It did not hang                                                                             |

**Not exercised in the fresh install:** the first-run `playwright install chromium`
download was skipped, because the environment was created before the launcher ran. The
web-chat browser connector is therefore **unverified** in the extracted archive, and a
genuine first run additionally downloads Chromium. The `start.sh` path was not executed
at all; see the platform limits below.

### Synthetic no-key demo

Two real processes, driven over HTTP, with no provider credential:

| Step                        | Result                                                                                   |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| Demo bot startup            | Ready in **1.1 s** on `127.0.0.1:2809`                                                   |
| Studio startup              | Ready in **0.5 s**                                                                       |
| Demo bot answered over HTTP | `POST /chat` returned the catalogue warranty answer                                      |
| Demo Cases fetched          | **8 Cases**, published with `judge_enabled=false`                                        |
| Run                         | Completed through the ordinary API connector and runner                                  |
| Scoring without any Judge   | **8 of 8 results scored — 7 passed, 1 failed**                                           |
| JSON export                 | HTTP 200, and its `id` matched the selected Run                                          |
| PDF export                  | Rendered, **59760 bytes**, valid `%PDF` header                                           |
| Restart durability          | After restarting Studio only, the Run was still listed and reopened with the same status |

The single failing Case is deliberate: the demo bot answers a refund question with an
invented unconditional guarantee and the Case forbids that phrase. A demo in which
everything passed would misrepresent the tool.

**What this does not establish:** the demo measures hand-written strings in
`app/blackbox/demo_bot.py`. It is not a measurement of any real chatbot, and it says
nothing about Judge accuracy because no Judge ran.

### Prerequisite and failure behaviour

On this machine **Docker is not installed** and **Ollama is installed**, which made the
missing-prerequisite path testable rather than assumed.

- White-box readiness with no source supplied reported **`ready: 0`** across all 14
  checks, each with the reason "No source ZIP or repository was supplied", under the
  notice "Ready means the check can be attempted. It is not a pass."
- **Not verified:** the Docker-absent path with a source ZIP actually supplied, any
  scanner execution, the scanner image and database provisioning, and the optional
  HHEM/Qwen classifiers, which remain disabled and unverified.

### Private material review

- No `.env`, key, certificate or credential file was added in **any reachable commit**.
- No provider-key-shaped string appears in any reachable commit. Patterns covered
  Google, Anthropic, OpenAI-style, GitHub, Slack and AWS keys, and PEM private-key headers.
- Credential-shaped literals in `tests/test_export_redaction.py` and
  `tests/test_judge_calibration.py` are synthetic fixtures whose purpose is to be
  redacted; they sit beside a fictional phone number, `example.com` and documentation UUIDs.
- The 509-Case and 20-per-Category packs contain **authored synthetic prompts** using
  synthetic identifiers, not customer transcripts or personal data.
- **Disclosure limit:** this is pattern scanning over reachable commits. It is evidence
  that nothing was found, not proof that nothing exists. Unreachable objects and any
  other remote are out of scope.
- **Owner decision outstanding:** a named third-party company still appears in shipped UI
  labels, auto-detection logic, API route names and case-pack filenames. Recorded in
  [open-source-readiness.md](open-source-readiness.md).

### Platform limits for this candidate

| Platform                | Status                                                                            |
| ----------------------- | --------------------------------------------------------------------------------- |
| Windows 11, Python 3.12 | Qualified: locked install, launcher start, demo, suite, packaging                 |
| Linux (native)          | **Not qualified.** `start.sh` was not executed                                    |
| macOS (native)          | **Not qualified.** `start.sh` was not executed                                    |
| Docker container        | **Not qualified.** No image was built; Docker is absent on this machine           |
| Remote CI               | **Not observed.** No remote run was triggered, and publication was not authorized |

Python support is claimed for **3.12 only**, which is the one version tested. Node 24.18.0
was used for contributor checks; Studio does not require Node at runtime.

### Pacing and the real-time benchmark

The bounded parallel pacing harness, the clock seam and the fake-clock pacing tests exist
only in a **separate local working tree** and are **not present in this repository**, so
this candidate reports pacing stress as **Not tested** rather than citing the other tree's
recorded 50 of 50 result. `tests/test_concurrency.py` and the real-time benchmark in
`tests/test_speed_cache.py` do pass here, which is a narrower claim. The benchmark
threshold was not changed and no workload was reduced.
