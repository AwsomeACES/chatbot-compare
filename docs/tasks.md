# AI Agent Studio — Delivery tasks

Purpose: connect product requirements to verified code and explicit remaining work.
Owner: AI Agent Studio maintainers; named task owners: TODO: confirm.
Last updated: 2026-10-17.

## Contents

- [Next 5 tasks](#next-5-tasks)
- [Status and sizing](#status-and-sizing)
- [Phase 0 — Black-box fixes](#phase-0--black-box-fixes)
- [Phase 1 — Shared Finding and Engines](#phase-1--shared-finding-and-engines)
- [Phase 2 — Gray-box](#phase-2--gray-box)
- [Phase 3 — White-box](#phase-3--white-box)
- [Phase 4 — Combiner and labels](#phase-4--combiner-and-labels)
- [Phase 5 — Dashboard](#phase-5--dashboard)
- [Phase 6 — Governance](#phase-6--governance)
- [Phase 7 — Speed and cache](#phase-7--speed-and-cache)
- [Phase 8 — Tests and documents](#phase-8--tests-and-documents)
- [Phase 9 — Packaging](#phase-9--packaging)
- [Known bugs and limitations](#known-bugs-and-limitations)
- [Parking lot](#parking-lot)

## Next 5 tasks

These are proposed next implementation tasks, not work performed by this documentation request.

1. **T-011:** stop model identifiers from becoming credential alerts without weakening real-secret detection.
2. **T-012:** distinguish unresolved dependency versions from confirmed vulnerable installed versions.
3. **T-017:** show prerequisites and applicability before users start scans.
4. **T-016:** reconcile winner-confidence wording/statistics and historical Category tie settings.
5. **T-013:** build a reusable, consent-aware White AI explanation service with honest provider failure handling.

## Status and sizing

**Done** means the scoped code or document exists with the stated evidence, not universal integration success. **In progress** means started but acceptance is incomplete. **Todo** means remaining implementation or validation, even where a partial path exists. **Blocked** names an external prerequisite. Unchecked items are unfinished. No live provider calls, full regression suite or operating-system qualification were run for this document audit.

P0 means correctness/privacy blocker; P1 means important product work; P2 means follow-up. S/M/L are relative small/medium/large effort estimates, not promised durations. Dependencies name prerequisite task IDs. Acceptance criteria describe the completion check. Terms Finding, Engine, Judge, Run, Case, Category and Assurance badge follow [PRD](PRD.md#terms-and-scope); file responsibilities are in [Architecture](Architecture.md#components), screens in [Design](Design.md), and workflow in [Rules](Rules.md).

## Phase 0 — Black-box fixes

- [x] **T-001 — Done · P0 · M:** recover Judge failures with permitted local alternatives. **Files:** `app/blackbox/judge_recovery.py`, `studio_engine.py`, `studio_routes.py`; `tests/test_recovery_controls.py`, `test_judge_credentials.py`. **Requirements:** FR-08, FR-09, NFR-03. **Acceptance:** quota/auth identity is recorded, installed-only fallback is bounded, credential changes are accepted without changing the target bot. **Dependencies:** none. **Evidence:** panel/recovery/discovery code and regression tests exist; real provider availability remains external.

- [x] **T-002 — Done · P0 · M:** resume retained work without replaying completed conversations. **Files:** `app/blackbox/runner.py`, `execution_cache.py`, `studio_routes.py`; `app/assurance/service.py`; `tests/test_http_turn_cache.py`, `test_governance_recovery.py`. **Requirements:** FR-17, NFR-02. **Acceptance:** compatible same-repeat checkpoints are reused, changed experimental inputs are rejected, unrecoverable web sessions retain a reason. **Dependencies:** T-025. **Evidence:** current keys, turn checkpointing and resume validation; no claim that absent credentials or deleted inputs are recoverable.

- [x] **T-003 — Done · P0 · M:** keep unknown bills and measured quality honest. **Files:** `app/blackbox/metering.py`, `pricing.py`, `cost_summary.py`, `studio_engine.py`; `tests/test_costs.py`. **Requirements:** FR-10, NFR-02. **Acceptance:** unknown failed-call billing stays Unknown, bot/evaluation roles remain separate, missing evidence contributes zero only to the conservative index. **Dependencies:** none. **Evidence:** attempt ledger and index/quality separation inspected.

- [x] **T-004 — Done · P1 · S:** display low scored coverage explicitly. **Files:** `app/blackbox/studio_engine.py`, `app/blackbox_static/simple.js`; `tests/test_simple_studio.py`. **Requirements:** FR-12, FR-18. **Acceptance:** Categories with fewer than half of planned outcomes scored show Low confidence and the denominator. **Dependencies:** T-003. **Evidence:** backend flags and UI label exist; confidence is not a calibrated probability.

## Phase 1 — Shared Finding and Engines

- [x] **T-005 — Done · P0 · M:** establish selected-mode planning and shared Finding validation. **Files:** `app/assurance/models.py`, `service.py`, `black.py`, `gray.py`, `white.py`; `tests/test_assurance.py`. **Requirements:** FR-05, FR-07, FR-17, NFR-02. **Acceptance:** selected Engines plan before execution, missing inputs create Findings, non-missing verdicts require evidence, duplicate mode selections are rejected. **Dependencies:** none. **Evidence:** contracts and explicit engine map inspected.

- [ ] **T-006 — Todo · P2 · M:** externalize remaining product constants and strengthen typed plans. **Files:** `app/assurance/models.py`, `intake.py`, `gray.py`, `white.py`; `app/studio/settings.json`; `app/blackbox/studio_engine.py`. **Requirements:** NFR-06. **Acceptance:** configurable values have validated defaults; existing snapshots still load; plan types catch missing fields without changing historical behavior. **Dependencies:** T-005, T-016. **Current gap:** check registries, intake bounds and some scoring/benchmark constants remain in Python.

## Phase 2 — Gray-box

- [x] **T-007 — Done · P1 · L:** implement private-input targeted checks. **Files:** `app/assurance/gray.py`, `intake.py`, `privacy.py`; `app/studio/gray-v1.json`; `tests/test_assurance.py`. **Requirements:** FR-05, FR-06, NFR-03. **Acceptance:** system rules, tools, knowledge, config and logs generate scoped checks; missing prerequisites are explicit; no private cloud Judge is used without opt-in. **Dependencies:** T-001, T-005. **Evidence:** required inputs, policy-rule expansion and local-only filtering inspected. This does not prove tool execution permissions from a verbal answer.

- [x] **T-008 — Done · P1 · M:** correlate logging evidence to a fresh synthetic canary. **Files:** `app/assurance/gray.py`, `privacy.py`, `routes.py`; `tests/test_assurance.py`. **Requirements:** FR-06, FR-14. **Acceptance:** only logs matching the current Run can score canary logging; later logs can be attached; stale logs do not pass a fresh Run. **Dependencies:** T-007. **Evidence:** correlated log and canary attachment paths exist.

- [ ] **T-009 — Blocked · P1 · M:** validate optional HHEM/Qwen classifiers with reviewed installed weights. **Files:** `app/blackbox/local_metrics.py`, `classifier_runtime.py`; `app/studio/settings.json`; `tests/test_assurance.py`, `test_speed_cache.py`. **Requirements:** FR-06, NFR-01. **Acceptance:** real offline inference runs within bounds; missing models stay Not tested; report classifier provenance and measured limitations. **Dependencies:** T-007; blocker: approved local weights and suitable validation hardware/data are not established. **Current gap:** adapters exist, default configuration disables them.

## Phase 3 — White-box

- [x] **T-010 — Done · P0 · L:** provide bounded, read-only source scanners. **Files:** `app/assurance/white.py`, `sandbox.py`, `intake.py`, `rules/`; `app/studio/scanners.json`; `tests/test_scanner_runtime.py`, `test_assurance.py`. **Requirements:** FR-02, FR-07, NFR-04. **Acceptance:** 14 planned source checks use trusted tools without executing uploaded code; missing tools/databases and unsupported output produce explicit Findings. **Dependencies:** T-005. **Evidence:** sandbox/parse paths exist; six real tools ran in the recorded Windows/WSL VoltKart audit. This is not native cross-platform qualification.

- [ ] **T-011 — Todo · P0 · M:** reduce credential false positives using source context. **Files:** `app/assurance/rules/gitleaks.toml`, `white.py`; `tests/test_assurance.py`, `test_scanner_runtime.py`. **Requirements:** FR-07, FR-13, FR-15. **Acceptance:** the six observed model-ID strings are not represented as verified keys; real credential fixtures still alert; old Findings remain reviewable with originals retained. **Dependencies:** T-010. **Current gap:** attached source review qualifies the alert, but generic scanner behavior still needs regression-backed correction.

- [ ] **T-012 — Todo · P0 · M:** qualify dependency advisories when installed versions are unknown. **Files:** `app/assurance/white.py`, `sandbox.py`; `tests/test_scanner_runtime.py`, `test_assurance.py`. **Requirements:** FR-07, FR-13, FR-18. **Acceptance:** `0.0.0`/unresolved requirements cannot be labeled confirmed installed vulnerabilities; real locked vulnerable and unaffected fixtures are distinguished; report requests a lockfile or resolved inventory. **Dependencies:** T-010. **Current gap:** the VoltKart report required additional review to qualify four advisory candidates.

- [ ] **T-013 — Todo · P1 · L:** make White AI explanation a product feature. **Files:** `app/assurance/service.py`, `routes.py`, `privacy.py`; `app/blackbox/judge.py`, `metering.py`; `app/blackbox_static/assurance.js`; `tests/test_assurance.py`, `test_assurance_ui.py`. **Requirements:** FR-08, FR-09, FR-10, FR-13, NFR-03. **Acceptance:** explicit private-source consent, bounded redacted excerpts, strict check-ID/evidence validation, permitted local fallback, no invented successful verdict after parse failure, audited provenance and every attempt metered. **Dependencies:** T-001, T-003, T-010. **Current gap:** optional UI fields exist; the latest review used external helpers and AI assistant review, not a reusable successful provider pipeline.

- [ ] **T-014 — Todo · P1 · M:** productize offline scanner/database readiness and provisioning guidance. **Files:** `app/assurance/sandbox.py`, `routes.py`; `app/studio/scanners.json`; `docs/assurance-guide.md`; planned `scripts/prepare_scanner_data.py` (does not exist). **Requirements:** FR-07, FR-18, NFR-05. **Acceptance:** dependencies outside an OSV snapshot's package coverage are clearly blocked; hashes are verified; no update occurs inside the networkless scan; setup explains disk/time requirements. **Dependencies:** T-010. **Current gap:** project-scoped OSV preparation was done with helpers outside this repository.

## Phase 4 — Combiner and labels

- [x] **T-015 — Done · P1 · M:** combine evidence without inventing causal links. **Files:** `app/assurance/combine.py`, `models.py`; `tests/test_assurance.py`. **Requirements:** FR-11, FR-12, FR-14. **Acceptance:** declarations alone never establish effective defense; selected modes determine Basic/Standard/Full/Custom; missing evidence remains visible. **Dependencies:** T-005. **Evidence:** exact label conditions inspected. Release recommendations remain scoped engineering summaries.

- [ ] **T-016 — Todo · P0 · M:** align winner confidence and Category tie handling with their saved protocol. **Files:** `app/blackbox/studio_engine.py`, `app/blackbox_static/simple.js`; `tests/test_simple_studio.py`, `test_exact_multijudge_compare.py`. **Requirements:** FR-11, FR-17. **Acceptance:** choose and document the statistical resampling unit; method and displayed label agree; repeats do not inflate independent evidence; Category ties use the Run's saved tie margin; incompatible panels/coverage withhold the overall winner. **Dependencies:** T-003. **Current gap:** backend samples Category differences under a scenario-cluster label; Category UI reads current settings for its tie margin. Per-Category winners themselves already exist.

- [ ] **T-017 — Todo · P1 · M:** preview readiness and applicability across all selected Engines. **Files:** `app/assurance/models.py`, `routes.py`, `service.py`, `white.py`; `app/blackbox_static/simple.js`, `assurance.js`; `tests/test_assurance.py`, `test_assurance_ui.py`. **Requirements:** FR-18, NFR-02, NFR-07. **Acceptance:** before start, each check shows Ready, Needs input, Tool unavailable or Not applicable with a reason; completed versus measured counts stay separate; absence of source-pattern evidence is not treated as runtime proof. **Dependencies:** T-005, T-014. **Current gap:** plans/prerequisite reasons exist, but no complete shared applicability model or status panel.

## Phase 5 — Dashboard

- [x] **T-018 — Done · P1 · L:** present evaluation, comparison, evidence and cost in one English shell. **Files:** `app/blackbox_static/simple.html`, `simple.css`, `simple.js`, `shell.js`, `assurance.js`; `app/database.py`; `tests/test_assurance_ui.py`, `test_database.py`, `test_studio_api.py`; `scripts/test-studio-navigation.cjs`. **Requirements:** FR-01, FR-03, FR-04, FR-11, FR-12, FR-13, NFR-07. **Acceptance:** 1–4 bots, ten Categories with repeat controls, paired Bias evidence, Category winner/tie column, costs and reliable history selection are reachable. **Dependencies:** T-003, T-005. **Evidence:** current source plus focused tests recorded in PROGRESS; no new full browser qualification performed for these docs.

- [ ] **T-019 — Todo · P1 · M:** unify status copy and make review/accessibility controls consistent. **Files:** `app/blackbox_static/simple.js`, `assurance.js`, `assurance-governance.js`, `simple.css`; `tests/test_assurance_ui.py`; `docs/Design.md`. **Requirements:** FR-12, FR-15, FR-18, NFR-07. **Acceptance:** Gray declarations do not say Found in code; Not tested/Estimated/Low confidence have consistent text; review form is keyboard-usable; glossary is accessible on focus; contrast is measured against the agreed standard. **Dependencies:** T-017, T-022. **Current gap:** mixed raw statuses, browser dialogs, partial tooltips and no full accessibility audit.

- [ ] **T-020 — Todo · P1 · M:** bring optional AI review into every supported report export. **Files:** `app/assurance/routes.py`, `service.py`; `app/blackbox/reports.py`; `tests/test_assurance.py`. **Requirements:** FR-13, FR-16. **Acceptance:** JSON and PDF retain original Findings, AI source/provenance, failure qualifications and unknown costs; redaction tests cover both. **Dependencies:** T-013, T-024. **Current gap:** the shareable VoltKart HTML was external; do not claim that its explanation is already in the product PDF.

## Phase 6 — Governance

- [x] **T-021 — Done · P0 · M:** retain tamper-evident provenance and model interpretation. **Files:** `app/blackbox/governance.py`, `governance_routes.py`, `bias.py`, `studio_engine.py`; `app/studio/governance.json`; `tests/test_bias_governance.py`, `test_governance_recovery.py`. **Requirements:** FR-14. **Acceptance:** hash-linked events and database anchor are checked; prompts/config/price/model identities are recorded; same-family warnings and distinct-model agreement appear. **Dependencies:** T-005. **Evidence:** chain and model-card source inspected; not a signed external audit service.

- [x] **T-022 — Done · P0 · M:** preserve originals during human review and support explicit privacy controls. **Files:** `app/assurance/routes.py`, `service.py`; `app/blackbox/studio_routes.py`, `governance.py`; `tests/test_assurance.py`, `test_bias_governance.py`. **Requirements:** FR-15, FR-16, NFR-03. **Acceptance:** review reason required, original preserved, missing evidence cannot become a pass; configured retention/deletion removes scoped private records; overrides remain visible. **Dependencies:** T-021. **Evidence:** review and retention endpoints inspected; append-only history applies only while a Run is retained.

- [ ] **T-023 — Todo · P1 · M:** strengthen reproducibility beyond saved application settings. **Files:** `app/assurance/service.py`, `sandbox.py`, `routes.py`; `app/blackbox/governance.py`; `tests/test_assurance.py`, `test_governance_recovery.py`. **Requirements:** FR-14, FR-17. **Acceptance:** record and validate reproducible scanner rule/image/database fingerprints and returned model revisions; clearly distinguish same configuration from identical external behavior. **Dependencies:** T-014, T-021. **Current gap:** current reproduction does not freeze every external revision and may require deleted input re-upload.

- [ ] **T-024 — Todo · P1 · M:** improve context-aware export redaction. **Files:** `app/assurance/privacy.py`; `app/blackbox/governance.py`; `tests/test_assurance.py`, `test_bias_governance.py`. **Requirements:** FR-16, NFR-03. **Acceptance:** regression fixtures retain public vulnerability IDs while masking real credentials/contact data; missing contextual coverage is disclosed; source/audit hashes remain meaningful. **Dependencies:** T-022. **Current gap:** broad phone matching can mask public advisory IDs and does not comprehensively identify names/addresses.

## Phase 7 — Speed and cache

- [x] **T-025 — Done · P0 · M:** cache exact completed work without reusing distinct repeats. **Files:** `app/blackbox/execution_cache.py`, `judge.py`, `connectors.py`; `tests/test_speed_cache.py`, `test_http_turn_cache.py`. **Requirements:** FR-03, FR-17, NFR-01, NFR-02. **Acceptance:** new repeat/new Run gets fresh bot calls; same-repeat resume reuses stored turns; changed Judge/prompt/transcript misses verdict cache. **Dependencies:** none. **Evidence:** actual key fields and checkpoint writes inspected.

- [x] **T-026 — Done · P1 · L:** bound concurrent traffic and batch compatible Judge requests. **Files:** `app/blackbox/scheduling.py`, `judge_batch.py`, `runner.py`, `studio_engine.py`; `tests/test_concurrency.py`, `test_speed_cache.py`. **Requirements:** FR-08, FR-09, NFR-01. **Acceptance:** active leases honor strictest provider limit, backoff/stop closes resources, invalid batches fail closed, batch bills are not duplicated. **Dependencies:** T-003, T-025. **Evidence:** gate and strict-batch code/tests exist; distributed scheduling is not implemented.

- [ ] **T-027 — Todo · P1 · M:** revalidate the fixed benchmark and reconcile its configuration. **Files:** `tests/test_speed_cache.py`; `app/studio/benchmark.json`; `app/blackbox/scheduling.py`; `app/database.py`; `docs/verification.md`. **Requirements:** NFR-01, NFR-06. **Acceptance:** run the same work with warm-up and median-of-five measurement; fail above baseline × 1.2; never raise baseline to hide a regression; make the declared tolerance and test agree. **Dependencies:** T-026. **Current gap:** historical passing and failing host measurements both exist; current revision/host performance is not verified in this documentation task, and the test uses a literal 1.2.

- [ ] **T-028 — Todo · P2 · M:** assess bounded Gray parallelism and scanner preparation cost. **Files:** `app/assurance/service.py`, `gray.py`, `sandbox.py`; `tests/test_assurance.py`, `test_scanner_runtime.py`. **Requirements:** NFR-01, NFR-02. **Acceptance:** any optimization preserves all checks, deterministic plan accounting, bounded memory and stop behavior; timings separate provisioning from scans. **Dependencies:** T-026, T-027. **Current gap:** mode jobs overlap, Gray checks and White tools/bots within a mode run serially; Trivy database copies are expensive.

## Phase 8 — Tests and documents

- [x] **T-029 — Done · P1 · M:** maintain isolated automated quality checks. **Files:** `.github/workflows/quality.yml`; `tests/`; `scripts/check-js-syntax.cjs`, `test-studio-navigation.cjs`, `check-exact-compare.py`, `process_cleanup.py`. **Requirements:** NFR-06. **Acceptance:** CI creates a project-only Python environment, runs lint/format/navigation/regression checks and cleans up owned UI processes on each configured OS. **Dependencies:** none. **Evidence:** configured Windows/Ubuntu/macOS matrix and test files inspected; latest remote run outcome is not asserted here.

- [x] **T-030 — Done · P1 · M:** deliver a truthful cross-linked documentation set and validator. **Files:** `docs/PRD.md`, `Architecture.md`, `Design.md`, `Rules.md`, `tasks.md`; `AGENTS.md`, `CLAUDE.md`; `scripts/check_docs.py`; `PROGRESS.md`. **Requirements:** FR-01, FR-02, FR-03, FR-04, FR-05, FR-06, FR-07, FR-08, FR-09, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-17, FR-18, NFR-01, NFR-02, NFR-03, NFR-04, NFR-05, NFR-06, NFR-07. **Acceptance:** five documents exist, source-backed features have paths, Planned work is labeled, every requirement has an implementation/validation task, relative links resolve, files pass formatting, one commit per primary document, progress lists mismatches. **Dependencies:** inspection of T-005, T-010, T-018, T-021. **Evidence:** five individual documentation commits; documentation/link checker passed; six checker tests passed; documentation formatting passed. Remaining implementation gaps are tracked separately.

## Phase 9 — Packaging

- [x] **T-031 — Done · P1 · M:** provide local launchers and optional container hosting. **Files:** `start.sh`, `run.ps1`, `scripts/open_browser.py`, `Dockerfile`, `compose.yaml`, `README.md`. **Requirements:** NFR-05. **Acceptance:** launcher creates environment/install/browser setup, checks Ollama without downloading models, serves Studio; Docker hosts Studio without executing uploads. **Dependencies:** none. **Evidence:** launcher and container source inspected; native qualification is separately T-032.

- [ ] **T-032 — Blocked · P1 · M:** verify native macOS/Linux startup and scanner setup. **Files:** `start.sh`, `Dockerfile`, `compose.yaml`, `docs/verification.md`; `tests/test_scanner_runtime.py`. **Requirements:** FR-01, FR-07, NFR-05. **Acceptance:** fresh-machine startup, browser system dependencies, local Judge discovery, container permissions and White scanners work on each target OS with recorded commands/results. **Dependencies:** T-014, T-031; blocker: native target environments and reviewed scanner/model provisioning are not available in this task. CI unit tests alone do not satisfy this item.

- [ ] **T-033 — Todo · P1 · M:** lock supported Python dependencies and verify clean installation. **Files:** `requirements.txt`, `requirements-dev.txt`, `requirements-evaluation.txt`; planned dependency lockfile (format/path TODO: confirm); `.github/workflows/quality.yml`, `Dockerfile`. **Requirements:** NFR-05, NFR-06. **Acceptance:** resolve a supported version set and transitive dependencies, validate platform installation and provider adapters, document update procedure. **Dependencies:** T-029. **Current gap:** package-lock.json pins Prettier, while most Python runtime dependencies remain ranges.

- [x] **T-034 — Done · P0 · S:** distribute source without local secrets or generated data. **Files:** `.gitignore`, `.dockerignore`, `scripts/package_release.py`; `tests/test_package_release.py`; `README.md`. **Requirements:** NFR-03, NFR-04, NFR-06. **Acceptance:** source export allowlist excludes `.env`, dependencies, runtime, caches and nested archives, validates output and avoids overwrite. **Dependencies:** none. **Evidence:** packaging implementation/tests exist. No new release ZIP or GitHub push is part of this documentation task.

## Known bugs and limitations

Source-inspected or recorded issues, not newly reproduced exploits:

| Issue                                                   | Evidence / affected interpretation                                                                                                     | Follow-up                          |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| Model IDs flagged as secrets                            | Latest VoltKart audit/source review: six identifiers; original scanner alerts remain.                                                  | T-011                              |
| Unresolved versions treated as vulnerability candidates | Latest VoltKart OSV findings used `0.0.0`; cannot claim installed vulnerabilities.                                                     | T-012                              |
| White AI automation failed for the latest sample        | Gemini/Gemma structured-output failures, provider failure and invalid/timeout local replies; final explanations were assistant review. | T-013                              |
| Resampling label differs from implementation            | `studio_engine.summarize()` samples Category score differences while saying scenario-cluster.                                          | T-016                              |
| Category tie display uses live settings                 | `simple.js` uses `settings.tie_margin`; historical Run snapshot may differ.                                                            | T-016                              |
| Declaration wording is source-specific                  | `exists` maps to Found in code even for Gray inputs.                                                                                   | T-019                              |
| “Not tested” groups different reasons                   | Missing inputs/tools, unsupported targets and insufficient source evidence share one verdict. Not all require a live bot to improve.   | T-017                              |
| Partial reproducibility/redaction                       | External revisions are not all frozen; pattern redaction can mask public IDs or miss contextual PII.                                   | T-023, T-024                       |
| Performance history is mixed                            | Progress includes a fixed-gate failure and later fixes; do not infer the current benchmark result.                                     | T-027                              |
| Historical handoff text says history empty              | Later audit section retains a completed assessment; earlier empty-history statement describes cleanup time only.                       | T-030 documentation reconciliation |

## Parking lot

- **Planned:** isolated uploaded-application execution. Needs a separate threat model and containment design; never substitute host execution. Supports the unbuilt portion of FR-02.
- **Planned:** distributed scheduling, signed/external audit anchoring and hosted multi-user authentication. Current local single-process boundaries remain.
- **Planned:** deeper source/control-flow analysis. Existing text scans cannot prove absence or effectiveness of controls.
- **Planned:** a comprehensive glossary, dark theme and refined review queue. See NFR-07 and Design; no new navigation pages are automatically required.
- **Planned only after preference change:** Hinglish UI toggle. English-only remains the active preference; language-test prompts retain their original content.
- **TODO: confirm:** named owner/reviewer, usability target, accessibility standard/device matrix, intended winner resampling unit and Python lockfile format. These decisions do not block documenting today's code.
- Promptfoo, blind arena and automatic deployment gates are not required by this documentation task. Reuse current components unless a future scoped decision justifies more infrastructure.
