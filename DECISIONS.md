# AI Agent Studio: black-box upgrade audit — 2026-10-09

## Work verified before drive disconnection
- Inspected existing main.py, database.py, config.py, ZIP handler, startup script and dependencies.
- Existing scoring excludes unavailable cases and can produce misleading high aggregate scores. Replace with a fixed planned-case denominator; Not tested contributes zero with an explicit missing-evidence reason.
- Existing comparison does not implement randomized, reversed pairwise judging. Add both orders and disclose disagreement.
- Retire source analysis, Bandit, project unit tests and coverage from the active application, preserving historical reports with their original labels.
- Preserve every planned case before execution so cancellation, errors and unavailable prerequisites cannot silently drop cases.
- Keep actual transcripts, reference facts, policy, judge rubric, model/version, timestamps and score reasoning together.
- Unknown cost must stay unavailable, not zero.

## Isolation and model decisions
- Verified Windows 11 Home, 16 GB RAM; WindowsSandbox.exe absent.
- Do not run uploaded ZIP code in a host process or pretend a virtual environment is a sandbox. ZIP execution must remain unavailable until a genuinely isolated runner is implemented and verified.
- Playwright widget detection needs an explicit failure path for ambiguous selectors, authentication and CAPTCHA.
- Local models should load sequentially to limit memory. Missing frameworks/models must yield Not tested, never invented judgments.
- Temperature 0 reduces variability, but does not guarantee determinism. Swapped A/B judging reduces position bias, but does not prove its elimination.

## Interrupted work
- A pre-upgrade archive was created at D:\AI-Agent-Testing-Studio\runtime\backups\pre-blackbox-upgrade.zip before disconnection.
- Dependency installation was started, but completion is NOT verified. Its log is runtime/logs/blackbox-install.log. Inspect before retrying.
- No new evaluator, UI or scoring implementation has been verified. The attempted DECISIONS.md write failed when D: disappeared.
- Resume by verifying D:, inspecting the package installation and backup, then copy this document to project DECISIONS.md and implement/test staged changes.

## Verification required before delivery
- At least 30 planned cases per category in Single and Compare modes.
- Identical cases for both bots, randomized and reversed pairwise judgments.
- Missing references/policy/judge/connection, errors and cancellation all persist Not tested with zero contribution and reason.
- No active source-code tests or host ZIP execution.
- Real connector fixture tests for REST, OpenAI-compatible and web widget interfaces.
- Framework/model adapters must prove actual execution; package presence alone is insufficient.
- Evidence-linked results, category/overall scores, fair comparison of latency, no invented cost.
- PDF/JSON exports, readable UI and browser verification.


## Implemented black-box core and current limitations
- The active app is now app.main -> app.blackbox_app. Old source-testing services and tests were moved to runtime/retired-pre-blackbox for recovery, not imported by the active app.
- Added 16 black-box categories with at least 30 pre-recorded case slots each. Missing cases contribute zero, never a pass or tie. Template variations are labeled as such.
- Single/Compare modes, randomized target order, reversed pairwise judgments, persistent evidence, cancellation, browser/REST connectors and PDF/JSON reports are implemented.
- Eleven core regression tests passed; browser Compare flow passed using unreachable verification targets. A PDF was rendered and visually checked. Further connector tests have been added; their completion must be verified.
- The earlier attempt to append these notes was not executed: automatic approval review failed due to an account usage limit, not because the operation was judged unsafe. It succeeded on this resumed turn.
- Framework installation is separate from integration readiness. DeepEval, DeepTeam, Garak, HHEM and QwenGuard execution must not be claimed until their adapters/models are verified. The current evaluator uses a configured OpenAI-compatible rubric endpoint.
- No genuine isolated ZIP execution backend is configured. Uploaded archives are stored without extraction or host execution. No local judge server is auto-started.

## Category discoverability correction
- User could not identify Hallucination, Bias, Guardrails or Performance under simplified names. Those exact terms now appear in the category headings, filters and results, with plain-language explanations alongside them.
- Each of the four cards states its actual requirements and planned case count. This is a naming/discoverability correction, not a claim that a new benchmark has run.
- Performance does not require an AI judge, but does require a working target and separate consent. Accuracy requires uploaded reference facts; guardrails require the user's policy; bias includes paired starter prompts and requires a configured judge.
- Existing run IDs and evidence are preserved. Historical case scores are not recalculated merely to change display labels.

## Verification after category-label correction
- All 16 active platform regression tests passed, including live local REST, OpenAI-compatible and Playwright widget fixtures, evidence validation and token redaction.
- Chrome verified Hallucination, Bias, Guardrails and Performance cards on port 2708, their descriptions/requirements, selected state, and case-count updates. No JavaScript runtime errors were observed.
- This check validates the interface and platform behavior; it is not a new quality benchmark of the user's chatbots.


## Team A / Team B live preflight
- Rechecked the user's previously supplied deployments. Team A frontend returned 200, its protected models endpoint returned 401; Team B root and models endpoint both returned 404. Local judge discovery failed and no provider key/model was configured.
- Authenticated Team A testing was blocked by automatic approval review; explicit permission for the publicly advertised customer demo login was requested. No credentials were sent after the rejection.
- Saved a blocked preflight comparison with 480 planned cases per bot, zero executed chat cases, Not tested statuses, zero missing-evidence contributions and no winner. This is not a quality benchmark.
- Added a prominent connection-evidence panel and direct run links so blocked preflight records cannot be mistaken for successful evaluations.

## Reliance-only live evaluation
- User limited testing to their local Reliance chatbot. Team A/Team B comparison was not continued.
- Started the existing backend on loopback port 8000; did not start Ollama. Gemini 2.5 Flash Lite returned a Google model-unavailable error. OpenAI returned a rate-limit error. Verified Google's recommended Gemini 3.5 Flash Lite with a real request, then changed only GEMINI_MODEL in the Reliance configuration and restarted the backend.
- Added bounded Reliance SSE token/meta/done parsing. An HTTP 200 with an error event, unsuccessful done event, incomplete stream, or empty answer cannot be scored as successful. Corrected REST history to exclude the current message (sent separately).
- Seventeen platform tests passed including streaming success/error/incomplete cases.
- Started run dc363235-db8d-40dd-a46e-c2c40a442f7c: 150 cases, 30 each for hallucination, bias, guardrails, injection and performance. Reference facts come from the bot's public synthetic /products catalogue, not uploaded source code.
- Judge is the already-configured Gemini account via Google's OpenAI-compatible endpoint, temperature 0. It is a cloud rubric estimate, not a local-model or framework-specific measurement. Same-model self-evaluation may be optimistic; this run is not an independent certification.
- Cost is unavailable because pricing and billable usage were not established. Other categories are outside this run's scope. Product facts are synthetic, not verified real-store facts.


## 2026-10-10: Simple setup, stable evidence view and visual dashboard
- Replaced the large initial form with link/ZIP entry, Single/Compare mode and Start. Technical fields, datasets, category selection and judge overrides live under a collapsed Advanced section. Core four categories are selected by default; all 16 remain available.
- Kept separate target-message, judge data-sharing and performance permissions. Automatic approval rejected a proposed hardcoded consent value; it was not applied. The shipped design retains explicit opt-ins and rejects missing consent before discovery requests.
- Added server-side defaults and automatic Reliance protocol/catalogue setup. Public defaults never return keys or server-side environment-file paths. A judge override resets sharing consent. Setup notes distinguish the generic safety baseline and bot-supplied synthetic facts from independently verified data.
- ZIPs remain stored but not executed because a genuine isolated runner is unavailable. Basic upload visibility does not imply runnable ZIP support.
- Fixed progress refresh replacing every details element: preserve open state, focus and scroll position, skip unchanged panels, ignore stale asynchronous fetches, and preserve results on transient refresh failure.
- Added dependency-free SVG donut, category score bars and request-latency graph backed only by recorded cases. Comparison shows one chart set per bot; pending cases are distinct from Not tested. New saved-run date/name/status context prevents confusion with the setup form.
- Auto protocol discovery now rejects HTTP 401/404 instead of treating JSON error bodies as a working chat. Target authorization headers are included in discovery.
- Updated active README; preserved legacy instructions in runtime/retired-pre-blackbox/README-before-simple-ui.md.
- Verification: 25 backend regression tests passed, including new consent, secret redaction, Reliance preparation, comparison-reference and ZIP nonexecution checks. Chrome regression passed simple form, explicit consent, saved 149/150 results, three graph types, open cases across repeated polling, scroll stability, search, Compare charts and mobile overflow, with no JavaScript runtime errors. Browser polling/Compare fixtures are not saved benchmark results and make no paid evaluator calls.
- The saved Reliance run completed with 149/150 scored cases; this UI work did not run a new chatbot benchmark or change case scores.

## GitHub delivery, 2026-10-10
- Updated the existing hussain-code checkout from the running Studio, preserving unrelated root-level chatbot comparison files and repository history. Removed superseded Studio source scanners and their tests from active tracked paths.
- Excluded environment secrets, runtime databases/reports/uploads, virtual environments and downloaded packages. No private live transcripts are included in this update.
- Included blank saved-judge settings in .env.example. The optional browser regression supports configurable Playwright module, server URL and saved run; a fresh clone uses the self-contained pytest suite without private benchmark data.

## 2026-10-12: Cost metering upgrade

### Pre-implementation call audit
- Target: `Connector.conversation` sends each REST/OpenAI-compatible/SSE turn; `web_conversation` sends each browser chat turn. Browser navigation, interface discovery and catalogue GETs are not model calls.
- Rubric judge: `judge.ask`, called once per individual evaluation and twice for swapped pairwise judgments. Performance uses measured latency and has no judge request.
- Resume/retry: each newly dispatched attempt must append a usage row, without replacing prior attempts.
- Case catalogue: deterministic Python templates; no model is used to generate current cases.
- DeepEval, DeepTeam, Garak, HHEM, Qwen3Guard and embeddings are not active engines in this installation. Existing capability checks only detect package availability. No framework/model costs are invented. Explicit custom-model/local hooks are provided for future integrations; real framework-internal compatibility is not verified by the generic adapter fixture tests.
- External REST/widget bots may make hidden model/tool/embedding calls. Studio cannot meter server internals without bot telemetry. A model alias prices visible traffic only and remains an incomplete estimate. A reported usage response establishes that reported call's usage, not full internal coverage.

### Accounting decisions
- All active target and rubric calls pass through one metering layer. OpenAI-compatible traffic uses LiteLLM with SDK retry/fallback/cache disabled. Explicit retries get a separate event. Failed/timeout calls without provider billing evidence have Unknown dollars, not zero. Exceptions are not stored in the usage table.
- SQLite inserts a counts-only attempt row before dispatch, then finalizes that same row. Prompt/answer text stays in existing transcript records. Startup marks any interrupted in-flight rows Unknown. The ledger includes extra disjoint cache-write fields, conversation IDs, visibility, and exact fractional-micro-dollar text for aggregate precision.
- Token priority is reported, then a known model tokenizer, then a visible-text character estimate. Opaque bots always remain estimates without provider usage even if a model alias is supplied. Tokenizer counts are measurements of visible text and cannot recover hidden system prompts.
- OpenAI Chat/Responses: cached input is a subset of total prompt/input tokens; reasoning is a subset of completion/output tokens. Subtract each before charging the disjoint components. https://developers.openai.com/api/reference/resources/chat
- Native Gemini: prompt includes cached content; candidates output and thoughts are separate. Native thoughts are added once. Nonstandard tool-use prompt accounting is not assumed exact. OpenAI-compatible Gemini follows its returned OpenAI schema. https://ai.google.dev/api/generate-content#UsageMetadata
- Native Anthropic: input excludes cache reads and cache creation. Read, 5-minute writes and 1-hour writes are separate charge buckets. Output already contains generated thinking; no fabricated extra reasoning count. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Validate token counts as nonnegative integers. Invalid provider usage falls back to labelled counting/estimation.
- Rates are USD per million tokens, seeded from LiteLLM's public JSON and stored in immutable dated snapshots. Source URL, snapshot ID/date, selected rates and overrides accompany reports. New overrides derive a snapshot without changing the base catalogue. Updating prices affects only new runs.
- Reasoning uses the supplied reasoning rate or documented output-rate fallback. Known long-context input/output tiers are honored. Unrepresented billing features (e.g. non-token tool fees, batch/priority service tiers, image/audio-specific charges) are outside current text-chat cost coverage; use a price override only when that rate is valid.
- Decimal arithmetic is used throughout. Required integer micro-dollar fields round at the storage boundary, while exact fractional micro-dollars are retained and summed before UI rounding, preventing per-call rounding accumulation.
- Local models have zero API cost only when explicitly declared local. Merely calling localhost does not imply a local model: a local bot may use cloud APIs. Optional local compute is elapsed call wall time times a manual hourly rate, an estimate rather than a hardware invoice. INR uses a manual rate only.

### Budget, summaries and compatibility
- A pre-run estimate uses planned target turns and judge requests times saved average input/output tokens and pinned rates; it excludes retries, hidden internal traffic and unknown local runtime. Existing safety/sharing/performance consent remains required.
- Budget checks use a SQLite write transaction to reserve the next call and include in-flight reservations. A configured finite budget refuses unknown pricing or unresolved failed-call billing. Reaching the allowance stops new calls and retains Not tested cases with worst-case score contributions. Partial completed transcripts are preserved.
- This is a launch guardrail, not a provider billing cap. Token estimates, opaque targets and already-running requests can exceed an estimate; local compute has no known duration before execution. The UI discloses this.
- Bot and Evaluation costs have separate headlines. Unit economics use all target attempt costs divided by successful visible answers/conversations. Parallel paired prompts are separate conversations. Retry and failed groups overlap and are never added again.
- Quality-per-dollar uses the configured evaluation score divided by projected dollars per 1,000 conversations. Zero-cost/unknown denominators are unavailable. A cheapest qualifying bot is not highlighted when measurement bases differ.
- Historical runs keep their original results, with cost unavailable. They are not retrospectively assigned zero cost. Unmetered historical runs must start a new run rather than mixing old and new accounting.
- Optional framework adapters require an active run context and explicit judge consent. DeepEval uses a custom DeepEvalBaseLLM; DeepTeam must receive both simulator and evaluator; Garak must use the metered generator. No global monkeypatching or implicit provider credentials are used. Local guard/HHEM/embedding hooks accept the actual tokenizer when available.
- The main installation and API keys were not used for paid verification. Development occurred in an isolated copy after automatic approval rejected a broad in-place rewrite; deployment is restricted to reviewed, tested files. Existing .env, transcripts and databases are preserved.
- Verification: 44 platform tests passed with no live provider calls, including a real local mock HTTP gateway, HTTP 429 with SDK retries disabled, browser sends, concurrent budget reservations, interrupted billing, immutable prices, exports and both modes. Chrome UI regression verified separate cost totals, Estimated badges, price provenance, comparison warnings, disclosure stability, settings, pre-run estimate/cancel, PDF/JSON downloads and mobile overflow with zero JavaScript errors. Synthetic verification data is isolated and is not copied into the production database.
- PDF cost pages were rendered with Poppler and inspected; long ledger records wrap within margins. Added page numbers and kept headings with following text.
- Garak's current Conversation/Message interface was checked against NVIDIA's generator source. Adapter process-pool execution is disabled to preserve per-case context. The adapter remains inactive until a real framework integration test is installed and run. https://github.com/NVIDIA/garak/blob/main/garak/generators/base.py
