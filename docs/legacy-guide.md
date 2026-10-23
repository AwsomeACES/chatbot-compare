# AI Agent Studio

**New simple screen:** open http://127.0.0.1:2708/. Add 1–4 bots, choose judges and repeat the same ten checks.
See [the short user guide](docs/simple-guide.md) for Windows, macOS/Linux, Ollama and Docker setup.
The older interface remains at /index.html for previous runs and advanced datasets.

## AI Agent Studio

Local, single-user black-box chatbot evaluation on **http://127.0.0.1:2708**. Test one chatbot or compare two to four using conversations and evidence. Source scanning and uploaded unit-test execution are retired.

For the code map, formatting conventions and development checks, see
[CONTRIBUTING.md](CONTRIBUTING.md). Current engineering decisions are in
[DECISIONS.md](DECISIONS.md); incomplete capabilities are tracked explicitly in
[BACKLOG.md](BACKLOG.md).

## Start on Windows

```powershell
Set-Location "D:\AI-Agent-Testing-Studio"
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Port 2708
```

For a fresh installation (Python 3.12+):

```powershell
Set-Location "D:\AI-Agent-Testing-Studio"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2708
```

Never overwrite an existing .env containing your settings. Installed Chrome is used for browser tests; otherwise install the Playwright Chromium browser separately.

## Simple workflow

1. Open the Studio and paste the running chatbot page or full API URL. Select Compare to add a second link.
2. Allow sending test messages. Enable the saved AI judge if you authorize sending prompts, reference facts and bot replies to the displayed provider.
3. Optionally enable speed and reliability checks. Click **Start testing**.
4. See progress, the outcome donut, category score bars and response-time graph. Open any case for its exact transcript and evidence; polling preserves open cases.
5. Download JSON or PDF, or use Previous results to reopen a saved run.

Default checks use 46 explicit scenarios: 10 hallucination, 12 bias, 12 guardrails and 12 injection. No padding is added. All 16 categories remain available under Advanced; non-core legacy scenarios are labeled, and extra wording variations require a separate opt-in. Sample counts do not guarantee comprehensive coverage. Set a longer time limit for large suites or slow targets. Only one evaluation runs at a time.

Advanced settings hold optional API credentials, JSON fields, conversation state fields, browser selectors, reference facts, policy, scope, judge overrides and limits. Selecting more categories does not eliminate their evidence requirements.

## Automatic setup and remaining requirements

REST JSON, OpenAI-compatible chat-completions and identifiable web chat widgets are supported. Common response fields are detected. Authentication, ambiguous web controls, custom payloads or multiple target models can require a one-time Advanced setting. Arbitrary chat websites are not universally supported.

For a recognized Reliance service on localhost:8000 (or its localhost:3000 frontend), Studio configures its streaming endpoint, Gemini provider and conversation history fields. If no references were supplied for a single Reliance target, it loads the public synthetic product catalogue. These bot-supplied facts are **not independently verified retail facts**; setup notes are saved with the run and exported. Compare mode does not invent a shared reference dataset.

For other bots, upload verified prompt/reference cases to evaluate factual accuracy or business correctness. A generic Studio safety baseline is used when no policy is provided; replace it with your actual rules when needed. Scope tests require your scope description. Missing evidence stays Not tested with a reason and no score; it reduces coverage, not answer quality.

A ZIP can be uploaded and validated, but **no isolated execution runner is available** on this machine. Studio does not execute uploaded code on the host or claim a virtual environment is a sandbox. Start your trusted chatbot separately and paste its running link to evaluate it.

## Save an AI judge once on the backend

The judge accepts an OpenAI-compatible chat-completions endpoint. Configure these in .env and restart Studio:

```dotenv
STUDIO_JUDGE_URL=http://127.0.0.1:1234/v1/chat/completions
STUDIO_JUDGE_MODEL=your-installed-model-id
STUDIO_JUDGE_API_KEY=
```

For an existing trusted server-side environment file, STUDIO_JUDGE_ENV_FILE and STUDIO_JUDGE_KEY_NAME may identify the key to read; this path is never supplied by a web client. The current machine can reuse its previously configured provider. No key is returned by the defaults API. The displayed saved model is configuration, not proof that provider quota is available. No local model is automatically started.

External judges receive data only with explicit judge-sharing consent. Performance-only testing does not need a judge. A free chatbot website account does not imply free API access. Costs remain unavailable unless verified billable usage and pricing are provided.

## Dashboard and scoring

The donut counts Passed, Needs improvement, Not tested and Waiting. Category bars show scores plus scored/planned counts. Response-time charts use recorded requests in seconds and work offline without a chart CDN. Current-attempt charts and retry-inclusive reliability totals are distinguished.

Category quality is the mean of evaluated cases only; overall quality is the equal-weight mean of categories with evidence. No evidence means Not scored. Coverage is evaluated / planned cases. Ranking requires at least 80% coverage in every selected category (min_coverage API setting, default 0.8). Comparisons use shared evaluated cases with valid pairwise judgments and require the same coverage threshold per category. Missing cases may introduce selection bias; inspect their reasons before drawing conclusions. AI rubric scores are estimates; they are not an independent quality certification. Pass threshold is 80. Compare runs use identical cases and swapped/randomized A/B judging; missing pairwise judgments are not ties.

Saved results retain transcripts, reasons, timing, case identifiers and evidence digests. Historical results from the old source-testing platform use different scoring and are labelled separately.

## Architecture

- app/main.py exposes app/blackbox_app.py (FastAPI).
- app/blackbox: schema, automatic setup, connectors, case catalogue, judge, runner, reports.
- app/blackbox_static: HTML, CSS, vanilla JavaScript and dependency-free SVG charts.
- SQLite persists runs and upload metadata under runtime.
- Runtime also stores ZIPs, reports, logs and archived legacy code.

Key endpoints: GET /api/health; GET /api/blackbox/capabilities; GET /api/blackbox/defaults; POST /api/blackbox/easy-run; POST /api/blackbox/runs; GET /api/blackbox/runs; GET /api/blackbox/runs/{id}; POST stop/resume under that run; GET download?format=json|pdf; POST /api/blackbox/upload.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node scripts/check-js-syntax.cjs
.\.venv\Scripts\python.exe scripts/check-exact-compare.py
.\.venv\Scripts\python.exe scripts/check-studio-ui.py
```

`check-exact-compare.py` is the browser regression for this retained legacy interface; `check-studio-ui.py` covers the current shell. Both start their own loopback server against a temporary runtime and synthetic fixtures, so neither reads saved history, calls an external judge or stores fabricated benchmark results. Backend tests isolate their database and exercise local protocol fixtures.

The earlier `scripts/check-*.cjs` browser checks were removed on 2026-10-23. They loaded Playwright from the gitignored `runtime/ui-check/node_modules`, hardcoded one machine's `chrome.exe` path and deleted run identifiers, and asserted retired selectors, so they could not run from a clean checkout. See PROGRESS.md for the per-file reasons.

## Troubleshooting and limitations

- Could not connect: start the target, check its exact URL and credentials. A reachable homepage does not prove that chat works.
- Not tested: open the case reason. Supply references, rules, scope or a working judge as requested; quota failures cannot be repaired by changing a score.
- ZIP stored but unavailable: use a running link; isolated execution requires a separately implemented runner.
- Blank or stale page: restart Studio, then refresh the browser. Static responses disable caching.
- Browser widget detection is deliberately limited to clear chat inputs and assistant outputs; it does not solve login or CAPTCHA.
- Runs are bounded and sequential; this is not heavy-load stress testing.
- Framework package presence is not integration proof. DeepEval, DeepTeam, Garak, HHEM and QwenGuard adapters/models are not claimed as executed by the current rubric runner.
- Keep Studio bound to loopback. This is not a public multi-user production service.

Next improvements: verified isolated ZIP workers, more authenticated interface adapters, calibrated independent judging and verified cost accounting. Design decisions and corrections are recorded in DECISIONS.md. Older documentation is archived under runtime/retired-pre-blackbox.

## Cost ($) tracking

New runs have a **Cost ($)** results tab. Bot cost and Evaluation cost are separate. Old runs show **Unavailable**, because no reliable usage ledger existed when they ran.

1. Open **Advanced settings > Cost settings**.
2. For a REST or web bot, map its model using **Chatbot A/B model or alias**. Use the exact name in the pricing catalogue, or add explicit per-million-token overrides. This estimates only visible traffic; hidden internal calls need bot-side telemetry.
3. Optionally set a maximum run budget, local compute dollars/hour, manual INR/USD rate and qualifying quality-score threshold. Mark a model local only if it actually runs locally without cloud charges.
4. Save settings. **Update prices from LiteLLM** refreshes prices for future runs; existing runs retain their pinned snapshot.
5. Start a run and review its estimated cost. Existing target, judge-sharing and speed-test permissions still apply.
6. Open **Cost ($)** to inspect tokens, model/role/category/case breakdowns, top five cases, retries, failed calls and per-answer/per-conversation costs. Compare mode shows the two target costs separately, with quality-per-dollar and measurement warnings.

Unknown model pricing or uncertain provider billing displays **Unknown**, never free. A finite budget blocks calls with unknown cost and stops new calls at the estimated allowance. Remaining cases stay **Not tested: budget limit**, unscored and reducing coverage only. It is not a provider-enforced hard billing cap.

Token sources: **reported** = provider usage; **counted** = known tokenizer; **estimated** = unknown/opaque visible text. Counted and estimated costs are not invoices. Local API charges are zero; optional compute cost is a separate estimate. PDF and JSON include the pinned source/date and counts-only ledger. No API keys or prompt/answer text are stored in `usage_events`.

API: `GET/PUT /api/cost/settings`, `POST /api/cost/prices/update`, `POST /api/cost/estimate`. Mutating requests retain the `X-Studio-Request: 1` header and local-origin protections.

Dependency: `litellm>=1.80,<2`. Standard install command remains `& .\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

Integration scope: the active HTTP, browser and rubric pathways are metered. Optional DeepEval/DeepTeam/Garak custom-model adapters and local HHEM/guard/embedding hooks are provided in `app/blackbox/cost_adapters.py`, but those engines are not active or installed here. Adapter fixture tests do not establish real framework-internal integration. Any future engine must inject the metered adapter for every model role and add provider-call-count integration tests before activation. See `DECISIONS.md` for provider normalization, pricing and budget limitations.

## Safe ZIP export

Do not ZIP the entire working folder. Use `python scripts/package_release.py --root . --output ../AI-Agent-Testing-Studio-safe.zip`. This source-only export excludes `.env`, runtime data, dependency folders and nested archives; it includes the blank `.env.example`. See [SECURITY.md](SECURITY.md) for key exposure and revocation steps.

### Reference-free defaults (Ticket 82)

Start testing first shows a configuration preview. Unavailable checks include reasons; choose to exclude them or go back and configure them. No bot messages are sent by this preview. Hallucination without reference facts uses synthetic model, policy, rating and shipment probes to assess unsupported claims and uncertainty handling. A working AI judge and data-sharing consent are still required. Upload verified facts for catalogue accuracy; provide scope and business expectations for those categories. Preview endpoint: POST /api/blackbox/preview using the run settings payload.

### Tickets 83 and 84: case sets and evidence

Advanced → Import test cases (JSON) accepts category, name, turns, expected, optional reference and parallel. Imported cases replace built-ins per selected category; the count setting is a maximum. Download the 46-case starter set at /api/blackbox/case-set. See app/blackbox/cases/README.md for schema and limitations.

Judge quote validation tolerates normalized whitespace, case, quotation marks, dashes and bounded ellipses. At least one quote must match recorded assistant text. Partially unmatched quotes and ellipses are flagged for review in results and reports. If no quote matches, one metered correction request is allowed. Invented evidence still fails validation and remains Not tested, without a quality score.

## Exact checks, second judges and multi-bot comparisons

Choose **Exact checks only (no AI judge)** to run literal assertions without a model/key. Download the synthetic examples from **Advanced > Import test cases**, then import them. Select their categories and allow messages to your running bot. The preview identifies cases without exact criteria; these stay unscored and reduce coverage. The built-in injection suite includes one exact canary case; the other attack scenarios still need a rubric judge.

Imported cases can contain `checks: {"required": ["129999", "24 months"], "forbidden": ["lifetime"], "canary": "STUDIO_OVERRIDE_OK"}`. Required strings must appear in assistant replies; forbidden strings and the canary must be absent. Matching normalizes case, whitespace, quotes and dashes and respects token boundaries. Checks are all-or-nothing (100 or 0). They do not detect negation, prove factual accuracy, or accept semantic equivalents such as "two years" unless you use the AI rubric instead. Quoting a forbidden marker even in a refusal fails that explicitly configured literal check. Reference objects alone are not converted into assertions: declare `checks.required` or use semantic judging.

In **Exact checks + AI judge**, the case score is the lower of the exact-check score and primary AI score. A score below 80 fails. A conclusive exact failure remains a failure if the judge is unavailable; an exact pass alone does not substitute for a missing configured AI judgment. Transport/quota errors remain Not tested, not failed answers. Individual criteria, matched replies, scores and transcripts are exported in JSON.

Enable **Advanced > Second judge and regression settings** to sample a second model. Enter a different model ID and operator-declared family, its compatible endpoint/key, sample percentage (default 20%), and separate sharing consent. The same deterministic seeded sample is used for every bot. Agreement reports raw primary/secondary pass-fail agreement at 80, average score difference, sample count and unavailable judgments. It does not alter the primary quality score or prove either judge is correct. Second-judge errors preserve the primary result. Reaching the shared run budget stops further calls while preserving completed results. Judge calls and retries remain metered.

**Test mode** now supports one bot or comparisons of 2, 3 or 4 bots. Every target receives identical cases. AI comparisons use randomized A/B order and a swapped repeat; disagreement is not a tie. Exact-only cases compare exact scores; a failed exact assertion overrides AI preference. Results show all head-to-head matchups and an overall winner only when one bot confidently beats every opponent.

Confidence uses 2,000 seeded bootstrap resamples of paired net wins (+1/0/-1), stratified with equal category weight. At least 10 distinct shared scenarios and the configured minimum coverage (default 80%) in every category are required. Legacy wording variants are clustered by topic. Pair intervals use Bonferroni adjustment for a nominal 95% family-wise confidence level. An interval containing zero means **Too close to call**. This exploratory interval describes the selected cases, not all possible users or a guarantee of superiority. Results are finalized only after the run ends. All target costs remain visible; 3–4 bot cheapest/quality-per-dollar ranking is intentionally unavailable.

After a completed run has sufficient category coverage, click **Save as baseline** on each bot's result card. Future runs pin that baseline at creation, using the same bot name and URL. The case set, exact checks, policy, scope, primary judge and latency budget must match. Regression alerts compare only jointly scored cases and require sufficient shared coverage; default alert threshold is a 5 percentage-point drop. These descriptive alerts do not claim statistical significance. Changing the evaluation protocol requires a new baseline. JSON/PDF include comparison confidence, judge agreement and regression findings.

This implements Studio comparison rather than merging repositories. A blind arena and automated release/deployment gate are not included.

## Concurrent evaluations (Ticket 87)

Advanced > AI judge and run limits now exposes:

| Setting                                               | Default |   Allowed |
| ----------------------------------------------------- | ------: | --------: |
| Cases in parallel (`case_concurrency`)                |       4 |      1–16 |
| Conversations per target (`target_concurrency`)       |       4 |       1–8 |
| Concurrent judge calls (`judge_concurrency`)          |       4 |       1–8 |
| Gap between target messages (`request_pause_seconds`) |  0.25 s | 0.25–15 s |
| Gap between judge calls (`judge_pause_seconds`)       |  0.25 s | 0.25–60 s |

Up to 3 evaluations can run simultaneously. Use Previous results to switch between runs and stop the intended one. The server administrator can set `STUDIO_MAX_ACTIVE_RUNS` to 1–8 before startup. Run the local server with **one Uvicorn worker**; scheduling and admission limits are process-local.

Target host/port limits and pacing are shared across runs and URL paths; the strictest active settings win. Judge calls have a shared overall limit plus pacing per judge host/port, including secondary judges, evidence retries and swapped-order comparisons. Browser conversations are capped at two per host to limit memory use. Conversation IDs and history stay isolated by case; turns within a conversation remain sequential. The old forced four-second simple-setup pause is removed.

HTTP 429 applies the provider's Retry-After delay (or a five-second fallback) to future calls on that host. It does not automatically replay an answer or count missing evidence as failure. Set slower gaps/lower concurrency for small provider quotas. Studio cannot infer a provider's complete token/minute quota or traffic from other applications. Existing circuit breakers, request/run timeouts, stop controls and transactional cost reservations remain in effect. Already-dispatched calls may complete or be cancelled and may still be billed.

Speed checks run in a separate exclusive, sequential phase after quality cases. Other Studio evaluation and connection-preflight traffic waits during that phase, across all targets/runs. Waiting for workers, pacing and judge queues is excluded from recorded response duration. Report `summary[].sequential_speed` and the displayed sequential-speed average separately from all-case latency, which can include concurrent quality traffic. External traffic, server cold starts and host resource noise remain uncontrolled. The maximum run duration includes queue time, so a run can time out while waiting for the exclusive phase.

Verification: the synthetic 46-case default-set scheduler benchmark measured **39.625 s sequential versus 12.610 s parallel (3.14×)** with 0.4-second simulated target and judge operations and 0.25-second pacing. It uses one simulated exchange per case; it is not a real chatbot benchmark or a guarantee for live multi-turn/provider behavior. No provider calls are made by `python scripts/benchmark-concurrency.py`. The current authored default set has 46 cases, not the older template-padded 120.

## Visible controls and quota recovery (14 October 2026)

The main screen now contains **Tests, API provider and recovery**. Category
selection, JSON import, provider/model/key fields and the optional dollar budget
are visible outside Advanced settings. OpenAI, Gemini, Kimi (Moonshot), DeepSeek
and custom OpenAI-compatible endpoints are supported for the judge. Enter a model
available to your account; a consumer chat subscription does not establish API
credit. Provider credentials are sent only to the chosen endpoint and are not
stored in browser storage, run records or reports. Selecting another provider
clears the key and requires renewed data-sharing consent.

1. Paste your chatbot link or click **Load Reliance 509-case pack** for this local
   Reliance setup. This pack contains the original 450 scenarios/labelled wording
   variations, 49 supplied hallucination rows, and 10 mock-catalogue functional
   checks. They are not 509 independently authored scenarios or verified store facts.
2. Select categories. **Run every imported case** keeps all imported rows instead
   of truncating a category to 30. The preview shows the real planned count.
3. Choose a judge, enable the applicable message/judge/speed consents, and start.
   A blank dollar budget means no Studio dollar cap. Provider charges can exceed
   the planning estimate; this is not a billing guarantee.
4. If interrupted, open the saved run. Stop it first if active, enter the new
   judge model/key if required, and click **Resume pending cases with this judge**.
   Completed results are retained. Complete bot transcripts awaiting judgment
   can be rejudged without another bot request. Changing judge model/endpoint is
   recorded as mixed-judge evidence; it is not a like-for-like fresh benchmark.
5. In **Previous results**, choose **Delete this run** only for unwanted data and
   confirm. Other runs remain. Active runs and saved baselines are protected.
   Downloaded report files are not deleted by this action.

Quality conversations that hit a rate limit receive at most two further attempts
with a 60-second cooldown. Previous failed transcripts and all Studio request
cost events are retained. Authentication errors are not blindly retried. Speed
samples are not retried, to avoid hiding failures or changing measured latency.
The existing circuit breaker remains after persistent failures. Slow down target
and judge pacing when both share the same provider quota. Daily quota, insufficient
balance or provider outages still require account/provider action.

Cost preview distinguishes missing model prices from zero calls. For local Reliance,
the known health interface can identify the configured model when message consent
is enabled; arbitrary websites cannot expose their hidden model automatically.
Live costs use recorded token usage, including Gemini thinking tokens represented
by a gap in the provider's total. Unknown failed-call billing remains unknown, with
a known subtotal. Hidden embedding/tool calls inside a remote bot are not measured
unless the bot reports them. Planning estimates exclude these hidden calls.

Verification: Studio suite 127 passed, 1 skipped before the final rate/cost checks;
cost and recovery regression subset 24 passed; recovery/concurrency subset 14
passed; Reliance backend 20 tests passed. JavaScript syntax checked for 22 files.
Live evaluation status is read from the dashboard; these software tests do not
claim that the 509 live chatbot cases completed.
