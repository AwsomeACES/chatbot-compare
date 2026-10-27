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

## 2026-10-23 — Human-aligned Judge calibration (T-035)

- Ownership: C08 Judges owns calibration (it measures an evaluator against supplied labels); C11 integrates audit, status display, privacy and retention. It is not a fourth Engine or test category, and the existing `calibration` category (Acknowledging uncertainty) is untouched.
- Human labels live only in `judge_calibration_set` records as ordered revisions with a required change reason; they are never Findings, overrides, credentials or Judge input. Human overrides are not imported as ground truth.
- Evaluations bind to an immutable frozen version and its content hash; later label or membership edits need a new version.
- Fingerprints are separate: evaluator template (builder output plus builder source), validation (source of evidence and verdict handling), generation settings, rubric/context, per-item request, transcript, version and policy hashes. Source hashing means forgotten version labels cannot hide prompt changes.
- Requested and actual models are recorded separately. Metrics are kept per actual evaluator, so a fallback never inherits the requested Judge's status and partial fallback never completes the primary.
- API-key rotation does not change evaluator identity; model, endpoint, template, validation, settings, policy or rubric changes make calibration stale. History stays readable.
- Denominator policy: agreement is matches over valid comparable labeled items; failures stay Not tested and reduce coverage and block the aligned state; zero comparable is unavailable. Defaults (80% agreement, 100% coverage, 10 scenarios, 2 pass, 2 fail) are editable engineering choices.
- Diagnostic only: no Finding, score, winner, override or model-to-model agreement is changed; no enforcement gate.
- Retention: copied evidence follows its source. Run, assessment or expiry deletion tombstones copies, drops cached Judge output and invalidates dependents; audit chains keep hashes only. Explicit set deletion removes everything dependent.
- Provider-returned model names are not immutable revisions, and a small labeled sample does not generalize across rubrics or categories.

## 2026-10-23 — Only the first litellm import is serialized

The initialization lock exists because concurrent first imports deadlock inside litellm's own package setup. It must not become a per-request lock. The module is cached on first success and read without the lock afterwards, and `completion()` reads that cache directly rather than hopping through a worker thread, so provider requests keep their own concurrency and a cancelled caller cannot strand a thread-pool worker on the lock. A failed import caches nothing and releases the lock, so the next caller retries rather than blocking forever. Any future change here needs the four regression tests in `tests/test_costs.py` to keep passing: serialized first import, lock-free reuse, retry after failure, and no worker thread per request.

## 2026-10-23 — Calibration sampling spreads coverage without revealing Judge output

- A flat seeded draw can omit whole Categories, so the default sample takes one conversation per Category in turn. Both the flat draw and the seeded order remain available and reproducible for a given seed.
- Optional outcome balancing alternates the saved Judge's own passes and failures inside each Category, because a Run that passed almost everything cannot measure false acceptance. The saved outcome is an allocation key only: it is never written to an item, never shown while labeling and never sent to a Judge, so blind labeling is preserved structurally rather than by convention. Because it changes the sampled failure rate, the selection method records a base-rate note and false acceptance and false rejection are reported as conditional on the sample, never as population rates.
- A held-out subset is split by scenario, never by item. Repeats of one scenario are not independent observations, so splitting by item would let a held-out number restate reviewed work. A holdout requires at least two distinct scenarios; otherwise freezing is refused rather than producing a degenerate fold.
- Fold metrics carry their own denominators and the headline stays the whole frozen sample. A smaller fold is never presented as a stronger result, and a fold below the configured minimums reports `insufficient_sample` as any sample would.
- The product cannot enforce the development-then-holdout sequence or detect prior exposure. `docs/judge-validation.md` states the procedure and the reviewer limitations the owner must record; fingerprint invalidation marks a changed configuration stale rather than carrying the old result forward.

## 2026-10-23 — Dependency locking is universal, hash-verified and pinned to the tested set (T-033)

- Format: `uv pip compile --universal --generate-hashes`, installed with `pip install --require-hashes`. Universal resolution keeps environment markers so one committed lock serves Windows, Linux and macOS; `pip` verifies every sha256 before installing. pip-tools was rejected because it resolves for the running platform only, which would make the committed lock a Windows artifact.
- `uv` is a maintenance tool, not a project dependency. It is installed into a throwaway environment, never globally and never into the project environment; `scripts/lock_dependencies.py` takes the interpreter that has it.
- Locks pin the versions the test suite actually exercised, by constraining the resolution to the installed environment. Taking the newest versions the ranges allow is a separate, deliberate `--upgrade` step followed by a full suite run, because a locking change must not smuggle in an untested upgrade.
- The optional evaluation set is resolved unconstrained and its lock is labelled `Unverified`, because the project neither installs nor exercises those packages. An unverified lock that says so is more useful than no lock.
- `requirements-dev.txt` no longer pins `filelock>=4.0.9`. That pin was added to satisfy a CI runner's preinstalled pipx during a global `pip check`; isolating CI in its own virtual environment superseded it, and because litellm requires `filelock<4.0` the pin made a clean development install impossible.
- Lock validity is asserted by tests rather than by regenerating in CI, so the checks run on every platform without `uv`.

## 2026-10-23 — Browser coverage follows the active shell; unrunnable checks are removed

- A browser check must start its own loopback server against a temporary runtime with synthetic fixtures. It may not depend on a running Studio, saved history, a fixed run identifier, a machine-specific browser path, or anything under the gitignored `runtime/` directory. A check that cannot run from a clean checkout is not coverage.
- The legacy `index.html` interface stays served and keeps its browser check, because saved reports and documented links still point at it. Retiring it is a separate, explicit decision.
- The current shell gets its own check covering navigation, opening a saved report, escaped provider output, Judge calibration and Governance alignment. Failure artifacts are a trace and a screenshot of synthetic fixtures only, never user data.
- CI wiring is guarded by tests (`tests/test_verification_wiring.py`), because the regression found here was configuration drifting away from the current UI while still reporting green.

## 2026-10-23 — Evaluator provenance is recorded, never reconstructed

- A verdict records the evaluator that actually produced it: requested and actual model, requested and actual endpoint, provider, local flag, family, whether a fallback answered and the specific failures that caused it. Credentials are never part of it.
- A saved Run from before this metadata existed reports provenance as unavailable. An unrecorded local flag stays `None` rather than defaulting to `False`, because a plausible default is indistinguishable from a recorded fact once displayed. Nothing is inferred from the configuration to fill a gap in a verdict.
- Provenance is derived on read and attached to the API response only. It is never written into a saved Run, so reading a report cannot change it.
- Results produced by a deterministic rule, measured latency or a local classifier are labelled "no Judge" and are never attributed to an evaluator.
- A Run with more than one actual evaluator stays qualified wherever it is shown: scores from different evaluators are not interchangeable and such a panel does not yield a confident winner.
- Three separate concerns keep three separate places: the same-family warning (shared bot and Judge model family), human-label calibration (agreement with the owner's labels), and model-to-model agreement (Judges agreeing with each other). Merging any two of them would let one be read as evidence for another.
- Readiness information is improved instead of changing model selection. No larger or paid model is ever chosen automatically, and model size is not treated as evidence of quality.

## 2026-10-23 — Redaction exempts public identifiers by shape, after the specific rules run

- Only the generic rule — any run of 10 to 15 digits — skips recognised public identifiers (UUID, CVE, GHSA, OSV-family, CWE, ISO 8601 instants). The email, national-identifier and credential rules run over the whole string first.
- That order is required, not cosmetic. Applying the exemption first preserved the CVE token inside `cve-2024-1234567@example.com`, which split the string so the email rule never matched the whole address and the address survived redaction. A negative test in `tests/test_export_redaction.py` reproduces it.
- A new redaction rule must be classified as specific or generic; a test fails if it is not, so the exemption cannot silently widen to cover it.
- A typed numeric metadata field keeps a bare number, because a counter or an epoch value is not a telephone number. The exemption checks the value shape as well as the field name, so a contact detail stored in such a field is still redacted. Free-text fields are never exempt.
- The exemption is disclosed in the export along with its limits: names, postal addresses, account handles and organisation-specific identifiers are not detected, and a value deliberately shaped like a public identifier is kept. This is a baseline against accidental disclosure, not an adversarial filter. No cloud redaction service was introduced.
- A redacted export states that its hashes cannot be recomputed from it, because redaction changed the bytes they covered. They remain comparable only against the retained original record, and they are integrity checks rather than signatures.

## 2026-10-23 — A declaration is labelled the same way in every mode

- An `exists` Finding reads **Declaration only** in Black-box, Gray-box and White-box alike. White-box reads source and Gray-box reads operator declarations, but neither shows that the control works, so a mode-specific label like "Found in code" invited the stronger reading. What each check could see is stated by its own guidance instead.
- The finding review is an in-page `dialog`, not `prompt()` and `confirm()`. A browser prompt cannot carry a field label, a written error or a minimum-length rule, and a confirm dialog gives a yes/no where the decision deserves named options. Validation lives in the handler so the message is visible, announced text; a native constraint bubble is not reliably announced and disappears.
- A reason shown only in a `title` tooltip is unreadable without a pointer, so the category matrix renders it as focusable text as well.
- Colour contrast has not been measured against an agreed standard, and status wording outside the assurance screens is not yet centralised. Both remain open in T-019 rather than being claimed.

## 2026-10-23 — One explanation provenance block for every export

- The JSON, PDF and teammate Markdown exports render the same `explanation_provenance()` block, so they cannot disagree about whether an optional AI explanation exists, which model produced it, which provider attempts failed, or what it cost. Each export previously described the explanation in its own way, and the teammate export omitted it for resolved checks.
- The block always states the returned model identifier with the caveat that a returned name is not a guaranteed immutable revision.
- An unmetered explanation reports "No explanation calls", never `$0.00`. Unknown billing stays Unknown.
- An explanation never changes a recorded verdict, severity or review. A test asserts a finding the explanation calls a false positive still carries `fail`.

## 2026-10-24 — The benchmark's configured tolerance is authoritative, and the baseline moves for neither reason

- The gate is `baseline_seconds × (1 + tolerance)` read from `benchmark.json`, not a literal in the test. A declared field that the test ignored was worse than no field.
- A guard test asserts the committed baseline, tolerance and simulated workload, so widening the budget in configuration fails a test rather than passing quietly.
- The baseline is not raised to hide a regression, and it is not lowered when a host happens to measure faster. The current median is about 31% below the gate on one Windows host; turning that into a stricter global claim would make the gate flake on hosts it was never measured on.
- The benchmark prints its measured distribution, so a result can be published rather than only passing.

## 2026-10-24 — Measure a scan before changing its concurrency

- `sandbox.scan()` reports five phases and separates `preparation_seconds` from `scan_seconds`. The offline database copy is preparation; reading it as scan time would misattribute the dominant cost on modest hardware.
- A phase that raises still records its duration, because the slow phase is often the failing one.
- Timings travel on a Finding's details and never become a score or a verdict.
- No concurrency change was made. Bounded Gray parallelism stays unimplemented until a real scan has been measured, because the images and offline databases needed to measure one were not available. Recording "no safe improvement demonstrated" is the honest outcome; a speedup claim without a measurement is not.
- The per-scan private Trivy copy stays. A mutable BoltDB is never shared between Runs, even though copying it is the expensive step.

## 2026-10-24 — Scenario coverage is selectable, versioned, and never self-certifying

- The ten top-level Categories do not change. An extended suite is a _selection_, not a new default: `default_scenario_suite` stays `screening`, so the light screening path is untouched for anyone who does not choose otherwise.
- Selecting a suite appends its version to the saved `protocol_version`. A Run therefore records which suite produced its Cases, older reports stay readable on their own terms, and two suites are never silently compared as the same protocol.
- The suite selection must reach the protocol override. `prepare()` and `make_run()` both resolve the protocol with the selected suite; resolving it in only one place would have planned the default while the interface claimed otherwise.
- Bias is excluded from the extended suite. It is governed by `bias-v1.json` with nine subtypes and a derived `algorithmic` aggregate, and a scenario set must not replace that or let the aggregate be counted as another independent observation.
- Every scenario carries `intent` and `review_status`. Nothing in this repository is marked independently reviewed, because nothing has been: the file, the API and the Evaluate screen all say `authored`.
- Reference facts state their own scope. "The supplied reference set contains no price for X" is a fact about the reference set; it is not proof that X does not exist, and the scenario says so.
- Distinct scenarios are the only coverage counted. Repeats are a separate multiplier, duplicated prompts are rejected by a test, and a paraphrase is not independence. More scenarios reduce the chance of missing a known failure mode; the interface says plainly that they do not show a bot is safe.

## 2026-10-24 — Contrast is measured, and status wording has one home

- Contrast is computed by `scripts/check_contrast.py` against WCAG 2.2 AA, and a colour the script cannot resolve is reported as skipped rather than counted as passing. The test requires zero failures _and_ zero skips, so an unmeasured colour cannot hide in a green run.
- The script cannot lay the page out, so its declared container-background mapping is part of the measurement and has to be kept truthful when the layout changes. That limitation is in the script, not only in a note.
- The three colours it found failing were darkened to roughly 4.8:1 rather than to the 4.5 boundary, so a later rounding or hue change cannot silently drop them below the standard.
- A checker that cannot fail is not a check: one test feeds it a known-failing grey and requires it to report a miss.
- Status wording lives in `window.StudioStatus` and every screen reads it. A second copy of the wording is how a Gray declaration came to be labelled "Found in code", so a test fails if any screen hard-codes those words again or prints a raw machine status.
- Only a known no-call case may render as zero cost; a missing figure stays Unknown. The helper decides the known-zero case before the unknown case, and a test asserts that order.

## 2026-10-24 — Transcript-only intake for human calibration

Owner-authorized `collect_only` is an explicit non-simple Black Run setting requiring the Judge to be disabled. It removes only the generated judge-disabled prerequisite, gathers conversations through existing connectors/metering, and leaves scores unmeasured. Resume preserves completed scores and all attempted transcripts, including partial/error records; only unsent Cases dispatch. It does not bypass unrelated prerequisites, call a Judge, retry failed conversations automatically, or manufacture human labels. Separate calibration evaluations reuse the retained complete evidence.
