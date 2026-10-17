# AI Agent Studio — Working rules

Purpose: give humans and coding agents a safe, testable way to change this repository.
Owner: AI Agent Studio maintainers; named approving maintainer: TODO: confirm.
Last updated: 2026-10-17.

## Contents

- [Authority and scope](#authority-and-scope)
- [Golden rules](#golden-rules)
- [Coding rules](#coding-rules)
- [Working process](#working-process)
- [Tests and definition of done](#tests-and-definition-of-done)
- [Security and privacy](#security-and-privacy)
- [Extension guides](#extension-guides)
- [Never do this](#never-do-this)

## Authority and scope

Start with [PROGRESS.md](../PROGRESS.md) and [HANDOFF.md](../HANDOFF.md), then the relevant [tasks](tasks.md). Read only implementation needed for the requested work. [PRD](PRD.md) defines intended behavior; [Architecture](Architecture.md) maps current components; [Design](Design.md) records actual screens. New user instructions govern their authorized task; do not treat historical notes as a request to restart old runs or delete new history.

These are contributor rules, not a claim that every legacy function already conforms. A **Finding** is an evidence-backed check result, an **Engine** performs checks, a **Judge** evaluates evidence, a **Run** is a saved assessment, a **Case** is a scenario, and a **Category** groups Cases. An **Assurance badge** describes selected evidence modes, never certification. Changes to these meanings need a recorded decision and migration plan for older saved data.

## Golden rules

1. Black-box tests never read target source. Gray private inputs and White source remain in their own paths; do not leak them into a Black Judge prompt.
2. A check that did not produce sufficient evidence stays **Not tested** with a reason. In the simple Black protocol it contributes zero to the conservative index while measured quality and coverage remain separate. Assurance `Finding.score` remains `None` for `not_tested`; never fabricate a measured zero or silently change historical scoring policies.
3. Unknown usage, price or failed-call billing stays **Unknown**, never $0. Only known zero/no-call/local-API-fee cases may show zero, with hardware-cost limits stated.
4. Private code/log review uses local Judges unless the user explicitly opts in to the specific cloud use. Current White scanning does not call an LLM (large language model); a future review service must preserve that boundary and consent.
5. Never put full credentials in source control, stored settings, reports, logs or audit. Keep saved keys in ignored local configuration and entered keys in the appropriate temporary credential path. Raw submitted archives may contain secrets until retention cleanup: do not claim universal secret removal.
6. Preserve Findings and original evidence when reviewing them. A false-positive review requires a meaningful written reason and an audit entry; missing evidence cannot be overridden into a pass. Whole-Run deletion expressly requested by the owner, or configured retention expiry, is the privacy exception.
7. Repeats are never substituted with another repeat's cached answer. Each distinct repeat and new Run makes fresh bot calls. Resume/re-judging may reuse the checkpoint of the exact same Run, bot, Case, repeat and prompt.
8. Never execute, import, build or install dependencies from an uploaded application on the host. Trusted source scanners are a separate sandbox (restricted process environment). An isolated ZIP application runner remains Planned.
9. Distinguish processed checks, measured results and passes. No amount of retrying guarantees available providers or correct judgments.
10. Keep the UI English and preserve technical terms. Original-language prompts/transcripts are evidence and must not be silently translated. Do not add a Hinglish toggle without a changed user preference.

## Coding rules

- Use focused modules, descriptive names and small functions with one responsibility. Annotate new/changed public inputs and outputs with types; document public functions with short docstrings explaining purpose and important limitations.
- Python uses four spaces and Ruff's configured 100-column style. Ruff is the formatter/linter: a linter detects common code errors. Frontend and Markdown use Prettier, the repository's formatter. Do not hand-minify code or pack statements with semicolons.
- Put Cases, weights, Judge catalogue and prices in editable configuration files identified by [Architecture](Architecture.md). Avoid new hardcoded product thresholds, endpoints or model defaults. Existing hardcoded check registries, intake limits and statistical constants are explicit migration work, not permission to claim everything is configurable.
- Validate external data at API boundaries. API means the application's program-to-program interface. Preserve the actual `Finding` and `Engine` contracts. Use safe structured data rather than evaluating strings as code.
- Keep deterministic checks, provider calls, evidence validation, scoring and presentation separable. Deterministic means a fixed rule rather than an AI judgment.
- Preserve old protocol snapshots and API behavior unless a migration is explicitly part of the task. A snapshot is a saved configuration version used by a Run.
- Escape all untrusted strings rendered in HTML; HTML is browser markup. Do not render provider text with unchecked `innerHTML`. Render stored model explanations literally and test malicious markup as data.
- Keep source-pattern observations distinct from runtime proof. A declared control is `exists`; its effectiveness needs behavioral evidence.
- Reuse existing metering, scheduler and cache layers. Do not add an unmetered SDK (provider library), silent SDK retry or independent concurrency pool.
- Use one server worker with the current in-memory scheduler. Distributed workers require shared admission/rate-limit coordination first.

## Working process

1. Read current progress/handoff and relevant task acceptance criteria. Map files with `rg --files` and `ls`/`Get-ChildItem`; search with `rg`. Do not read `.env` into chat or scan generated dependencies as maintained source.
2. Inspect Git status and existing instructions. Preserve unrelated modifications and user data. Before a large authorized change, make a scoped restore-point commit after reviewing staged files for secrets. Never commit every file blindly.
3. Work in a small phase with targeted edits. Use the project's existing style and dependencies. Do not add cloud calls, provider charges, runtime deletion or publication outside the authorized scope.
4. Run relevant tests and formatting/lint checks. State what was tested, what failed and what was not checked. An available package, adapter or workflow is not proof that a real integration ran.
5. Update [PROGRESS.md](../PROGRESS.md) after each implementation phase with changed behavior, validation and remaining limits. Record lasting choices in [DECISIONS.md](../DECISIONS.md). Update [tasks](tasks.md) when acceptance criteria change status.
6. Commit only intended files. Use short imperative subjects; a `docs:`, `fix:` or `feat:` prefix is a recommended convention, not a configured enforcement mechanism. Use `codex/` for a new agent-created branch unless the user specifies another. This documentation task uses the existing `master` branch; it does not require moving existing work.
7. Do not push merely because a local commit was requested. On an authorized push, check the workflow for the new commit; re-running an old failed job tests the old commit. Branch protection/required-review settings are TODO: confirm.
8. When roughly 5% of context/token capacity remains, or continued work risks losing context, stop coding and write a self-contained [HANDOFF.md](../HANDOFF.md): actual paths, completed changes, commands/results, known bugs, pending consent and exact next steps. Never include keys.

## Tests and definition of done

Use synthetic fixtures (controlled sample inputs) and mocked providers by default. Tests must not start paid evaluations or modify production history. Choose tests that exercise behavior and failure boundaries, not assertions that merely repeat implementation text.

| Change                          | Relevant existing tests / additional required behavior                                                                                                                                                              |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New Engine / Finding / combiner | `tests/test_assurance.py`: selected-mode isolation, prerequisites, evidence validation, missing checks, declaration versus effective control, audit tampering.                                                      |
| Scanner adapter/intake          | `tests/test_scanner_runtime.py`, `tests/test_assurance.py`: path/expansion limits, no source execution, no-network sandbox, missing image/DB, timeout/output bounds, version/provenance.                            |
| Bias/category/scoring           | `tests/test_bias_governance.py`, `tests/test_simple_studio.py`: pair-only differences, randomized order, aggregate not double-weighted, repeat counts, ties/incomplete coverage.                                    |
| Judge/fallback                  | `tests/test_recovery_controls.py`, `tests/test_judge_credentials.py`, `tests/test_governance_recovery.py`: quota/auth failures, local-only discovery, key changes, exact evidence, independent-model agreement.     |
| Cache/resume                    | `tests/test_speed_cache.py`, `tests/test_http_turn_cache.py`: fresh distinct repeats, same-repeat resume, changed prompt/model cache misses, partial conversation preservation.                                     |
| Costs                           | `tests/test_costs.py`: reported/estimated/unknown usage, failed-call billing, batch cost once, separate roles, price snapshots.                                                                                     |
| Concurrency/performance         | `tests/test_concurrency.py`, `tests/test_speed_cache.py`: per-provider limits, lease release, cancellation, speed isolation, fixed benchmark.                                                                       |
| Governance/privacy              | `tests/test_bias_governance.py`, `tests/test_governance_recovery.py`, `tests/test_assurance.py`: hash chain/anchor, reason-required old/new review, deletion/retention, redaction and consent.                      |
| UI/history                      | `tests/test_assurance_ui.py`, `tests/test_studio_api.py`, `scripts/test-studio-navigation.cjs`: current selection wins, deleted report eviction, keyboard/state controls, escaped model output, responsive layouts. |
| Persistence/processes           | `tests/test_database.py`, `tests/test_process_cleanup.py`: durable transactions, handle release and cleanup of only owned child processes.                                                                          |
| Packaging/docs                  | `tests/test_package_release.py`, `scripts/check_docs.py`: clean source export, document existence, requirement traceability and relative links.                                                                     |

The benchmark is `test_standard_suite_runtime_regression_budget` in `tests/test_speed_cache.py`, configured by `app/studio/benchmark.json`. It uses an unmeasured warm-up and median of five simulated runs. The checked baseline is 1.0 seconds and the gate is 1.2 seconds; the test currently multiplies by a literal 1.2 rather than reading the `tolerance` field. A slowdown beyond 20% fails. Do not raise the threshold or remove work to hide failure; profile, fix, or record the failure. This is not an API speed service guarantee.

Typical scoped commands, using the project virtual environment (an isolated dependency installation):

```text
python -m pytest tests/test_assurance.py -q
python -m ruff check <changed Python paths>
python -m ruff format --check <changed Python paths>
node scripts/check-js-syntax.cjs
node --test scripts/test-studio-navigation.cjs
python scripts/check_docs.py
```

Use `.venv/bin/python` on macOS/Linux or `.venv\Scripts\python.exe` on Windows if the environment is not active. Check changed Markdown/JS with the pinned Prettier; `npm run format:check` is the repository-wide check. Do not add tests for a typo-only prose edit. CI (automated repository verification) runs the broader configured suite; see [quality.yml](../.github/workflows/quality.yml).

Definition of done:

- [ ] Requirement IDs and acceptance criteria are identified.
- [ ] Implemented versus Planned boundaries remain truthful.
- [ ] Targeted behavior and error paths pass relevant tests, or an unresolved failure is recorded and the work remains incomplete.
- [ ] Changed files pass formatter/linter, and links/requirement coverage pass the docs checker for document changes.
- [ ] No source execution, secret disclosure, fabricated evidence or silent cost/score substitution was introduced.
- [ ] Existing unrelated modifications and retained history remain intact.
- [ ] UI changes are checked in the browser where available; providers/operating systems not exercised are disclosed.
- [ ] Progress, tasks and applicable decisions/handoff are current.
- [ ] Scoped diff and commit are reviewable; publication happens only within authorization.

## Security and privacy

Confirm ownership or permission before starting tests. Separate consent for bot traffic, Judge review and cloud private-input review. Do not copy another bot's `.env` as Studio's required configuration; use provider-specific Studio settings and masked password fields.

Keep `.env`, credentials, runtime files, caches, `.venv`, `node_modules` and archives out of source commits. Use the allowlisted source packager rather than ZIPing the working folder. PII (personally identifiable information) pattern redaction is only a baseline; context review is needed before sharing.

Provision trusted scanner images/databases outside evaluations. Do not automatically pull images, download model weights, enable scanner networking, mount source writable or open an unauthenticated Docker daemon. For Windows cleanup, resolve and verify exact paths and use one shell end-to-end. Do not recursively delete broad/computed roots. Prefer recoverable backups where deletion is authorized.

Audit hashes detect particular edits against their stored anchor; they are not signatures or immutable external storage. Keep retained audit history append-only. Reproduction cannot promise identical answers from changing external providers. Framework mappings to NIST AI RMF, ISO/IEC 42001 and EU AI Act themes are informational references, not certification or legal findings.

## Extension guides

### Add an Engine

1. Define its scope, inputs and privacy boundary in PRD/tasks first; identify whether it reads code or private declarations.
2. Implement `required_inputs`, `plan`, and asynchronous `run` in `app/assurance/`, returning the real `Finding` schema from `models.py`.
3. Extend mode validation, explicit engine construction/planning in `service.py`, API capabilities and the relevant UI choices. There is no auto-discovered plugin registry.
4. Persist planned checks before dispatch, preserve missing reasons, checkpoint results and route all model calls through metering/governance.
5. Add combined-label behavior only where evidence supports it, then add selected-mode, failure, privacy, resume and schema tests.
6. Update Architecture/Design/tasks and record trade-offs in DECISIONS. Do not describe a new mode as completed before its tests and actual integration limits are recorded.

### Add or change a Category

1. Edit the versioned simple protocol in `app/studio/settings.json` and increment its `protocol_version`; use `bias-v1.json` for Bias content or version it separately.
2. Keep ten default Categories unless a scope change explicitly authorizes more. Add sub-tests without treating derived aggregates or wording variants as independent coverage.
3. Update weights, expected behavior, prerequisites, mappings in `app/studio/governance.json`, and necessary `studio_engine.py`/`bias.py` logic.
4. Preserve saved Run snapshots and keep legacy suites in `app/blackbox/cases/` compatible. Never silently overwrite historical expectations.
5. Test planning, repeat IDs, missing evidence, scoring, comparison, UI labels and exports; add requirement/task references.

### Add a Judge model/provider

1. Add catalogue/credential environment-variable metadata to `app/studio/settings.json`. Model IDs must come from the account or installed model discovery, not invented availability.
2. Use `judge_credentials.py` for endpoint-bound credentials and `metering.completion()` for requests. Add a reviewed adapter only when compatible routing is insufficient.
3. Add price metadata to an editable snapshot/seed or require a user override; otherwise show Unknown. Do not hardcode rates in evaluation code.
4. Keep local/private flags, allowed fallback order, family identification and model discovery explicit. Never change the bot model when its Judge fails.
5. Test malformed output, unsupported quotes, quota/auth errors, local fallback, switches, cache invalidation, costs and audit; use actual provider tests only within authorized scope.

## Never do this

- Turn Not tested into Passed merely to reach 100% completion.
- Call a scanner false positive a confirmed exposed secret after evidence disproves it.
- Treat dependency version `0.0.0` placeholders as verified installed vulnerable versions.
- Claim a code declaration proves authorization, logging, retention or guardrail effectiveness.
- Reuse one repeat for another, silently alter a saved protocol, or compare incompatible Judge panels as a confident winner.
- Hide unknown cost, retry outside metering, or claim a planning estimate is an invoice.
- Erase an alert instead of recording a reasoned review; erase history without the user's authorized deletion/retention scope.
- Claim all integrations work because libraries import or old CI screenshots show green checks.
- Bypass a sandbox restriction with host execution, disable a failing test to obtain green CI, or publish unrelated local changes.
