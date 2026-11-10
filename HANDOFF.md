## 2026-11-10 — Shared hussain-code update

The owner explicitly requested publishing the current release updates to AwsomeACES/chatbot-compare, branch hussain-code. Integration is prepared in the isolated `studio-hussain-update-20261110` worktree from shared commit `db02513`, preserving its older comparison-tool files. The release source is the C: `AI-Agent-Testing-Studio` checkout at `cfbe8de` plus its 34 staged release changes. The separate studio-publish lineage was not merged.

The README conflict was resolved by retaining current installation guidance. Formatting corrections are included. See [the dated release review](docs/release-review-20261110.md) for five still-open functional defects and test boundaries. This is a branch update, not a release-ready claim or authorization to publish a tag or release. Publication outcome and final checks are recorded in PROGRESS below and the user-facing response.

## 2026-11-09 — Open-source release candidate 0.1.0-rc.1 (current task)

Read this section first; everything below it is dated history.

### Where the work is

```text
C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\AI-Agent-Testing-Studio
```

Branch `codex/open-source-release`, based on `cfbe8de` (= published `origin/master`).
Remote `origin` is `https://github.com/Simali2724/AI-Agent-Testing-Studio.git`, which is
**already public**. **Nothing was pushed, committed, tagged, published or made visible by
this task**; all changes are uncommitted in the working tree. No provider credential was
used and no paid or cloud call was made.

### Why the path changed — read before looking for `D:`

The session started in `D:\AI-Agent-Testing-Studio`. **That volume was removable and it
disconnected mid-session.** Windows logged NTFS `Delayed Write Failed` errors against
`D:\$Mft` and `D:\AI-Agent-Testing-Studio\.venv\...` at 22:08:40, then the volume vanished;
`Get-Disk` now shows only the internal NVMe. Every command issued against `D:` had been
read-only.

The tree was **clean** and its HEAD equalled published `master`, so the source was recovered
in full by cloning to `C:`. The recovered inventory matched the lost tree at **184 of 184**
source files. **Not recovered:** that volume's git-ignored `runtime/` directory, which held
local saved evaluations, and its local `.env`. If the drive is reconnected, that data may
still be there — nothing was deleted by this work.

### The other checkout — do not merge it blindly

`C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\studio-publish` still exists,
untouched, on branch `codex/industry-reliability` at `043173c` with ~48 dirty files. It holds
work this lineage does **not** have: `app/blackbox/voltkart.py`, `app/blackbox/judge_review.py`,
`app/studio/judge-rubric.json`, a `scheduling.py` clock seam, `tests/fake_clock.py`,
`tests/test_pacing.py` and `scripts/pacing-stress.py`.

It also uses a **different task-ID lineage**: there T-040 to T-042 mean rubric review, pacing
and the release program, while in this repository they mean reference facts, cost redaction and
endpoint pricing. Do not cross-reference task numbers between the two. The owner chose to build
this candidate from the published lineage only and to defer that work (T-052).

### Phase status

| Item                                      | Status                                                            |
| ----------------------------------------- | ----------------------------------------------------------------- |
| T-046 bounded PDF rendering               | **Done**, 9 tests                                                 |
| T-047 no-key synthetic demo               | **Done**, 12 tests plus a real end-to-end run                     |
| T-048 source archive manifest repaired    | **Done**, 14 tests including a real-repository export             |
| T-049 license and honest public documents | **Done**                                                          |
| T-050 document link checking broadened    | **Done**, now 32 documents                                        |
| T-051 owner decisions                     | **Blocked** on the owner                                          |
| T-052 pacing stress and native platforms  | **Blocked**; absent from this lineage, no Linux/macOS environment |

### Commands and results

All recorded with observed numbers in [docs/verification.md](docs/verification.md), newest
section. Summary: ruff format and check clean over 134 files; Prettier clean including the new
`.github` templates; `check:js` 16 files; `test:ui` 23 passed; `scripts/check_docs.py` passed
over 32 documents; packaging 14 passed 1 skipped; a fresh extracted archive installed 75
packages with `pip check` clean and `run.ps1` served HTTP 200 in 6.9 s from a path with spaces;
the demo scored 8 of 8 Cases with no Judge, 7 passed and 1 failed, and survived a restart.

The one skip is `test_symlink_escape_is_skipped`, which skips where the Windows account cannot
create symlinks. It is not a disabled failure.

### Failed or not-run checks

- **Pacing stress: not run.** No harness exists here. Do **not** record the other tree's 50 of
  50 result against this candidate.
- **`start.sh` on native Linux or macOS: not run.** No such environment was available.
- **Docker: not run.** Docker is not installed on this machine, so no image was built and no
  White-box scanner executed.
- **Remote CI: not run.** Publication was not authorized, so no candidate commit was pushed.
- **Live provider smoke test: not run.** No credential was requested or used.
- **Human calibration labels: not obtained.** Judges remain uncalibrated and are labelled so.
- **Chromium first-run download: skipped** in the fresh install, so the web-chat browser
  connector is unverified in the extracted archive.

### Private data boundaries

- No `.env`, key, certificate or provider-key-shaped string exists in any reachable commit.
- Credential-shaped literals in `tests/test_export_redaction.py` and
  `tests/test_judge_calibration.py` are synthetic redaction fixtures. Leave them.
- `PROGRESS.md` and `HANDOFF.md` are deliberately **excluded from the source archive** and no
  longer linked from the public README. Keep them that way.
- Pattern scanning proves nothing was found, not that nothing exists. Say it that way.

### Pending approvals

1. Written confirmation that all included material is the owner's to distribute under MIT.
2. The decision on the named third-party company still present in UI labels, auto-detection
   logic, API route names and case-pack filenames. Content is synthetic; the naming is public.
3. A security reporting route. GitHub private vulnerability reporting is **verified disabled**
   (`"enabled": false` as of 2026-11-09). No address was invented.
4. Explicit authorization before any push, tag, release or announcement.

### Numbered next steps

1. Review the working-tree diff on `codex/open-source-release`, then commit it after a
   secret-safe staged review. A local commit is not permission to push.
2. Get the owner's answers to the four pending approvals above and record them in
   `DECISIONS.md` and `docs/open-source-readiness.md`.
3. Rebuild the archive after any further change, recompute its SHA-256, and update the manifest
   — the hash must describe the **final** artifact, not an earlier build.
4. If pacing matters for the release, port only the pacing files from `studio-publish`
   (`scheduling.py` clock seam, `tests/fake_clock.py`, `tests/test_pacing.py`,
   `scripts/pacing-stress.py`), renumbering their task IDs to free ones, then run
   `scripts/pacing-stress.py --repetitions 50 --parallel 12` separately from the benchmark.
5. For Linux and macOS, run a fresh extracted install and `./start.sh` on each, and record the
   result in `docs/verification.md`. Until then keep the narrowed support claims.
6. Enable GitHub private vulnerability reporting, then replace the notice in `SECURITY.md`.
7. Only after 1 to 3: tag and publish, as an explicitly authorized separate action.

Never mark the human-validation or pacing criteria Done by citing another tree's or another
chat's recorded numbers.

## 2026-10-29 — Evaluation reliability from the VoltKart retest (historical task)

Worked in `D:/AI-Agent-Testing-Studio`, branch `codex/industry-reliability`. **Nothing was pushed.**
No provider call, no paid evaluation, no Jira issue, no saved history deleted or modified. The only
network request was one read-only fetch of Google's public pricing page.

### Checkout decision, made after verifying all three

| Checkout                                                                             | Origin                             | State at start                                             |
| ------------------------------------------------------------------------------------ | ---------------------------------- | ---------------------------------------------------------- |
| `C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/studio-publish`       | AwsomeACES/chatbot-compare         | `codex/industry-reliability` @ `043173c`, 5 modified files |
| `C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/studio-simali-update` | Simali2724/AI-Agent-Testing-Studio | `master` @ `0978e48`, clean                                |
| **`D:/AI-Agent-Testing-Studio`** (used)                                              | Simali2724/AI-Agent-Testing-Studio | `codex/industry-reliability` @ `90cd616`, clean            |

Every uncommitted file in `studio-publish` was verified to exist committed elsewhere first:
`simple.css`, `simple.js` and `test-studio-navigation.cjs` are byte-identical to Simali `0978e48`,
and `check-studio-ui.py` is committed in D: as `90cd616`. **Nothing was at risk of loss.** D: was
one commit behind, so `0978e48` was cherry-picked in as `3b93d74`. Both C: checkouts were left
exactly as found — re-verify with `git status` in each before any further work.

### Local commits, oldest first

Rebased onto `origin/master` (`0978e48`) before publication, which dropped an earlier
cherry-pick of that same commit as a duplicate patch. The tree is byte-identical to the
pre-rebase branch, confirmed with `git diff`, and the branch fast-forwards from `origin/master`.

| Commit    | Scope                                                                                            |
| --------- | ------------------------------------------------------------------------------------------------ |
| `88288c5` | Phase A — Judge score direction contract and self-contradiction handling (T-039)                 |
| `ad9f87a` | Phase B — claim rules, owner reference facts and capability declarations (T-040)                 |
| `4354e9f` | Phase C — numeric cost-field redaction (T-041) and provider/endpoint prices (T-042)              |
| `9185d8a` | Phases D/E/F — White coverage semantics (T-044), provider readiness (T-043), truthful UI (T-045) |
| `e04b42c` | Prettier formatting of DECISIONS.md                                                              |
| `f26cd73` | docs — T-039 to T-045 and the resolved defect rows                                               |
| `03614b8` | Phase H — read-time review of verdicts saved before the contract                                 |
| `3368b88` | Phase I — claim rules joined evaluator identity; PDF parity                                      |
| `c4462e8` | Phase J — declare facts and capabilities from the Evaluate screen                                |
| `5ae4872` | docs — this handoff and the extended T-040 entry                                                 |
| `83450b3` | Phase K — display the panel policy, failed judges and local-fallback cost                        |

A branch `backup/pre-rebase-84b788b` holds the pre-rebase tip in case the old hashes are needed.

### What to know before changing this further

1. **Score direction is a contract, not a prompt tweak.** `app/blackbox/judge_consistency.py`
   defines `compliance-higher-is-better-v1`: higher is better, bands `compliant` 80-100,
   `partially_compliant` 20-79, `non_compliant` 0-19 around the single pass threshold of 80.
   Single, batch and Bias judging all use it. Changing a band or the threshold changes what every
   verdict means; the bands are covered by a test that walks all 101 scores.
2. **The structured verdict is the primary check; the phrase list is not.** A Judge returns a
   `verdict` word beside its score and the two are compared. `NO_VIOLATION_CUES` is supplementary,
   may only raise a contradiction against a `non_compliant` score, and must never become the sole
   mechanism. Measured on the saved retest it flags 4 of 4 reported contradictions and 0 of 14
   genuine low-score verdicts; keep that property if you touch it.
3. **A contradiction is not the opposite verdict.** One bounded metered correction, then the raw
   output is kept and the Case reports insufficient reliable evidence as `not_tested` with
   `partial_score`. Never convert a zero into a pass.
4. **Historical records must keep deriving identically.** The consistency marker is written at
   judge time, so a record saved earlier has none and `bias.derive_algorithmic` produces exactly
   what it did before. A regression test pins this, and re-aggregating the real saved run changes
   no score, status or reason. Any new gate must be keyed on a field only new runs carry.
5. **Claim rules live in the user payload, not the system message.** That is why they needed their
   own identity (`judge_prompts.claim_rules_fingerprint`) before a reference change would invalidate
   a recorded alignment. `mismatch_reasons` reads it with `.get()` and treats a record written
   before the dimension existed as a **mismatch**. Any future rubric dimension needs the same
   treatment or alignment will silently look valid.
6. **The redaction exemption is gated on field name _and_ value shape.** `governance.PLAIN_AMOUNT`
   accepts a bare decimal including the `0E-12` exponent form. A telephone number parked in a cost
   field is still redacted. A test fails if `cost_summary` grows a `*_micro_usd` field the
   allowlist does not cover — classify it, do not widen the pattern.
7. **A price belongs to an endpoint.** `pricing.price_for` resolves endpoint, then provider, then
   catalogue, and withholds a catalogue entry whose provider does not match the call so the price
   stays Unknown. `openai-compatible` means "host not identified" and never matches a specific
   provider. Hand-checked rates go in `app/studio/verified-prices.json`, never in evaluation code.
8. **Two navigation-harness traps.** Script slices run in a `vm` realm, so an array built there has
   a different prototype and `assert.deepEqual` from `node:assert/strict` rejects it even when the
   contents match — copy with `Array.from` first. And Prettier reflows prose in `simple.html`, so a
   markup assertion should collapse whitespace rather than match across line breaks.
9. **Heredocs break on very long lines** in this shell. Write a script into the scratchpad directory
   and run it with the interpreter instead.

### Verification actually run (Windows 11 10.0.26300, Python 3.12.3, project `.venv`)

- Full suite: **793 passed, 1 skipped** (the Windows symlink privilege case) in 138.91 s.
- Navigation: **17 passed**. JavaScript syntax: 16 files. Ruff lint and format: 116 files.
  Prettier repository check and `scripts/check_docs.py`: clean.
- Isolated browser check `scripts/check-studio-ui.py`: every section passed including mobile
  layout, with **zero browser errors**.
- Measured contrast `scripts/check_contrast.py`: **44 pairs, 0 failing, 0 skipped**.
- Historical integrity, against the real saved run
  `40df499d-ea32-4a4a-b349-87fa441747c7`: re-aggregating changes **0** scores, **0** statuses and
  **0** reason strings; overall 91.81 preserved; derived Bias 70 and 40 preserved. The read-time
  review inspects 218 verdicts, finds the 4 reported contradictions and leaves the record
  byte-identical.
- Evidence files under
  `C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/voltkart-retest-20261029` are
  untouched (`black-results.json` sha256 begins `e0aeae048d62ce80`).

### Outstanding external prerequisites (ask only for these)

- **Human calibration labels under the current rubric.** Evaluator identity now includes the
  direction contract and the claim rules, so any earlier calibration correctly reports **stale**.
  No real human-labelled sample ever existed, so nothing measured was lost. Follow
  `docs/judge-validation.md`. The old 53% figure came from fabricated labels and must never be
  reported as validation.
- **A funded provider or a running local Ollama model** for any live validation. None was called.
  A fresh, clearly versioned re-judge of the Bias category under the new rubric needs this plus the
  owner's explicit go-ahead; it would be a **new Run**, never an edit of `40df499d…`.
- **Runtime evidence inputs** for the White checks whose `next_test` points at Gray-box:
  synthetic test users, tool-call logs, retention TTL, timeout/retry limits, a CI run link.
- **Scanner images and offline databases**, and **native Linux and macOS environments** (T-032).
- **An owner-supplied reference profile** if the hallucination and capability categories should be
  judged against declared facts rather than reported as unverified. The Evaluate screen now
  collects it; nothing is assumed in its absence.

### Startup

```powershell
cd D:\AI-Agent-Testing-Studio
.\run.ps1                                  # first run creates .venv and installs the locked set
# or, with an existing environment:
$env:STUDIO_AUTO_RESUME = "0"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2708
```

Studio serves the current shell at `http://127.0.0.1:2708/`. Do not resume or rerun the completed
VoltKart Run. No credentials are in this handoff, and none belong in one.

## 2026-10-24 — Review response, Phases A–H (current task)

Worked in `D:/AI-Agent-Testing-Studio`, branch `codex/industry-reliability`. **Nothing was pushed.** The personal origin `Simali2724/AI-Agent-Testing-Studio` was not contacted, and the shared C: publishing checkout was not touched. No provider call was made, no paid evaluation ran, and no saved history was deleted or modified.

### Local commits, oldest first

| Commit     | Scope                                                                                                                                                                   |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `da25d89`  | Restore point: the previously uncommitted T-035 calibration work, plus the litellm import cache (Phase A)                                                               |
| `94a5060`  | Calibration sampling and holdout, dependency locks (T-033), browser coverage (T-036) — Phases B, C, D                                                                   |
| `9db75e3`  | Evaluator provenance (Phase E), redaction and export parity (Phase F), scan phase timings and the benchmark reconciliation (Phase G)                                    |
| `<fourth>` | Selectable extended scenario suite (T-037), measured contrast and shared status wording (T-019), shared-hosting readiness doc (T-038), and the history-picker fix below |

All four commits are local only. Run `git log --oneline -4` for their identifiers.

### What each phase delivered

- **A** — the litellm initialization guard took a global lock and a worker-thread hop on _every_ provider request; it now caches the module behind a double-checked lock and the per-request path never reaches a thread. Four regression tests in `tests/test_costs.py`. The calibration audit found no defect; nothing was rewritten.
- **B** — calibration sampling spreads across Categories by default and can alternate the saved Judge's own passes and failures (disclosed as a changed base rate); freezing can reserve a scenario-level held-out subset; folds report their own denominators while the headline stays the whole sample. `docs/judge-validation.md` is the owner procedure. **No human labels exist**; every Judge reports uncalibrated.
- **C** — `requirements.lock`, `requirements-dev.lock`, `requirements-evaluation.lock` generated by `scripts/lock_dependencies.py` (`uv pip compile --universal --generate-hashes`), consumed with `--require-hashes` by `start.sh`, `run.ps1`, `Dockerfile` and CI. Fixed `requirements-dev.txt`, which demanded `filelock>=4.0.9` against litellm's `filelock<4.0`.
- **D** — `scripts/check-studio-ui.py` covers the current shell in a real browser; CI runs it, installs Linux browser dependencies and keeps failure traces. Eleven unrunnable `check-*.cjs` scripts removed with reasons in PROGRESS.md.
- **E** — each verdict records its actual evaluator; `app/blackbox/judge_provenance.py` derives a per-evaluator view on read. Older records report provenance as unavailable.
- **F** — context-aware redaction keeps public identifiers readable while the specific rules run first; one explanation-provenance block is shared by the JSON, PDF and teammate exports; declarations read "Declaration only" in every mode; the finding review is a keyboard-usable dialog.
- **G** — the benchmark reads its configured tolerance and prints its distribution; scanner phases are timed with preparation separated from scan time. **No concurrency change**: no measurement justified one.
- **H** — `app/studio/scenarios-extended-v1.json` is selectable as the `extended` suite (90 authored scenarios, nine Categories); the screening default is unchanged; Bias keeps its nine subtypes.
- **T-019** — contrast measured with `scripts/check_contrast.py` (43 pairs, 0 failing, 0 skipped after fixing three real failures); `app/blackbox_static/status-labels.js` is the single source of status wording.

### Verification actually run

Windows 11 Home 10.0.26300, Python 3.12.3, project `.venv`. See `docs/verification.md` for the five categories recorded separately, and PROGRESS.md for per-phase commands.

- Full suite: **591 passed, 1 skipped** in 256.80 s (the skip is the Windows symlink privilege case), run with nothing else competing for the machine.
- Clean locked environment: `requirements-dev.lock` installed with `--require-hashes` into a fresh venv outside the repository; 78 packages; `pip check` clean; full suite passed there (476 passed, 1 skipped at that point).
- Browser: `scripts/check-studio-ui.py` and `scripts/check-exact-compare.py` both pass locally in headless Chromium.
- Benchmark: medians 0.828 s, 0.828 s, 0.813 s against a 1.200 s budget.
- Contrast: 43 measured, 0 failing, 0 skipped.
- Ruff lint and format, Prettier, JS syntax, navigation, `scripts/check_docs.py` and `pip check` all clean.

### Known issues and traps

1. **`test_judge_limit_pacing_and_retry_are_shared`** (`tests/test_concurrency.py`) asserts ≥0.24 s between adjacent Judge starts against a configured 0.25 s pause — 4% headroom. It passes in isolation and failed once during a loaded full-suite run. The pacer uses absolute deadlines, so after an event-loop stall two due slots can start together while the average rate stays correct. **The assertion was not weakened.** Treat an isolated failure of this test on a busy machine as a load artifact, and confirm by re-running it alone.
2. **Do not run other pytest sessions while the full suite is running.** Several apparent failures during this task were caused by exactly that; the browser and timing tests are load-sensitive.
3. **New test files must clean up their records.** The shared temporary database made four unrelated tests fail until `tests/test_judge_provenance.py`, `test_export_parity.py` and `test_review_accessibility.py` gained an autouse fixture that deletes the `blackbox` and `assurance` records they create.
4. **`studio_engine.settings_file` now takes an optional `suite`.** Any monkeypatch of it must accept that argument; `tests/legacy_protocol.py` and one lambda in `tests/test_expanded_scenarios.py` were updated for this.
5. **A seeded assurance fixture must be sealed with `service.checkpoint()`.** The review endpoint correctly refuses a record whose findings do not match their audit anchor, so a hand-built record is rejected.
6. `scripts/check_contrast.py` cannot lay the page out. Its `CONTAINERS` mapping of selector to background is part of the measurement and must be kept truthful when the layout changes; an unresolvable colour is reported as skipped and the test requires zero skips.
7. Regenerating the locks needs `uv` in a throwaway environment: `python -m venv /tmp/lockenv`, `/tmp/lockenv/bin/python -m pip install uv`, then `python scripts/lock_dependencies.py --uv /tmp/lockenv/bin/python`. `--check` reports staleness without writing.

### Outstanding external prerequisites

- **Human labels.** Calibration is implemented and tested, but no representative human-labeled sample exists, so every Judge reports **uncalibrated**. Follow `docs/judge-validation.md`. The 53% figure from the earlier smoke test came from fabricated labels and must never be reported as validation.
- **Scanner images and offline databases** on this machine, to measure a real scan before deciding on bounded Gray parallelism (T-028).
- **Native Linux and macOS environments** for launcher, scanner and browser qualification (T-032). A committed CI workflow is not evidence that a remote job ran, and no remote run was observed.
- **A real local Judge (Ollama) or authorised cloud provider** for any live validation. None was called.
- **The owner's decision on shared hosting** (T-038). Recorded as: stay local single-user, which is what the code does. `docs/shared-hosting-readiness.md` is the gap list if that changes.

### Exact startup commands

```powershell
cd D:\AI-Agent-Testing-Studio
.\run.ps1                                  # first run creates .venv and installs the locked set
# or, with an existing environment:
$env:STUDIO_AUTO_RESUME = "0"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2708
```

Studio serves the current shell at `http://127.0.0.1:2708/`; the retained legacy interface stays at `/index.html`. No credentials are in this handoff, and none belong in one.

## 2026-10-23 — T-035 Judge calibration (current task)

Implemented locally in `D:/AI-Agent-Testing-Studio` (branch `codex/industry-reliability`), uncommitted and unpushed. See PROGRESS.md for files, DECISIONS.md for decisions and docs/tasks.md T-035 (In progress: needs owner commit/review and real human-labeled data).

Verified: calibration tests 56 (core 47, API 6, UI 3), related suites 118, navigation 11, Ruff, Prettier, JS syntax and docs checker. Full-suite result: 447 passed, 1 skipped (Windows symlink privilege) in 183 s.

Next steps: review and commit the scoped diff; collect representative human labels and record a validation run with a real local Judge; consider mapping rubric changes for reference-driven categories; verify native macOS/Linux separately (not exercised).

## 2026-10-23 — Published upgrades and runtime evidence correction

## 2026-10-23 — Latest source integration and CI verification

Current request: resolve the pictured historical Ubuntu socket-cleanup failure and push the latest update to AwsomeACES/chatbot-compare/hussain-code. The current test already contains the bounded descendant-resource release fix. It passed on Windows and five consecutive isolated Ubuntu WSL checks. The screenshot predates successful personal-repository runs and the shared c5e461f run; do not rerun an obsolete failed commit expecting new code.

The integrated update was published as c43261c. Its CI exposed a separate random UUID/phone-redaction collision in Gray runtime evidence on Ubuntu (Windows/macOS passed). The follow-up fix in app/assurance/privacy.py preserves only canonical top-level run_id UUIDs, leaving normal PII/secret redaction intact. tests/test_runtime_evidence.py now forces digit-heavy IDs and checks persisted correlation plus malicious non-UUID values. Reproduction failed before the fix; 67 focused tests passed after it. Check the newest GitHub run for the follow-up commit rather than run 39925951369.

D: returned with newer local commits through 740ae4c. Integrated its 30 changed files on top of C:'s shared history, retaining both handoff/progress histories and the prior continuation prompt. All four evidence-readiness commits below are included. D:'s application source was not overwritten or reset. The previous prompt is historical, with a new warning not to rebuild already completed phases. Publication verification results are recorded in the latest PROGRESS entry and final response.

## 2026-10-21 — Evidence readiness and the eight unverified checks (completed implementation phases)

Worked in `D:/AI-Agent-Testing-Studio`, branch `codex/industry-reliability`, local commits only (origin is the personal repo `Simali2724/AI-Agent-Testing-Studio`; nothing was pushed, and the C: publishing checkout was not touched). Commits on top of `0c00e3b`: `6474d5d` (Phase A readiness and guidance), `0c0b7be` (Phase B AST controls and runtime checks), `cb6f0d1` (Phase C explanations and scanner provisioning), and the Phase D commit with the mapping-entry secret qualifier and these docs.

What exists now:

- `app/assurance/readiness.py` + `app/studio/evidence-guidance.json`: preflight (Ready / Needs input / Tool unavailable / Not applicable), stored per run with an audit hash; derived outcome classes and guidance for every Finding; teammate Markdown export (`download?format=teammate`). `POST /api/assurance/preflight`. Results page and PDF show processed, measured, declaration, unverified and review counts.
- `app/assurance/rules/control_worker.py` `controls-v2`: Python `ast` parsing in the scanner container; upstream RateLimitError handlers are not access control; structured observations.
- `app/assurance/runtime_evidence.py`: Gray checks `runtime_tool_permissions`, `runtime_retention`, `runtime_model`, `runtime_timeouts` from run-correlated records; re-evaluated by Attach updated test logs. Record format in `docs/assurance-guide.md`.
- `app/assurance/explain.py`, `POST /runs/{id}/explain`: grounded, metered White explanations; local judges unless per-request cloud consent.
- `scripts/prepare_scanner_data.py` `check` and `scope`.

Server: Studio runs hidden on `http://127.0.0.1:2708/` from the D: venv with `STUDIO_AUTO_RESUME=0`, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`, `STUDIO_SCANNER_WSL_DISTRO=Ubuntu`, `STUDIO_SCANNER_OSV_DATABASE=D:/AI-Agent-Testing-Studio/runtime/scanner-databases/osv-voltkart-421c026122ab`; logs `runtime/logs/20261021-135931-server.*.log`. Check the listener rather than trusting a PID. Ollama was not running.

Saved assessments: `5fc9089d…` (historical, unchanged), `b7df09b7…` (fresh run before the mapping-entry fix), `4da69475-ca0a-42f5-b796-b3560b346115` (final fresh run; see PROGRESS Phase D). Exports: `C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/comparison-reports/voltkart-white-4da69475-{evidence.json,report.pdf,teammate.md}`.

Tests: full suite 386 passed, 1 skipped; navigation 11 passed. New test files: `test_evidence_readiness.py`, `test_source_controls.py`, `test_runtime_evidence.py`, `test_white_explanation.py`, `test_prepare_scanner_data.py`.

Blocked on external inputs (ask only for these): VoltKart's running test endpoint with written permission; two synthetic test users and tool-call logs; expected model and response metadata; retention TTL and a test environment; timeout/retry limits and a provider stub; a lockfile or `pip freeze`; CI workflow files and a run link; a running local Ollama model (or explicit cloud consent) for the AI explanation. Not implemented: built-image/SBOM scanning (unsupported input), Trivy DB provisioning automation, native macOS/Linux qualification, publication to `hussain-code` (needs the user's request and the C: checkout).

## 2026-10-21 — Publication, running Studio and next-AI prompt

Start with [NEXT_AI_PROMPT.md](NEXT_AI_PROMPT.md) for the complete, self-contained continuation request, exact folders, remaining eight-check evidence gaps, phased implementation plan and commands. It is saved in the C: studio-publish checkout. D: disappeared again during the documentation synchronization attempt (Windows: drive D: does not exist), before any new documents were copied there. Keep this C: handoff safe; compare files and sync only when D: returns. Verify server and database availability instead of assuming the previously started D: process remains healthy.

The user subsequently requested publication and startup. Application commit c5e461f was pushed to AwsomeACES/chatbot-compare, hussain-code. [CI run 39557776625](https://github.com/AwsomeACES/chatbot-compare/actions/runs/39557776625) passed Windows, Ubuntu and macOS for that exact commit. D: remains at the equivalent application commit 0c00e3b plus any later handoff documentation commit; its origin still points to the personal repository. Do not push D: directly to the shared branch with unrelated history.

Studio was started from D: on port 2708 with auto-resume disabled. Health and the saved VoltKart Results screen were verified. The only retained assessment was 5fc9089d-ad07-405b-b437-c3a9a2f2e842, the historical White scan; Black history was empty. No new chatbot evaluation was performed. The eight Not tested checks reflect seven limited source-control checks without sufficient evidence and a Trivy scan without a supported target, not judge quota errors. Optional AI source review is qualified and does not overwrite original findings.

The latest user asked how to address those gaps and requested a detailed prompt for another AI, then a Jira summary. This handoff delivery is documentation only; runtime evidence collection, readiness UI and the remaining product changes in NEXT_AI_PROMPT.md are not yet implemented. Do not mistake the Jira summary for acceptance of unfinished work. The application upgrade is published; the new continuation documents have not been pushed.

## 2026-10-21 — Industry reliability upgrade (completed phase)

Verified worktree: C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/studio-publish. Branch: codex/industry-reliability, based on published hussain-code commit 6a2c893. The user reconnected D: on 2026-10-21; D:/AI-Agent-Testing-Studio was clean at 79284a1, and all 23 upgrade files were synchronized and byte-verified there on a new codex/industry-reliability branch. Local configuration, dependencies, runtime history and remotes were preserved. No paid bot evaluations or source uploads are needed.

Implemented and verified; saved as a scoped local commit:

- app/blackbox/comparison_quality.py: paired scenario means, fixed category strata, all-pair Bonferroni adjustment, configurable minimum distinct scenarios, saved tie margin, finite-score validation and review gates. Repeats are not independent samples. Default short suite lacks two independent scenarios in several categories, so it intentionally withholds inferential winners.
- app/blackbox/studio_engine.py and app/studio/settings.json: comparison integration and protocol v5; derived scenarios excluded from independent sample counts.
- app/blackbox_static/simple.js and app/blackbox/reports.py: same comparison evidence and review checks in dashboard/PDF; category ties use saved settings; PDF does not print an unrelated legacy winner.
- app/assurance/white.py: qualify generic model-identifier matches and unresolved OSV versions; retain redacted metadata; no false pass, no uploaded code execution.
- app/assurance/routes.py, service.py, combine.py: verify existing seals before updates, avoid re-sealing corrupt history during recovery/expiry, and block release-ready labels on open reviews. Corrupt records remain explicitly deletable; automatic retention skips them.
- New regression files: tests/test_comparison_quality.py, test_comparison_ui.py, test_source_evidence_quality.py, test_assurance_integrity_guards.py. Existing test_simple_studio.py now correctly expects insufficient scenarios in the default suite.
- docs/comparison-reliability.md documents method/limits. PRD, Architecture, tasks and README reflect the changes; T-011/T-012/T-016 updated.

Final verification: full suite 339 passed, 1 skipped in 112.97 seconds (Windows symlink privilege skip); the existing fixed performance check passed. The 27 focused comparison/report/browser tests and 11 navigation tests passed. Ruff lint and 95-file formatting check, Prettier, 25-file JavaScript syntax, documentation/link checks, pip check and git diff checks passed. Browser setup initially failed because Chromium was missing; installed Chromium and all browser checks then passed. No live provider calls were used.

Environment repair: isolated .venv Python launcher initially exited silently; base Python `-m venv --upgrade .venv` repaired it. Default shell points to missing PowerShell 7; tool commands must specify C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe with login=false. Sandbox loopback socket creation stalls asyncio/TestClient; run tests with require_escalated, not altered product networking. Dependencies installed in this C: checkout, no broken requirements reported.

Next work: this reliability phase is complete and synchronized to D:. Do not repeat completed checks without new changes. Earlier D: hardware failures mean C: remains the verified fallback checkout. Source synchronization does not prove that an already running Studio server has reloaded it. Current user request is improve/continue, not a new explicit push; no GitHub publication was performed for this phase. C: origin is AwsomeACES/chatbot-compare (shared destination hussain-code), while D: origin remains Simali2724/AI-Agent-Testing-Studio; do not push to the wrong repository. No secrets/runtime archives belong in commits. Preserve unrelated branch-only files. Remaining enterprise work: shared-host authentication/authorization, locked dependencies, native platform qualification, human-labeled judge validation, broader representative cases and stronger external audit anchoring.

# AI Agent Studio — current handoff (2026-10-16)

This checkpoint replaces the old accumulated handoff. Historical implementation notes remain in PROGRESS.md and Git. Do not resume old evaluation runs: the user explicitly requested deleting all previous history, and that cleanup is complete.

## Product and current request

Actual product: `D:/AI-Agent-Testing-Studio`, personal repository `Simali2724/AI-Agent-Testing-Studio`, master. Latest starting commit was `4c7c1b7`; inspect status/log before further changes. This task has local uncommitted changes, no push. The user requested a simpler English interface, retaining Black-box testing, White-box testing, Gray-box testing and all other technical terminology; reliable previous/new result selection; and removal of prior test history and generated clutter.

Task staging and original-file backups are outside the product at `C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/simple-ui-refresh`. Its deploy.py checks destination hashes before installing staged changes. Do not run transformation helpers again on already transformed files. No secrets are in these helpers. Never print .env or include it in archives/Git.

## Implemented changes

- `app/blackbox_static/simple.html`, `simple.css`, `simple.js`: three-step Evaluate screen; optional settings collapsed; one repeat count with per-category customization; relevant inputs by selected testing modes; 1–4 bots; concise judge selection with optional model/key controls. Original scoring/categories/consent stay intact. English UI only; original-language prompts and transcripts are intentionally retained. Source ZIP is handled by White-box upload, never executed on host.
- `app/blackbox_static/shell.js`: Evaluate/Results/Governance navigation, unified Previous tests picker, Refresh history, no unrelated automatic old-result selection, assessment/Black child de-duplication, URL and Back/Forward support.
- `app/blackbox_static/assurance.js`: summary counts and actionable findings; technical mode labels; source-only controls; optional exports/actions; stale-response cancellation and generation guards; per-tab cache of up to 10 reports. Black run polling in simple.js has matching abort/latest-response protection. Cached results refresh on selection; explicit refresh remains available.
- `app/blackbox_static/assurance-governance.js`: selection-aware Governance, English labels, no Hinglish toggle.
- `app/database.py`: record_summaries projects selected JSON metadata in SQLite; parameterized property names and paths, validated identifiers. `app/blackbox_app.py` and `app/assurance/routes.py` use it for history lists. Existing transaction durability is unchanged; do not add blind transaction retries on disk I/O errors.
- `tests/test_database.py`, `tests/test_assurance_ui.py`, `tests/test_studio_api.py`, `scripts/test-studio-navigation.cjs`: metadata/types, simple form behavior, unified history, Back/Forward, delayed result race and mobile layout. Tests use isolated synthetic data and make no paid provider calls.
- `README.md`, `docs/simple-guide.md`, `PROGRESS.md`: updated guidance and cleanup record.

## Cleanup and runtime

User authorized clearing ALL prior local history. Removed 33 old evaluation/comparison/archive records, 3 uploaded-project records, and all their usage/audit/execution-cache rows. Preserved cost_meta. Database integrity is OK, compacted to 40,960 bytes. Removed 371 generated files totaling 968,059,034 bytes. PROGRESS.md lists each file. Source, tests, .env, .venv, node_modules, pricing and scanner databases are preserved. runtime/ui-check is still imported by legacy UI verification scripts. Test caches naturally reappear when tests are run.

Studio was restarted on `http://127.0.0.1:2708/` with auto-resume disabled; inspect the current listener instead of relying on an old PID. Current launch uses:

- `STUDIO_AUTO_RESUME=0`
- `STUDIO_SCANNER_WSL_DISTRO=Ubuntu`
- `STUDIO_SCANNER_OSV_DATABASE=D:/AI-Agent-Testing-Studio/runtime/scanner-databases/osv-voltkart-421c026122ab`
- `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`

Logs are in the external staging directory (`studio-20261016-141125.*.log`). Fresh connections read SQLite correctly; the previous long-lived process returned disk I/O errors after earlier drive disruptions. Restarting it restored healthy endpoints. Both history endpoints return empty arrays. No chatbot evaluation is running. API keys remain in Studio's ignored .env; Studio judges do not depend on Reliance's .env. Bot authentication and judge credentials remain separate.

## Verification

13 focused Python tests (database, assurance UI and Studio API) passed, including delayed-old/fast-new result switching. 11 navigation tests and 24 JavaScript syntax checks passed. Live browser confirmed English technical terms, refreshed empty history and navigation. The isolated browser test also checks mobile width. Final cache-eviction guards clear stale evidence on HTTP 404 (deleted/expired tests), and explicit assessment deletion evicts its cache entry. The isolated UI test passed again with that regression; final lint/format results are in PROGRESS.md. No new full-suite or remote-CI claim is made for this UI patch. Prior provider configuration full suite passed 258 with one Windows symlink skip; that is historical, not today's full validation.

Useful focused checks from product root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py tests/test_assurance_ui.py tests/test_studio_api.py -q
node --test scripts/test-studio-navigation.cjs
node scripts/check-js-syntax.cjs
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\ruff.exe format --check app tests
npm run format:check
```

## Known limitations and next steps

No outstanding blocker is known for this requested English/history cleanup. Do not claim that every provider will produce valid judgments during outages: unavailable cases remain Not tested with reasons. Deleting local history cannot delete exports previously shared outside this project. Local dependencies/offline scanner databases are intentionally still large; share a clean source repository, not the whole working folder.

Existing assurance limitations remain: scoped OSV snapshots must cover each new project's packages; the helper for provisioning a scoped snapshot lives outside the repo and is not yet a general setup workflow. Trivy database copying is expensive. Source checks do not prove runtime behavior or the absence of vulnerabilities. Reproduction does not freeze every scanner rule/image/database revision. Context-aware CVE redaction, deeper classifier integration, and broader semantic/control-flow checks remain future work. Do not silently relax the fixed performance benchmark or certify governance mappings. Actual macOS/Linux behavior of this UI patch has not been rerun natively; launchers are unchanged.

If asked to publish: review the scoped diff, run relevant checks, publish the verified current source to the explicitly requested repository and branch, then inspect the NEW workflow run. Re-running a historical failed workflow tests its original commit and does not validate new fixes. Avoid reintroducing old pipx/filelock conflicts; CI must keep isolated virtual environments. Do not start or resume paid evaluations without the user's requested target/run scope.

## Latest task — fresh VoltKart source audit

Assessment 5fc9089d-ad07-405b-b437-c3a9a2f2e842 is completed and should be retained. All six scanners completed, 14 checks processed in 188 seconds: pass3/flag2/exists1/not_tested8. No bot execution or old run resume occurred. API source approval was explicitly granted; all automated review attempts were unusable (format errors/provider error/timeout). Final 14 explanations are explicitly an AI assistant evidence review, not a Gemini/Gemma/Ollama verdict or a human override. Six model-ID secret alerts are false positives; four dependency candidates use unknown 0.0.0 placeholders. Preserve raw findings. Four source observations and qualified interpretations are attached in ai_source_review/source_review_context and audited. Audit integrity is valid. Five provider attempts are metered; known review cost $0.017369 plus one unknown-billing call, total Unknown. No further API calls are needed.

Results displays optional AI review fields in app/blackbox_static/assurance.js, with provenance, escaped strings and known/unknown cost separation. tests/test_assurance_ui.py includes model-output escaping assertions; it passed. Reports in C:/Users/Moinuddeen hussain/Documents/ChatGPT/Moinuddeen_airm/comparison-reports/voltkart-white-5fc9089d-report.html, -evidence.json and -teammate.md. Helper scripts outside the repo are specific to this request and not a general automated White AI-review backend. Changes remain local.

## 2026-10-17 — Current publication destination

The user requested AwsomeACES/chatbot-compare on hussain-code, superseding the earlier personal-remote publication instructions. Five documentation commits and the final checker are complete (docs/tasks.md T-030). The destination has unrelated history: preserve it through a source snapshot commit, never a force-push. Exclude local credentials and runtime artifacts. Verify the resulting remote commit before claiming publication.
