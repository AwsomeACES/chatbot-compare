# AI Agent Studio

Local, single-user black-box chatbot evaluation on **http://127.0.0.1:2708**. Test one chatbot or compare two using conversations and evidence. Source scanning and uploaded unit-test execution are retired.

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

Default checks are hallucination, bias, guardrails and prompt injection, with 30 cases each. All 16 categories remain available under Advanced. Each includes template variations, not a guarantee of comprehensive coverage. Set a longer time limit for large suites or slow targets. Only one evaluation runs at a time.

Advanced settings hold optional API credentials, JSON fields, conversation state fields, browser selectors, reference facts, policy, scope, judge overrides and limits. Selecting more categories does not eliminate their evidence requirements.

## Automatic setup and remaining requirements

REST JSON, OpenAI-compatible chat-completions and identifiable web chat widgets are supported. Common response fields are detected. Authentication, ambiguous web controls, custom payloads or multiple target models can require a one-time Advanced setting. Arbitrary chat websites are not universally supported.

For a recognized Reliance service on localhost:8000 (or its localhost:3000 frontend), Studio configures its streaming endpoint, Gemini provider and conversation history fields. If no references were supplied for a single Reliance target, it loads the public synthetic product catalogue. These bot-supplied facts are **not independently verified retail facts**; setup notes are saved with the run and exported. Compare mode does not invent a shared reference dataset.

For other bots, upload verified prompt/reference cases to evaluate factual accuracy or business correctness. A generic Studio safety baseline is used when no policy is provided; replace it with your actual rules when needed. Scope tests require your scope description. Missing evidence stays Not tested with a reason and contributes zero.

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

Each category score is the sum of all planned case scores divided by planned cases. Not tested contributes zero. Overall is the equal-weight mean of selected categories. A missing-evidence penalty is not a measured unsafe response. AI rubric scores are estimates; they are not an independent quality certification. Pass threshold is 80. Compare runs use identical cases and swapped/randomized A/B judging; missing pairwise judgments are not ties.

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
node --check app/blackbox_static/app.js
node --check app/blackbox_static/dashboard.js
node scripts/check-simple-ui.cjs
```

The optional browser regression requires Node Playwright (`npm install --no-save playwright`) or STUDIO_PLAYWRIGHT_MODULE pointing to an installed module, Chrome, and this workspace's saved 150-case Reliance run. STUDIO_BASE_URL and STUDIO_RUN_ID can override its server and record. A fresh clone does not include private run data; use the self-contained pytest suite there. It mocks progress/compare responses in the browser to verify UI behavior; it does not store fabricated benchmark results or call an external judge. Backend tests isolate their database and exercise local protocol fixtures.

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
