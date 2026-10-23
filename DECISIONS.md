# Current engineering decisions

Audited for Ticket 89 on 2026-10-13. This register describes the active application.
Historical notes are preserved in [the archive](docs/decision-history.md); they are
not current verification claims. Capability gaps have explicit acceptance criteria
in [BACKLOG.md](BACKLOG.md).

## Maintainable source and automated checks

Use pinned Ruff 0.14.1 for Python formatting, four-space indentation, import
sorting, undefined/unused-name checks and invalid/packed-statement checks. Use
Prettier 3.6.2 for maintained frontend files and documentation. Development tools
are separate from runtime requirements.

`EvaluationExecutor` owns one run's state. Discovery, quality workers, sequential
speed checks, progress persistence and cleanup are named methods. Public
`execute()` remains compatible. `build_cases()` delegates selection, normalization
and judge prerequisites to separate helpers. Long plain literals were split with
an AST-equivalence check; prompt content was preserved.

The Windows GitHub Actions workflow runs format/lint, JavaScript syntax, pytest
and isolated browser checks. Local success is distinct from a hosted CI result:
GitHub runs the workflow after publication. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the code map and reproducible commands.

## Black-box boundary and permissions

The active entry point is `app.main` -> `app.blackbox_app`. Evaluation uses REST,
OpenAI-compatible, SSE or browser conversations, never source-code scoring.
ZIPs are stored but never executed on the host. A virtual environment is not a
sandbox; isolated ZIP execution is task MAINT-01.

Target-message, judge-sharing and performance permissions remain explicit.
Missing permissions fail before network preparation. Authentication, ambiguous
widget detection and connection errors have explicit failure paths.

Evidence: `tests/test_easy_setup.py` and `tests/test_blackbox_upgrade.py`, including
real local REST, compatible-API, browser, HTTP-error, SSE and ZIP fixtures. These
tests do not certify arbitrary external chatbots.

## Quality and evidence coverage

Ticket 81 supersedes the original missing-evidence-zero policy. Quota, timeout,
judge, connection and prerequisite errors remain `not_tested` with null scores.
Measured zero scores remain failures. Category quality averages evaluated cases;
overall quality equally weights categories with evidence. Coverage is evaluated
cases divided by planned cases and is shown separately.

Ranking requires the configured coverage threshold in every category (80% by
default). Comparisons use jointly evaluated cases with valid pair judgments.
Missing evidence is never a loss or tie. Historical retrieval normalizes missing
scores without rewriting transcripts.

Evidence: `tests/test_coverage_scoring.py` and `tests/test_reference_free.py`.

## Case provenance and prerequisites

Imports take priority over built-in scenarios. Usable uploaded facts replace
generic hallucination probes; references are not cycled to fill a count.
Reference-free probes assess unsupported claims and uncertainty, not all factual
knowledge. Synthetic identifiers are not assumed globally nonexistent.

The core suites have 46 authored scenarios. Remaining legacy scenarios are
labeled; extra wording variations require opt-in and are not independent coverage.
Cases record provenance, rubric and prerequisites. Scope and business correctness
still need supplied expectations. Preview allows unavailable categories to be
excluded before execution. Further authored-case expansion is task MAINT-04.

Evidence: `tests/test_curated_and_evidence.py`, `tests/test_reference_free.py` and
`app/blackbox/cases/README.md`.

## Exact checks, judges and evidence

Explicit required/forbidden strings and canaries support deterministic checks.
They do not understand semantic equivalence or negation. Combined scores use the
minimum of exact and primary rubric scores. Exact failure survives judge errors;
exact success cannot replace missing semantic judgment. AI scores remain estimates.

Evidence matching normalizes Unicode, whitespace, quotes, dashes and case.
Ellipses require substantial ordered fragments and bounded gaps. At least one
supported quote is required; partial matches are flagged for review. A verdict
with no supporting quote gets one metered retry, then fabricated evidence is rejected.

Optional second-judge sampling is seeded and requires a different declared family,
different model and separate consent. Its results are diagnostic: report sample
denominator, pass/fail agreement and absolute difference. Family labels are
operator declarations; agreement is not proof of correctness.

Evidence: `tests/test_curated_and_evidence.py` and
`tests/test_exact_multijudge_compare.py`.

## Comparison and baselines

Continue the Studio with 2–4 targets instead of merging products in this change.
All target pairs use identical cases. AI pair judgments randomize and swap answer
order; disagreement is disclosed. Exact failure can override AI preference.

Winner confidence uses paired net-win bootstrap (2,000 resamples), equal category
weight, at least 10 distinct scenarios and pair-count adjustment. Template variants
are clustered. Insufficient coverage or intervals spanning zero mean no confident
winner. Intervals are exploratory and conditional on the selected case set.

Baselines are explicit immutable snapshots. Protocol hashes reject incompatible
comparisons; shared coverage gates descriptive regression alerts. Blind arena and
automatic release gates are task MAINT-05.

Evidence: `tests/test_exact_multijudge_compare.py` and the isolated
`scripts/check-exact-compare.py` browser check.

## Concurrency and timing

Defaults: four case workers, four conversations per target host, four judge calls
and three active runs. Browser conversations are capped at two. The strictest
active host limits and pacing apply across evaluations in one event loop.
HTTP sessions/cookies and histories are isolated per conversation. One Uvicorn
worker is required; distributed scheduling is outside current scope.

Speed checks are globally exclusive and sequential while other Studio traffic
waits. Timing starts after pacing. External traffic and machine load remain
uncontrolled. Sequential-speed summaries are separate from concurrent latencies.

Cancellation, budgets and deadlines preserve completed evidence and close tasks,
clients and scheduling leases. Progress saves are coalesced at 500 ms with a final
save. SQLite contexts commit/rollback and explicitly close connections.

Evidence: `tests/test_concurrency.py` and interruption tests in `tests/test_costs.py`.
Ticket 87's prior 3.14x timing result is synthetic, not a new chatbot benchmark.

## Costs, secrets and source distribution

Calls have attempt-level metering. Unknown billing stays unknown, not zero.
Reported usage, tokenizer counts and text estimates have separate provenance.
Prices use immutable snapshots and decimal arithmetic. Target and evaluation
costs are separated; hidden bot-internal model/tool traffic cannot be recovered
without telemetry. Reservations include in-flight calls. Budget control limits
dispatch, not the provider's bill; requests already sent may still incur cost.
Secondary-judge interruption preserves completed primary evidence.

Stored settings redact secrets. The source exporter uses an allowlist, credential
checks, private-file exclusions, limits, ZIP validation and no-overwrite publication.
Quality/development files are now included. Explorer ZIPs do not honor `.gitignore`.
The user reported the exposed key revoked; provider-side revocation was not tested
as part of this maintenance work. No new key or paid provider call is needed here.

Evidence: `tests/test_costs.py` and `tests/test_package_release.py`.

## Disposition of historical open checks

| Earlier item                                        | Current disposition                                                                                                                                                           |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Interrupted dependency install                      | Replaced by current environment audit: `pip check` passes and core tests exercise runtime imports. Old installation logs are historical.                                      |
| Connector fixture tests                             | Implemented in `test_blackbox_upgrade.py` and included in the full suite. External compatibility is task MAINT-03.                                                            |
| Evaluator, UI and report verification               | Regression tests, report export tests and isolated comparison browser checks provide current evidence; see `docs/verification.md`.                                            |
| Optional engines and model integration              | DeepEval, DeepTeam, Garak and Transformers are absent in the audited environment. Torch alone does not establish integration. Task MAINT-02 requires actual engine execution. |
| Isolated ZIP execution                              | Deliberately unavailable; task MAINT-01, with no host-execution fallback.                                                                                                     |
| Universal 30-case count and missing-evidence zero   | Superseded by explicit/imported scenarios and the quality/coverage policy above.                                                                                              |
| Historical live model/provider/benchmark statements | Preserved as historical notes, not evidence from this change. Task MAINT-03 defines repeatable external validation.                                                           |

Verification results are recorded in [docs/verification.md](docs/verification.md).
Formatting code does not establish an unimplemented capability.

## Visible controls, quota recovery and expanded suite — 14 October 2026

- The user's newer instruction removes the $5 cap for this run. Budget controls
  remain available, and unknown billing is never converted to zero.
- UI provider selection targets the judge; it does not silently replace the bot
  under test. Kimi model discovery succeeded, but its chat request was rejected
  for insufficient API balance. Its key was not saved. OpenAI/DeepSeek endpoint
  options use the compatible adapter; live account checks await supplied keys.
- Gemini 3.5 Flash Lite timed out in a direct probe. Gemini 2.5 Flash answered the
  direct probe in 1.27 s and the actual Reliance product query in 2.64 s with usage.
  Reliance's non-secret model setting is now 2.5 Flash. Old-model results remain
  in their original run; they were not merged into the new-model benchmark.
- The expanded suite retains every imported row: 79 hallucination (including 49
  supplied rows), 30 for each of 14 other categories, 10 functional checks = 509.
  Preserve provenance: template variations and mock reference facts are disclosed.
- Judge retries are bounded and individually metered. Target rate-limit recovery
  preserves failed observations and waits 60 s, at most twice. Performance has
  no automatic replay; its observed error/latency remains a real speed sample.
- Complete saved transcripts are reused on judge-only retries. Primary judge
  changes are logged. Such runs require mixed-judge interpretation, not silent
  claim of comparability. No existing user run was deleted during verification.
- Gemini-compatible usage reconciliation accounts for total-token gaps as thought
  tokens only for Gemini models; ordinary OpenAI-inclusive totals are not doubled.
  Regression tests cover both forms. Native token-count reference:
  https://ai.google.dev/gemini-api/docs/generate-content/thinking
- Local retrieval now has a 12 s deadline and embedding HTTP attempts are bounded;
  existing keyword fallback remains. The full bot answer uses a separate deadline.
- A full live run encountered provider rate limits, so throughput is deliberately
  reduced. Complete live coverage remains a runtime outcome, not a software-test
  claim. Follow-up task: add provider-account-wide pacing shared with instrumented
  bot internals and an optional provider quota preflight.

## Account quota exhaustion — 14 October 2026

- Direct provider diagnostics identified a daily Gemini quota, not only burst
  throttling: HTTP 429, 20 requests per day for the selected model, about 21.5
  hours until retry. The newly supplied key reported the same exhausted quota.
  Changing a key does not necessarily change project-level quota. Neither new
  credential was saved by these checks; the Kimi account reported no balance.
- Account/billing or daily exhaustion pauses dispatch with `provider_limit`.
  Messages are fixed safe text; provider error bodies and keys are not exposed.
  Existing scores and complete transcripts are retained for resume. Transient
  rate limits still have bounded retries. Slow mode cannot bypass a daily cap.
- The live run remains partial: 5 scored of 509. A separate diagnostic was
  attached to explain the stop; no case score or transcript was modified.
- Incomplete judge JSON gets one bounded retry with a larger output allowance;
  both attempts are metered. No fabricated judgment substitutes for a failure.

## 2026-10-14 — Simple ten-case Studio

- New default screen separates chatbot connections from judge selection and defaults to three repeats of ten authored scenarios. Older datasets/API routes remain compatible at /index.html.
- New protocol uses a worst-case missing-evidence index requested by the user, and keeps measured quality and coverage separate. Historical runs retain their original measured-quality policy.
- Winners require complete evidence and a positive scenario-cluster interval against every opponent. Repeats are not treated as independent coverage. Weights and tie margin are editable and snapshotted.
- Use existing LiteLLM/metering/connectors instead of adding Promptfoo. Claude uses LiteLLM Anthropic conversion; Google Gemma retains the existing native adapter for compatibility.
- Local fallback is explicit, never an automatic model download or unauthorized cloud data transfer. An unavailable chatbot provider is independent of judge availability.
- Persist exact judge prompts and a versioned protocol snapshot. Model identifiers do not guarantee an immutable upstream revision; provider identifiers are retained when returned.
- No ZIP host execution. Optional Docker hosts the Studio only. TASK: implement an isolated ZIP runner with resource/network limits and consent.
- VERIFIED: offline scoring, fallback, live update, override, crash-recovery, cost and concurrency tests; formatter/linter and shell syntax. TASK: native Mac/Linux/Docker execution and real-model integration when providers are usable.

## 2026-10-15 — simplify the Studio into one interface

- Use one static application shell with Evaluate, Results and Governance views. Advanced settings are collapsed controls inside Evaluate, avoiding a second setup experience. Keep the legacy interface reachable for historical protocols; redirect existing governance bookmarks while preserving the run ID.
- Keep current evaluation drafts when viewing saved results. Reusing a saved configuration is an explicit action; matching target settings are required before resuming with entered credentials. Navigation and refresh must not start or reproduce an evaluation.
- Prioritize score, coverage, category comparison, cost and evidence. Insert transcript bodies when a category is opened, preserving expanded evidence on refresh. Keep raw audit, timing and framework details expandable; scoring and governance API contracts remain unchanged.
- Verified: 25 focused Python regressions and 9 executable navigation tests passed; all 22 JavaScript files parsed, Prettier and Ruff checks passed. Browser confirmed bookmark compatibility, saved-run switching, draft preservation, lazy transcripts and refresh. Historical scores/costs were displayed without new paid calls. UI changes require a browser reload, not a backend restart.

## 2026-10-15 — optional gray/white assurance

- Latest request supersedes the earlier black-only restriction: keep the Black engine and add opt-in Gray/White plug-ins. Source is read, never executed. A ZIP is not a running bot.
- Reuse the existing connectors, metering, audit journal and judge panel. No duplicate LLM/framework stack. Ownership is recorded before public starts/resumes; private Gray payloads are hashed in audit requests, not copied into the audit log. Cloud private-input review is separately opted in per run.
- Use pinned scanner images and trusted local rules, with no auto-pull/network during scanning. Actual image IDs and runtime versions are recorded. Missing scanners/databases/classifiers cannot become passes. Custom declaration rules do not prove dataflow, authorization effectiveness or successful CI.
- Link findings by bot/category with explicit uncertainty, never infer a code cause from behavior alone. Full describes selected evidence modes, not certification or complete coverage.
- Preserve original overridden findings, source hashes and anchored state hashes. Raw source uploads stay private until their retention expires; report secret findings contain only tails. Regex redaction is not comprehensive anonymization.
- Keep the fixed benchmark threshold. Both baseline and modified code fail it on the current host; profiling/further performance work remains open instead of inflating the baseline.

## 2026-10-15 — Execute the requested source audit honestly

- Keep scanner completion separate from a passing verdict. All 14 checks can process while six control questions remain Not tested: limited text rules found no sufficient evidence. Never invent controls or turn these into passes to satisfy a completion target.
- Support explicitly configured WSL Docker transport through argument vectors; do not expose an unauthenticated Docker TCP socket. Preserve network=none, read-only source, dropped capabilities and unprivileged scanner UID.
- Trivy's pinned version opens its public BoltDB read/write. Give it a disposable, size-limited private copy, not a writable source or writable shared database. Keep public DB updates outside evaluations.
- Retain all advisories for every OSV-inventoried package; check final package coverage and snapshot hashes. A scoped DB cannot silently evaluate an unseen dependency. OSV uses a bounded 2 GiB/240-second limit; the scoped real scan completed in about two seconds.
- Scanner scan time excludes provisioning. Report package/advisory matches rather than adding overlapping scanner counts into a supposed unique vulnerability number. No source-only audit establishes chatbot behavior quality or control effectiveness.

## 2026-10-15 — Database leases and portable CI fixtures

Retain thread-owned SQLite connections to avoid repeated WAL initialization on Windows. Each active context has an exclusive lease and its own transaction; nested contexts use separate connections. Explicit synchronous=FULL preserves durable commits. Application shutdown and fixture cleanup close idle handles, while active leases close after transaction completion. Tests cover commits, rollback, concurrent writes, nested contexts, reuse, file release and shutdown. The fixed speed regression threshold was not relaxed.

Concurrency limits apply to active run leases: the strictest overlapping lease governs traffic, and its capacity restriction ends when that run closes. Test these two states separately with events instead of depending on which OS schedules a run to finish first. Comparison subprocess flags use a portable fallback on Linux/macOS; synthetic UI fixtures grant ownership explicitly and clean up their own files.

### CI Python environment isolation

Use a fresh virtual environment on every matrix platform. The Windows hosted runner contains unrelated pipx packages; global pip check reported their filelock conflict after installing Studio dependencies. Isolating project packages preserves dependency checking while making runner-preinstalled tools irrelevant. The same portable environment setup applies to Windows, Ubuntu and macOS.

## 2026-10-16 — Owned subprocess cleanup in UI verification

Treat the synthetic UI server as a process tree. A Windows venv launcher may leave the actual Python server alive when only the launcher is terminated; the orphan holds the temporary SQLite database. Shut down the exact owned PID tree with taskkill /T /F on Windows and a dedicated process session/group on POSIX. Keep this utility in scripts/process_cleanup.py, outside production evaluation logic. A real descendant-file/socket regression verifies resource release without paid provider calls or relaxed cleanup assertions.

## 2026-10-16 — Manual CI entry point

Expose workflow_dispatch with no inputs so nontechnical users can run the current master branch through GitHub's Run workflow button. Re-running historical jobs intentionally retains their original commit; the README explains this and provides a branch status badge. Assert sys.prefix differs from sys.base_prefix before installation to catch accidental use of a hosted runner's global Python. Preserve dependency checks and historical evidence.

## 2026-10-16 — Keep judge accounts independent of target bots

Store ordinary judge credentials in Studio's own ignored .env. Resolve them by the configured judge endpoint, never by the chatbot target. Provider names, endpoints and environment variable names are editable in app/studio/settings.json. User-entered UI keys override saved credentials; an explicit generic key applies only to its saved endpoint. Match scheme/authority/path, rejecting user-info, query and fragment variants before any automatic provider-key reuse. Keep external credentials files only as explicit backward-compatible opt-in. Migrated this machine's former Reliance-derived judge key into Studio without altering the target bot file or publishing keys.

## 2026-10-21 — Conservative comparison and source-evidence decisions

- Simple comparison now uses paired scenario means within fixed category strata, not category resampling mislabeled as scenario resampling. Repeats stay inside their scenario. Confidence intervals adjust over all bot pairs, and a winner must beat every opponent beyond the saved practical tie margin. Protocol v5 records editable policy. Minimum scenario gates deliberately leave the short screening suite without an inferential winner; independence and representativeness still require human review.
- Per-category leaders are descriptive. Saved run policy controls ties, and incomplete panels/open evidence reviews prevent a definitive result. PDF and the simple dashboard report the same decision; legacy comparison remains available for legacy runs only.
- Generic secret matches in narrowly recognized model-name assignments are unverified review items, not confirmed credentials or automatic passes. OSV placeholders/unresolved versions are Not tested with retained advisory context. Exact scanner-reported versions do not establish deployed versions. Raw secrets/matched source text remain redacted.
- Assurance mutations must validate the existing audit/findings seal. Recovery and automatic retention cannot re-seal corrupt records; the owner can inspect/delete them explicitly. Open review items block a Ready to launch label. This is local tamper detection, not immutable external audit storage or certification.
- This phase is validated with offline synthetic fixtures and local browser tests, not real provider evaluations or uploaded application execution. Shared-host authentication, dependency locking and native platform qualification remain separate work.

## 2026-10-21 — Readiness and outcome are explanations, not verdicts

- Keep the four `Finding.verdict` values. Preflight readiness (Ready, Needs input, Tool unavailable, Not applicable) is a separate stored report, and outcome classes (insufficient evidence, tool unavailable, missing input, not attempted, declaration, flagged, confirmed by review, cleared by review) are derived for display and export. This avoids a scoring, export and backward-compatibility migration.
- Not applicable is used only when a check structurally cannot apply (Bandit with no Python files). Missing lockfiles, workflows or container files are Needs input, never Not applicable.
- A scanner "fail" is Flagged until a person keeps it in review; only then is it Confirmed by review. Source declarations stay Declaration only.
- Historical runs are explained by conservative inference from saved fields and are never rewritten. New White findings record `details.outcome` explicitly.
- Guidance text and cause types live in `app/studio/evidence-guidance.json` so wording can change without code changes.

## 2026-10-21 — Runtime evidence must be run-correlated

- Runtime checks are Gray-box Findings with their own IDs (`runtime_*`) that name the White check they corroborate in `details.corroborates`. They never change the White Finding, so a source declaration is never promoted into a pass.
- Only records with this assessment's `run_id` (and the matching `check` name) are evaluated. Uncorrelated or other-run records are counted and excluded. Bot wording is never evidence that a tool did not run.
- A pass needs both sides of the behavior: an unauthorized attempt that did not execute and an authorized one that did; a session seen before and gone after the TTL; an injected fault plus a timed response. Otherwise the check stays Not tested.
- Expectations are captured when the run starts and reused when later logs are attached, so a later upload cannot change the limits it is judged against.
- The control worker parses Python with `ast` inside the scanner container and copies out only recognizable model names and numbers, never other literals.

## 2026-10-21 — White AI explanations and scanner provisioning

- An automated explanation is accepted only with every planned check ID exactly once, a fixed assessment vocabulary, and quotes that are exact substrings of the supplied reason or excerpts. Anything else is rejected and kept as a failed attempt; there is no partial acceptance.
- Explanations are appended to `ai_explanations` with an audit event; they never rewrite `ai_source_review`, findings, scores or reviews. The earlier assistant review stays the displayed review where present.
- Cloud judges are used only when the explanation request sets `cloud_consent`; earlier consent for specific VoltKart excerpts is not generalized.
- Scanner data preparation is an explicit maintainer step outside evaluations. The script works only on files already on disk and writes a new folder; scoped snapshots are checked again at scan time against every package OSV inspected.

## 2026-10-21 — Model names in mapping literals

A generic secret match on a dict-literal line is qualified as a model-name review item only when the line contains nothing but string literals and `: , { }`, at least one `*model` key holds a structured model identifier, no key looks secret-like, and every other value is a model identifier or plain words. Everything else keeps the credential alert. Qualified matches remain Not tested with review, never a pass.
