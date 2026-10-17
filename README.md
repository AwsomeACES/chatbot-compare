# AI Agent Studio

[![Code quality and regression tests](https://github.com/Simali2724/AI-Agent-Testing-Studio/actions/workflows/quality.yml/badge.svg?branch=master)](https://github.com/Simali2724/AI-Agent-Testing-Studio/actions/workflows/quality.yml?query=branch%3Amaster)

Test one chatbot or compare up to four using the same **10 categories**. Each category runs **3 repeats** by default; change the repeat number on screen.

Choose **Black-box testing** for chat behavior, **Gray-box testing** for declarations, knowledge and traces, or **White-box testing** for read-only source scans. Any combination is supported. Confirm ownership or written permission before testing. [Read the short assurance guide](docs/assurance-guide.md) for inputs, evidence labels, privacy and optional scanner setup.

## Check the latest code on GitHub

Open **Actions → Code quality and regression tests → Run workflow**, select **master**, then click **Run workflow**. This starts checks for the current code. Use the status badge above to find recent runs.

**Re-run jobs** inside an older failed run tests that run's original commit and workflow again. It does not pick up later fixes. For example, historical run #3 uses `663d90d`; the dependency-isolation fix was added afterward. Old failed records keep their original result.

## Start

**Windows:** open PowerShell in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

**macOS / Linux:** install Python 3.12+, then:

```sh
chmod +x start.sh
./start.sh
```

Open **http://127.0.0.1:2708/**.

1. Start your chatbot, then paste its chat page or complete API link.
2. Check the selected **AI judge**. Open **Change model or API key** only if you want to change it; saved settings are reused.
3. Set repeats, allow test messages/judge access, then click **Start test**.
4. Open **Results** for scores, comparison and evidence. **Tokens and cost** keeps bot and judge costs separate. Download PDF or JSON.
5. Open **Governance** for audit integrity and data controls. Use **Previous tests** to choose another result, or **Refresh history** to reload the list. Your selection stays the same across views.

**Advanced settings** are optional, collapsed controls inside Evaluate. Selecting a saved result keeps your current draft. The interface is English; original test prompts and bot answers retain their original language.

For automatic local fallback, install a model in Ollama and run `ollama serve`. On a failed judge call, Studio can discover installed text models; it never downloads weights. Explicit fallback choices take priority. Judge fallback cannot repair an unavailable chatbot API.

**Not tested contributes 0 to the configured evaluation index.** Its reason and measured coverage are shown separately. An incomplete comparison has no winner. Repeats measure consistency and do not prove broad safety or fairness.

Unknown usage/prices show **Unknown**, not $0. Hidden bot calls require that bot's own telemetry. Keys entered in password fields stay out of Git and reports. Never put credentials in reference facts or extra request JSON.

ZIPs imported through White are scanned as source inside a restricted, networkless Docker sandbox. They are never executed. Start trusted bots yourself and paste their running link for behavioral checks. Missing tools or inputs are recorded as **Not tested**. Docker is optional for normal Black/Gray use.

Read [the detailed simple guide](docs/simple-guide.md) for configuration, recovery and optional Docker. [Previous documentation](docs/legacy-guide.md) and the older interface at `/index.html` remain available for historical runs.

Need to change a key? [API keys and testing-file locations](docs/api-keys.md) explains independent Studio judge accounts and chatbot authentication. Studio does not need another chatbot's .env.

[PROGRESS.md](PROGRESS.md) records changes and verification. [HANDOFF.md](HANDOFF.md) describes remaining work.

Bias now includes nine sub-tests under one bar. Open **Governance** to inspect audit integrity, reproduce runs, set retention or delete local results. See [the bias and governance guide](docs/bias-governance.md).
