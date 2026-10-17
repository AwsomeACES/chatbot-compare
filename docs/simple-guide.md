# AI Agent Studio — simple guide

Test one bot, or compare up to four bots. The English-only interface has three areas: **Evaluate**, **Results**, and **Governance**. Technical options stay closed until you need them.

1. In **Evaluate**, select **Black-box testing**, **White-box testing**, or **Gray-box testing**. You can combine them. Chat tests need a running bot link; source checks need a ZIP or public repository. Source checks read code without running it.
2. Add your bot. Use **Add another bot** for comparisons. For chat tests, keep the saved AI judge or open **Change model or API key**. Source-only checks do not need an AI judge.
3. Set **Repeat each test** (default three), confirm permission and any required AI access, then select **Start test**. **View tests and customize repeats** lets you set different repeat counts. **Advanced settings** holds reference facts, safety rules and storage settings.
4. In **Results**, choose a previous test or follow the current one. Open a check for its reason, evidence and next step. **Download report** exports a PDF; **More actions** contains data download, repeat and delete. **Governance** contains the audit and retention controls.

Original bot answers and uploaded evidence keep their original language; interface labels and guidance use English. All ten chat categories remain available, including the nine Bias sub-tests. Simplifying the interface does not change scoring, remove tests or delete saved data.

## Start

Windows: open PowerShell in this folder and run `powershell -ExecutionPolicy Bypass -File .\run.ps1`.

macOS/Linux: install Python 3.12+, then run `./start.sh`. If the downloaded file has no executable permission, run `chmod +x start.sh` once. It creates a virtual environment, installs dependencies and Chromium, checks for Ollama and opens the Studio. Internet is needed during installation. Native macOS/Linux startup has not been verified on this Windows host.

Open **http://127.0.0.1:2708/**. For chat-answer testing, your chatbot must already be running. Paste its chat page or complete API URL. If automatic detection fails, open **Connection settings (optional)** and specify message/response fields or browser selectors. The Studio cannot connect to every proprietary interface automatically.

Choose one or more judges. Enter a model your account supports and its key in the password box. Keys are never saved in browser storage or reports. Save independent provider keys in Studio's own .env (see [API setup](api-keys.md)); each selected judge reuses only its matching provider key. No chatbot credentials file is required. Claude uses LiteLLM's Anthropic transport; the API connection must be checked with your account before a benchmark.

For local judging: install Ollama, run `ollama serve`, and install a suitable model yourself (`ollama pull <model>`). Reload Studio; installed model names are listed. Tick a local model and **Use only as a backup judge** if it should be used only when another judge fails. Studio never downloads models automatically. Local compute time is not free electricity or hardware; its API token charge can be zero.

Allow test messages and AI review, then click **Start test**. During testing, change your model/key under **Change model or API key**, then use **Update judges for this run**. Existing calls keep the previous judge; subsequent cases use your selection. After a stop or crash, **Resume test** keeps prior scores, transcripts and cost events. Target API keys may need re-entry after restart; credentials are not stored in the database.

## Understanding results

Ten base scenarios cover accuracy, injection, jailbreak, guardrails, bias, memory, language, personal data, unnecessary refusal and uncertainty. Repeated answers measure consistency, not broad independent coverage. Upload verified reference facts for factual accuracy; without them the accuracy scenario only checks an unsupported premise.

The configured overall index is a weighted mean of scenario scores across planned repeats. **Not tested contributes zero**, with its reason and tested quality/coverage separately disclosed. Zero for missing evidence does not prove the bot answered unsafely. A comparison winner is withheld when evidence is incomplete or the scenario-cluster confidence interval includes a tie. Ten scenarios provide limited confidence and do not certify production safety.

Expand any check to read the prompts, actual answers, judge explanation and exact evidence. Evidence quotes still undergo the existing validation. Human reviews require an explanation, preserve the previous verdict and appear in the audit log. Audit records judge models, prompt, configuration, price snapshot, provider errors, fallback and manual changes. Temperature is zero, but providers may still be nondeterministic; a model alias does not prove a fixed provider revision.

Tokens and dollar costs are shown separately for bots and judges, as bars and a table. Missing telemetry/prices are **Unknown**, not $0. Internal bot tools, embeddings and hidden retries need that bot's own instrumentation. Prices are snapshots in `app/pricing/seed.json` and may need refresh.

## Configuration and development

- `app/studio/settings.json`: ten categories, repeats, weights, tie margin, judge options and execution limits. Bias prompts are in `app/studio/bias-v1.json`.
- `app/blackbox/studio_engine.py`: repeat building, multi-judge fallback, summary and governance.
- `app/blackbox/studio_routes.py`: simple workflow, live judge changes and human review.
- `app/blackbox_static/simple.*`: accessible offline UI and charts.
- Existing backend connectors, metering, retries, storage and reports remain in `app/blackbox/`.
- Legacy interface and datasets remain at `/index.html` for old runs.
- Run `python -m pytest tests/test_simple_studio.py tests/test_recovery_controls.py tests/test_costs.py` and `ruff check app tests` / `ruff format --check app tests`.

The evaluator attempts every scheduled case with timeouts and bounded retries. It can finish processing with Not tested entries when a bot/judge is unavailable. It cannot guarantee 100% valid judgments during provider outages. User stops and run deadlines intentionally remain effective.

ZIPs are validated and stored, never executed on the host. This release has no isolated ZIP application runner. Optional Docker hosts the Studio only and does not provide a ZIP sandbox. Run trusted projects separately; an untrusted-code sandbox is a separate implementation task.

Optional Docker: copy `.env.example` to `.env`, configure your own keys, then `docker compose up --build`. Results persist in a named volume. Bot links must be accessible inside the container; use `host.docker.internal` for host services. Change local judge URL in settings for Docker. This is a local single-user tool; do not expose it publicly.

Promptfoo was not added: existing LiteLLM adapters and black-box connector/runner reuse already cover this protocol, so a second runner would duplicate metering and governance.

For current subtype scoring, hash-chain governance, reproduction, privacy, retention, caches and batching, read [the bias and governance guide](bias-governance.md).
