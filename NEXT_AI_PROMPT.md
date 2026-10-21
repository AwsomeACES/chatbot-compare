# Continue AI Agent Studio: evidence readiness and the eight unverified checks

Prepared for the next coding AI on 2026-10-21, Asia/Calcutta. This is a self-contained continuation prompt. Read it, verify the current files, then implement the next small phase. Do not restart the project or simply repeat a proposal.

Latest environment update: D: disappeared again while saving this handoff. Windows reported that drive D: does not exist. This document and the updated HANDOFF/PROGRESS files are saved in the C: studio-publish checkout only; their synchronization to D: is pending. Start from C: if D: is still absent. The application upgrade had already been synchronized to D: and published successfully before this new disconnection. The previously running D: server may now be unable to read its files; verify health and stored-result endpoints before relying on it.

## 1. My request to you

Continue my existing AI Agent Studio. Make it clear why a check cannot be verified, supply practical ways to collect the missing evidence, and implement trustworthy runtime checks where the current Studio only scans text. Start with the eight unverified checks in the saved VoltKart White-box report below. Preserve the simple English UI and the technical terms Black-box testing, Gray-box testing and White-box testing.

My goal is evidence-backed results that a non-technical user can understand and give to a teammate. I do not want fabricated passes, hidden skips, misleading vulnerability claims, or repeated API calls that cost money without producing evidence. A completed scan is different from a measured result or a passed test. Explain what is a Studio limitation, what information is missing from the target bot, and what is an actual confirmed defect.

Work in phases. Read only relevant files, map with `rg --files` and directory listings, make targeted edits, and run relevant tests. Continue useful implementation with mocked services if a live endpoint or external service is unavailable. Ask only for the specific missing external input when needed. Keep progress updates short.

## 2. Exact folders, branches and Git destinations

Primary product folder:

```text
D:\AI-Agent-Testing-Studio
```

Healthy fallback and publishing checkout:

```text
C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\studio-publish
```

Both are currently on `codex/industry-reliability`. At the handoff's preparation, the last application-code commits were:

- D: `0c00e3b` — `feat: harden comparison evidence and assurance integrity`.
- C: `c5e461ff72ffb7c5d4cec3245f46fc5ada3615fa` — same 23 upgrade files, different repository history.
- The upgrade files were compared against the old baseline, copied to D: and verified byte-for-byte. Both working trees were clean before these handoff documents were added. Inspect status/log again; later documentation commits may exist.
- C: `origin` is `https://github.com/AwsomeACES/chatbot-compare.git`.
- Requested shared destination: `https://github.com/AwsomeACES/chatbot-compare/tree/hussain-code`.
- The application upgrade `c5e461f` WAS pushed to `hussain-code` on 2026-10-21. The older HANDOFF section saying no push describes an earlier point in the task.
- D: `origin` remains the personal repository `https://github.com/Simali2724/AI-Agent-Testing-Studio.git`. Do not accidentally push there.
- C: and D: do not share the same Git history. Do not force-push D: onto the shared repository, reset either tree, or copy `.git` between them. Use the verified C: publishing history for future authorized publication; compare changed source files before synchronization and preserve unrelated branch-only files.
- This new handoff does not authorize publishing future changes automatically. Finish and validate locally, then report the commit and ask for a push only if it has not been requested for that work.

D: previously disconnected and returned fatal hardware errors. It was reconnected successfully for the application synchronization and startup, then disappeared again during this documentation save. Continue in C: while it is unavailable. Compare changes before any later synchronization and do not claim D: contains these new documents until verified. C: is a fallback source checkout; do not assume it has D:'s credentials or saved results.

## 3. Read first, in this order

Paths below are relative to `D:\AI-Agent-Testing-Studio` unless an absolute path is shown. Use equivalent paths under the C: fallback if needed.

1. `AGENTS.md` and `docs/Rules.md`.
2. This `NEXT_AI_PROMPT.md`, the newest section of `HANDOFF.md`, and the latest `PROGRESS.md` entries. Old progress sections describe history, not current requests to delete or resume runs.
3. Relevant tasks in `docs/tasks.md`, especially T-013, T-014, T-017, T-019 and T-020.
4. `docs/Architecture.md`, `docs/assurance-guide.md`, `docs/comparison-reliability.md`; read PRD/Design sections only for the part you change.
5. Inspect `git status`, branch and remote before editing. Preserve unrelated changes and make a scoped restore point before a substantial implementation phase. Never stage `.env`, runtime evidence, archives or installed dependencies.

The task register currently contains 34 named items: 21 Done, 11 Todo and 2 Blocked. This is NOT a meaningful percentage of engineering effort. The “Next 5 tasks” introduction and some historical limitation wording in `docs/tasks.md` are stale: T-011, T-012 and T-016 are already implemented and tested. Reconcile those summaries, not the completed implementation. T-027's broader configuration reconciliation remains open even though the current fixed benchmark passed.

## 4. What already works — preserve it

- FastAPI backend and plain HTML/CSS/JavaScript frontend; this is not a Streamlit or React rewrite task.
- Unified Evaluate / Results / Governance navigation, previous-test picker, stale-response guards and English technical labels.
- One to four bots through existing supported chat/web, REST or OpenAI-compatible connectors. Uploaded source ZIPs are inspected; they are not automatically launched as applications.
- Ten default Black-box categories, configurable repeats, Bias sub-tests with paired evidence, weighted summaries and bot/judge cost separation. Legacy suites remain for compatibility; do not delete referenced files just to reduce size.
- Multi-provider judges, permitted local fallback, bounded retries/timeouts, provider concurrency, run checkpoints, caches and UI judge changes. Changing the judge must never silently change the bot under evaluation.
- Exact same-run/case/repeat checkpoints can be reused on resume; a new repeat or new run must make a fresh bot call.
- Gray-box private-input checks, run-correlated synthetic canary logs, source-only White-box scanners, findings with evidence, review notes and audit history.
- Human review preserves the original result and requires a reason. An unverified check cannot be overridden into a fabricated pass.
- Token/cost metering with Unknown for missing usage, prices or uncertain billing. No-call bot cost can be zero; local API charges being zero does not mean hardware is free.
- `start.sh`, `run.ps1`, optional Docker hosting and a three-platform GitHub Actions workflow using an isolated Python environment. Docker hosting is not an uploaded-code execution sandbox.

The latest reliability upgrade also added:

- `app/blackbox/comparison_quality.py`: paired scenario means, fixed category strata, all-pair confidence adjustment, saved tie margins, minimum distinct scenarios, measured-score validation and review gates. Repeats are not independent evidence.
- `app/blackbox/studio_engine.py` integration and `app/studio/settings.json` protocol v5. Derived Bias aggregate observations do not inflate independent sample counts.
- Dashboard/PDF comparison parity in `app/blackbox_static/simple.js` and `app/blackbox/reports.py`.
- Narrow source-context qualification for model names incorrectly detected as secrets, while real credential-shaped/provider-specific matches still alert.
- Qualification of OSV placeholder/unresolved versions. Unknown versions cannot establish a confirmed installed vulnerability or a clean dependency pass.
- Existing assurance seals are verified before review, retention, canary or judge updates. Recovery/expiry does not silently re-seal corrupt evidence. Explicit owner deletion remains possible.
- Unresolved review items prevent a launch-ready label.

The short default suite has too few distinct scenarios in some categories for an inferential winner. The new code deliberately withholds a winner in that situation. Do not “fix” it by weakening the gates or counting repeated prompts as independent scenarios; add reviewed distinct scenarios through the existing protocol mechanism if needed.

## 5. Validation already completed

Full local regression at the application upgrade: **339 passed, 1 skipped**, 112.97 seconds. The skip was Windows symlink privilege. The existing fixed performance threshold passed unchanged. Also passed: 27 focused comparison/report/browser checks, 11 navigation checks, Ruff lint and 95-file formatting check, Prettier, 25-file JavaScript syntax checks, documentation/link checks and `pip check`.

Remote CI for the exact published code commit passed Windows, Ubuntu and macOS:

```text
https://github.com/AwsomeACES/chatbot-compare/actions/runs/39557776625
```

That verifies the CI test workflow, not every native scanner installation, Docker integration, `start.sh` path or real model provider. Do not claim those separate integration tasks are complete.

New regression files worth preserving:

```text
tests/test_comparison_quality.py
tests/test_comparison_ui.py
tests/test_source_evidence_quality.py
tests/test_assurance_integrity_guards.py
```

## 6. The actual saved VoltKart result

Studio was started from D: on 2026-10-21 and opened at:

```text
http://127.0.0.1:2708/
http://127.0.0.1:2708/?assessment=5fc9089d-ad07-405b-b437-c3a9a2f2e842#results
```

Check the current listener and health endpoint before starting another server. Do not rely on an old process ID or interrupt an active evaluation without checking it.

Saved assessment ID: `5fc9089d-ad07-405b-b437-c3a9a2f2e842`.
This is the historical VoltKart White-box scan from 2026-10-16, NOT a new scan using the latest code. All six scanner tools completed; all 14 planned checks were recorded in approximately 188 seconds:

- 3 limited scanner passes: `unsafe_patterns`, `python_security`, `prompt_injection_paths`.
- 2 original scanner flags: `hardcoded_secrets`, `dependency_vulnerabilities`.
- 8 unverified checks listed below.
- 1 declaration: `endpoint_controls`; this does not prove that access control works.

The original raw summary still says “Do not launch.” Separate AI assistant source review qualifies the two flags: six matches in `providers.py` assign model identifiers, not demonstrated leaked keys; four OSV candidates use `0.0.0` placeholders, not confirmed deployed versions. The new parser fixes apply to fresh scans; no historical findings were silently rewritten.

The endpoint-control match was a provider `RateLimitError` handler. Catching an upstream quota error does not prove inbound request limiting, authentication or session ownership.

Latest history inspection found this one saved assurance run and no saved Black-box runs. Earlier history was deleted at the user's explicit request. Do not invent missing Reliance results or restart historical runs.

Historical cost: 0 target-bot calls and $0 bot API cost; review usage 37,429 tokens, including estimates; $0.017369 known metered review cost, plus one call with unknown billing, so total review cost remains Unknown. Gemini/Gemma/Ollama automated explanation attempts failed validation or availability; no provider verdict was accepted. The current narrative is labeled **AI assistant source review**, not a successful automated provider judgment.

Input ZIP, still present when this handoff was written:

```text
C:\Users\Moinuddeen hussain\Downloads\voltkart-ai-chatbot-main.zip
```

Recorded ZIP SHA-256:

```text
421c026122ab66168fb67d661a2f67b8b262dce2d6cac0c2288d7ffb3f5c8e0e
```

Recompute the hash before treating a later ZIP as identical. Uploaded runtime inputs were deleted under the configured retention policy; use a fresh intake of the original ZIP for a new scan. Do not alter retention or resurrect deleted private data silently.

Existing shareable artifacts, outside the repository:

```text
C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\comparison-reports\voltkart-white-5fc9089d-report.html
C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\comparison-reports\voltkart-white-5fc9089d-evidence.json
C:\Users\Moinuddeen hussain\Documents\ChatGPT\Moinuddeen_airm\comparison-reports\voltkart-white-5fc9089d-teammate.md
```

## 7. Why eight checks are unverified, and what would fix that

These were processed, not silently skipped. Trivy completed without a supported versioned target. Seven control checks completed their limited text scan without enough matching evidence. None of these eight statuses was caused by judge API quota. Another API key, a longer timeout or rerunning the same ZIP alone cannot supply the missing evidence.

| Check ID                    | Current evidence gap                                                                               | Required implementation or evidence                                                                                                                                                                                                                                                                                                       |
| --------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `container_vulnerabilities` | Trivy returned no supported dependency/container target for a vulnerability verdict.               | Accept and validate supported versioned inventory/lockfiles with a compatible scanner. If adding SBOM or supplied-image support, explicitly implement and test that adapter. Do not claim arbitrary image intake already exists or build an uploaded Dockerfile on the host. Distinguish a filesystem dependency scan from an image scan. |
| `guardrail_path`            | No matching control path established by limited source rules.                                      | Parse relevant source declarations safely; use a running authorized endpoint and defined policy for allowed/disallowed request tests. Link matching behavioral evidence without promoting a source declaration into a pass.                                                                                                               |
| `tool_permissions`          | Tool handlers/order ID/phone checks do not demonstrate authenticated ownership or least privilege. | Validate declared tool policy, then test authorized/unauthorized synthetic principals on an isolated fixture or approved test endpoint. A bot saying “I cannot do that” is not proof that no tool executed. Require execution/authorization evidence.                                                                                     |
| `pii_logging`               | No deployed log/redaction evidence.                                                                | Reuse the existing synthetic canary chat and upload logs captured afterward with the same run ID. Evaluate only correlated supplied records; absence in a partial log is not proof about all logging paths.                                                                                                                               |
| `retention`                 | Source review showed in-memory sessions and manual reset, but no verified automatic expiry.        | Read explicit retention/TTL configuration and verify deletion/expiry of synthetic session data in a controlled fixture or authorized test environment. Configuration alone stays a declaration. Do not delete real customer sessions.                                                                                                     |
| `model_config`              | Existing rule mainly looks for a `latest` alias; it is not a general model-access validator.       | Validate expected provider/model configuration and compare to actual response or correlated trace model metadata. Missing metadata stays unverified; do not guess a model from answer style. Use existing Gray model-drift support where applicable.                                                                                      |
| `timeouts_retries`          | Error handling or an SDK default does not prove bounded end-to-end behavior.                       | Use controlled slow/429/5xx test services to measure deadlines, bounded retries, cancellation and backoff. Unit fixtures can validate Studio; evidence about VoltKart must come from VoltKart's actual path, clearly distinguished.                                                                                                       |
| `ci_safety`                 | ZIP rules did not establish relevant CI-safety evidence.                                           | Inspect supplied workflow/configuration and exact-commit run evidence where authorized. Parsing YAML is not proof that checks ran; report scanner/test scope. Studio's green CI does not prove VoltKart's CI or safety.                                                                                                                   |

Source review also raised session ownership, request/message/history/session limits, dependency locking and provider availability for the teammate. These are qualified source observations, not all proven exploits. Do not modify the teammate's bot merely to make Studio's test pass unless explicitly asked.

## 8. Where to implement the fix

All paths in this map are under `D:\AI-Agent-Testing-Studio` (or the equivalent C: checkout):

| Area                                                         | Existing files                                                                                                                 |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Finding, Evidence, Assessment and Engine contracts           | `app/assurance/models.py`                                                                                                      |
| Planning, execution, checkpoints, retention and exports      | `app/assurance/service.py`                                                                                                     |
| Upload/repository intake, run/review/resume/canary endpoints | `app/assurance/routes.py`, `app/assurance/intake.py`                                                                           |
| White check registry and scanner-output interpretation       | `app/assurance/white.py`                                                                                                       |
| Trusted scanner isolation and offline databases              | `app/assurance/sandbox.py`, `app/studio/scanners.json`, `Dockerfile.scanners`                                                  |
| Limited current control detector                             | `app/assurance/rules/control_worker.py`                                                                                        |
| Other source rules                                           | `app/assurance/rules/gitleaks.toml`, `semgrep.yaml`, `bandit.yaml`                                                             |
| Gray checks, log correlation, private judge filtering        | `app/assurance/gray.py`, `app/assurance/privacy.py`, `app/studio/gray-v1.json`                                                 |
| Black bridge and combined interpretation                     | `app/assurance/black.py`, `app/assurance/combine.py`                                                                           |
| Connectors, scheduling, attempt metering and cache           | `app/blackbox/connectors.py`, `scheduling.py`, `metering.py`, `execution_cache.py`                                             |
| Judge evidence validation, credentials and fallback          | `app/blackbox/judge.py`, `judge_credentials.py`, `judge_recovery.py`, `studio_engine.py`                                       |
| Simple UI and navigation                                     | `app/blackbox_static/simple.html`, `simple.js`, `simple.css`, `shell.js`                                                       |
| Assurance results and governance UI                          | `app/blackbox_static/assurance.js`, `assurance-governance.js`                                                                  |
| Protocol, judges, weights and prices                         | `app/studio/settings.json`, `app/pricing/seed.json`, existing pricing modules                                                  |
| Audit and persistence                                        | `app/blackbox/governance.py`, `governance_routes.py`, `app/database.py`                                                        |
| Source intake/parser/isolation regression tests              | `tests/test_assurance.py`, `test_scanner_runtime.py`, `test_source_evidence_quality.py`                                        |
| Integrity and UI tests                                       | `tests/test_assurance_integrity_guards.py`, `test_assurance_ui.py`, `test_studio_api.py`, `scripts/test-studio-navigation.cjs` |

Actual `Finding.verdict` values are `pass`, `fail`, `not_tested`, `exists`. Not tested forces `score=None` and low confidence; other verdicts require evidence. `Finding.details` exists for structured metadata. Do not introduce a new verdict such as `not_applicable` without a deliberate schema, scoring, export, UI and backward-compatibility decision. A separate preflight applicability/readiness field is likely safer.

Existing API paths include `/api/assurance/capabilities`, `/inputs/{kind}`, `/runs`, `/runs/{id}`, `/runs/{id}/resume`, `/runs/{id}/reproduce`, `/runs/{id}/review`, `/runs/{id}/canary-logs`, `/runs/{id}/judges`, `/runs/{id}/retention` and `/runs/{id}/download`; all are under `/api/assurance`. Inspect method/schema before use. There is no `app/assurance/plan.py`; planning currently lives in Engines and service code.

## 9. Recommended implementation phases

### Phase A — truthful preflight and actionable missing evidence

Prioritize T-017 and relevant T-019 changes. Add typed, config-driven prerequisite/readiness information for each selected check. Show Ready, Needs input, Tool unavailable or Not applicable before execution, each with a specific reason and next action. Ready means eligible to attempt, not guaranteed pass. Unsupported evidence still needs a recorded reason after a run. Do not classify an inconvenient or failing check as Not applicable merely to improve the score.

The result page must separately show processed, measured/pass/fail, declarations, unverified and human-review counts. For historical reports, display the original verdict and supplemental explanation; never retroactively invent an attempted runtime check. Replace generic “install a tool” guidance when the tool actually ran but evidence was missing.

Provide a concise teammate-facing export listing each unresolved check, required input, owner action and next test. Keep existing simple navigation and collapse maintainer settings. Add useful UI/error-state tests, including escaping and stale-result selection.

### Phase B — stronger evidence collection and bounded runtime validation

Safely improve source analysis where it can establish declarations: Python AST parsing and structured configuration/workflow parsing, without imports, eval or target execution. A `RateLimitError` handler must not be mislabeled as authentication; a model alias is not a key; source absence is not whole-system absence.

Reuse Gray/Black connectors, synthetic canaries, scheduling and metering for behavioral checks. Add explicit evidence correlation between bot, run, check, response/tool action and configuration. Implement controlled fixtures for permissions, expiry, model metadata and timeout/retry behavior. Keep product tests of Studio separate from tests of a real target bot. Do not claim all eight can become measured from source alone.

Add lockfile/inventory parsing and a tested scanner path for supported formats. Do not install dependencies or build images from the uploaded application on the host. New image/SBOM support requires an explicit isolated adapter; until implemented, show it as unsupported input, not a supported upload option.

### Phase C — productize White AI explanations and scanner readiness

T-013 is NOT finished: the saved VoltKart narrative came from helper-assisted AI source review. Existing UI support for `ai_source_review` does not mean a reusable provider pipeline exists.

Implement a bounded reusable explanation service through existing metering and permitted judge fallback. Require exact check IDs, valid output schema, grounded excerpts and model provenance; retain parse failures and Unknown billing. Source explanations are separate from original scanner verdicts and human overrides. Default private review to local models. Previous permission covered specific redacted VoltKart excerpts sent to Gemini; do not generalize it to all private repositories, other providers or future arbitrary uploads.

T-014 needs scanner/database readiness and a maintainable offline provisioning workflow. `scripts/prepare_scanner_data.py` is a planned path, not an existing script. Validate hashes and package coverage. A VoltKart-scoped OSV snapshot cannot silently cover unrelated dependencies. Network/database preparation stays outside the networkless scan.

### Phase D — demonstrate the result honestly

After tests pass, create a NEW VoltKart White assessment using the actual ZIP and latest code. Preserve the old report. Verify tool readiness before launching; a real scan may still legitimately produce unverified checks. Use the new runtime tests against the actual bot only when its working endpoint, access and safe test fixtures are available. The old localhost VoltKart address from earlier chats is not proof that it is running today.

Request only missing inputs that cannot be inferred: current endpoint/connection fields, approved synthetic test accounts/tools, expected model, correlated logs, retention behavior, dependency inventory and CI evidence. Do not ask the user to paste secrets into chat; use the existing Studio password fields or ignored `.env`. Complete mock-based implementation even if external inputs block live verification.

Deliver a new run link and plain-English report with exact counts, measured coverage, original evidence, AI explanation provenance, bot/judge tokens and known/unknown costs. Do not guarantee 100% passes or universally available providers. Account for every planned check with an honest outcome/reason.

## 10. Environment, credentials and running the app

Studio judge settings live in `D:\AI-Agent-Testing-Studio\.env`; safe field documentation is `.env.example`. They are independent of the chatbot's own provider credentials. Do not restore the obsolete dependency on `D:/reliance-project/backend/.env`.

Supported configured judge fields include `STUDIO_JUDGE_PROVIDER`, provider-specific keys/models, `GEMMA_MODEL`, `OLLAMA_MODEL`, and optional `STUDIO_JUDGE_URL`, `STUDIO_JUDGE_MODEL`, `STUDIO_JUDGE_API_KEY`. Discover actual available models; do not assume a named model is installed or funded. Read credential variable names/status only; never print or commit values. Previously pasted chat keys must not be copied into the handoff or source.

Current launch used these non-secret process settings:

```text
STUDIO_AUTO_RESUME=0
PYTHONUTF8=1
PYTHONDONTWRITEBYTECODE=1
STUDIO_SCANNER_WSL_DISTRO=Ubuntu
STUDIO_SCANNER_OSV_DATABASE=D:/AI-Agent-Testing-Studio/runtime/scanner-databases/osv-voltkart-421c026122ab
```

Disabling auto-resume prevents old interrupted evaluations making fresh requests simply because Studio starts. Runtime/history remains under `D:\AI-Agent-Testing-Studio\runtime`; current server logs are in `runtime\logs`. Do not delete these to fix a UI or evidence problem.

The working Windows shell is:

```text
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
```

Use it explicitly with login disabled if the tool's default PowerShell 7 path is missing. The D: venv successfully imported Uvicorn during the last startup. The C: venv launcher had previously been repaired with base Python `-m venv --upgrade .venv`; do not repeat repairs unnecessarily.

Start manually only if the port is free and no active run needs preservation:

```powershell
Set-Location -LiteralPath 'D:\AI-Agent-Testing-Studio'
$env:STUDIO_AUTO_RESUME = '0'
$env:PYTHONUTF8 = '1'
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2708
```

The normal Windows launcher is `powershell.exe -ExecutionPolicy Bypass -File .\run.ps1`; macOS/Linux use `./start.sh`. Keep both supported. Use a hidden window for a background Windows service. Check `/api/health` and the visible results screen afterward.

Some agent sandboxes stall asyncio/TestClient loopback socket creation. If tests hang at socket creation, use the tool's properly approved local execution permission; do not weaken application networking or disable the failing tests. In the verified C: environment, Node is `C:\nvm4w\nodejs\node.exe`; use it explicitly if Node is absent from PATH. Chromium was provisioned for Playwright. Keep runtime dependencies out of Git.

## 11. Testing and acceptance

Select relevant tests first, adding regression tests for actual new behavior:

```powershell
Set-Location -LiteralPath 'D:\AI-Agent-Testing-Studio'
& .\.venv\Scripts\python.exe -m pytest tests/test_assurance.py tests/test_source_evidence_quality.py tests/test_scanner_runtime.py tests/test_assurance_integrity_guards.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_assurance_ui.py tests/test_studio_api.py -q
& .\.venv\Scripts\python.exe -m ruff check app tests scripts sample_project
& .\.venv\Scripts\python.exe -m ruff format --check app tests scripts sample_project
npm run format:check
npm run check:js
npm run test:ui
& .\.venv\Scripts\python.exe scripts/check_docs.py
```

After new behavioral changes pass focused checks, run the appropriate full regression and fixed benchmark before publication. Do not rerun broad tests repeatedly without changes or failures. Use synthetic fixtures and no provider calls in tests. Do not lower benchmark thresholds, skip failing platforms, or bypass evidence validation to get green results.

Acceptance for the eight-check improvement:

1. Every selected check has a clear prerequisite/readiness reason before execution and a recorded outcome afterward.
2. The UI distinguishes a finished scanner with insufficient evidence from a tool failure, an unattempted request and a confirmed target defect.
3. Source declarations are not behavioral passes; no-match text searches do not prove a missing control.
4. Tests cover valid and missing/malformed inputs, real and false-positive source patterns, exact/unresolved versions, stale/unrelated logs, unauthorized tool operations in safe fixtures, timeout bounds and model metadata mismatch.
5. Existing history/audit seals remain valid; override reasons and original findings remain visible; mixed Black/Gray/White evidence cannot be attached to the wrong bot/run.
6. Costs include every actual attempt and keep missing billing Unknown. Provider changes are logged and never mutate the tested bot silently.
7. Exports include the same qualified explanation and missing-evidence guidance as the UI, without private credentials or unsafe HTML.
8. A fresh demonstration uses a new run ID and records exact code/input/tool/database versions. Clearly state any checks still blocked by external inputs or unimplemented adapters.

## 12. Remaining industry work and how to finish the handoff

After the eight-check work, the tracked backlog still includes typed/config-driven plans (T-006), reviewed HHEM/Qwen weights and validation (T-009), export parity (T-020), stronger reproduction (T-023), context-aware PII redaction including over-redacted public vulnerability identifiers (T-024), benchmark configuration reconciliation (T-027), bounded Gray parallelism (T-028), native startup/scanner qualification (T-032), and Python dependency locking (T-033).

Shared-host authentication/roles/tenant isolation, distributed scheduling, signed/external audit anchors, independent human-labeled judge evaluation, broader reviewed scenarios and isolated uploaded-application execution are separate future work. Do not claim the local Studio is enterprise-certified or that CI passes prove model judgment accuracy.

Update PROGRESS.md after each phase and record lasting decisions in DECISIONS.md. Keep docs/tasks.md truthful. Commit only intended files locally; do not push to the wrong remote. At roughly 5% remaining context/token budget, stop implementation and write an updated HANDOFF.md with exact paths, commits, tests, active server state, blockers and next actions. Never include keys. Leave the next AI a concrete starting point rather than an unexplained partial rewrite.
