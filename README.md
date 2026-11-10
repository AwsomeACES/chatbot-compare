# AI Agent Studio

Test one chatbot or compare up to four using the same **10 categories**. Each category runs **3 repeats** by default; change the repeat number on screen.

Studio is a **local, single-user application**. It binds to loopback (`127.0.0.1`) and keeps your results, credentials and transcripts on your own machine. It is not a hosted service and not a certification tool.

Choose **Black-box testing** for chat behavior, **Gray-box testing** for declarations, knowledge and traces, or **White-box testing** for read-only source scans. Any combination is supported. Confirm ownership or written permission before testing. [Read the short assurance guide](docs/assurance-guide.md) for inputs, evidence labels, privacy and optional scanner setup.

## What works, and what it needs

| Capability                                      | State                    | What it needs                                       |
| ----------------------------------------------- | ------------------------ | --------------------------------------------------- |
| Black-box chat testing against a running bot    | Supported                | Your bot's chat page or API link                    |
| Synthetic no-key demo                           | Supported                | Nothing beyond installation                         |
| AI Judge scoring                                | Supported, needs setup   | A cloud provider key **or** a local model in Ollama |
| Deterministic literal checks (no Judge)         | Supported                | Nothing; works with the AI Judge disabled           |
| Gray-box declarations and traces                | Supported, needs setup   | Owner declarations; optional route/trace evidence   |
| White-box source scans                          | Supported, needs setup   | Docker, plus a prepared scanner image and database  |
| Governance, audit integrity, retention, exports | Supported                | Nothing beyond installation                         |
| Human-calibrated Judge accuracy                 | **Not established**      | Real reviewer labels; see below                     |
| Native Linux and macOS startup                  | **Not qualified**        | Verified on Windows only for this candidate         |
| Optional HHEM/Qwen classifiers                  | **Disabled, unverified** | Approved model weights, installed deliberately      |

**Judges in this release are uncalibrated.** No human-label validation has been completed, so Studio does not claim measured Judge accuracy. See [Validating a Judge](docs/judge-validation.md) for the owner procedure.

## Install and start

Requires **Python 3.12**. Node.js is needed only for contributor format and lint checks, not to run Studio. Docker is optional and only used by White-box scanning.

**Windows** — open PowerShell in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

**macOS / Linux** — install Python 3.12 or newer, then:

```sh
chmod +x start.sh
./start.sh
```

The launcher creates `.venv`, installs hash-verified dependencies from `requirements.lock`, installs the Chromium browser used by the web-chat connector, copies `.env.example` to `.env` if absent, and opens **http://127.0.0.1:2708/**. Use the `-Port` parameter or the `PORT` variable to choose another port.

First install downloads dependencies and a browser, so it is bandwidth-bound rather than quick. Measured timings for this candidate are recorded in [docs/verification.md](docs/verification.md); no "five-minute setup" is promised.

## Try it without any API key

**Known limitation (10 November 2026):** the demo backend works, but the current dashboard does not yet expose the Judge-off/import flow described below. Follow [the release review](docs/release-review-20261110.md) for this and the other open fixes. Do not treat the following UI journey as verified.

Studio ships a deterministic synthetic chatbot, so you can complete a real evaluation with no provider account and no chatbot of your own.

**1.** In a second terminal, start the demo bot:

```sh
python scripts/demo_bot.py
```

It serves `http://127.0.0.1:2709/chat` and prints that address.

**2.** In Studio's **Evaluate** screen, paste `http://127.0.0.1:2709/chat` as the bot link, set the response field to `answer` under **Advanced settings**, switch the **AI judge off**, import the demo Cases from `http://127.0.0.1:2708/api/blackbox/case-set/demo`, confirm ownership, and click **Start test**.

Scoring uses the deterministic literal checks carried by those Cases, so **no provider is called and nothing is billed**. The demo deliberately includes a Case the bot fails, because a demo where everything passes would misrepresent what the tool shows you.

Measured on this candidate: 8 Cases, 8 of 8 scored with no Judge — 7 passed, 1 failed — exported as JSON and PDF, then reopened unchanged after a restart.

Demo results are **synthetic demonstration data**. They show how Results, evidence, Governance and exports behave; they are not a measurement of any real chatbot. See [the simple guide](docs/simple-guide.md) for the walkthrough.

## Normal workflow

1. Start your chatbot, then paste its chat page or complete API link.
2. Check the selected **AI judge**. Open **Change model or API key** only if you want to change it; saved settings are reused.
3. Set repeats, allow test messages and judge access, then click **Start test**.
4. Open **Results** for scores, comparison and evidence. **Tokens and cost** keeps bot and judge costs separate. Download PDF or JSON.
5. Open **Governance** for audit integrity and data controls. Use **Previous tests** to choose another result, or **Refresh history** to reload the list. Your selection stays the same across views.

**Advanced settings** are optional, collapsed controls inside Evaluate. Selecting a saved result keeps your current draft. The interface is English; original test prompts and bot answers retain their original language.

For automatic local fallback, install a model in Ollama and run `ollama serve`. On a failed judge call, Studio can discover installed text models; it never downloads weights. Explicit fallback choices take priority. Judge fallback cannot repair an unavailable chatbot API.

## How to read the results

**Not tested contributes 0 to the configured evaluation index.** Its reason and measured coverage are shown separately. An incomplete comparison has no winner. Repeats measure consistency and do not prove broad safety or fairness.

For decision limits, saved confidence settings and source-review safeguards, read [reliable comparisons](docs/comparison-reliability.md). The short default suite supports screening; a statistical winner requires enough distinct reviewed scenarios, not just more repeats.

Unknown usage and prices show **Unknown**, not $0. Hidden bot calls require that bot's own telemetry. Keys entered in password fields stay out of Git and reports. Never put credentials in reference facts or extra request JSON.

## Privacy and safety boundary

ZIPs imported through White are scanned as source inside a restricted, networkless Docker sandbox. They are never executed. Start trusted bots yourself and paste their running link for behavioral checks. Missing tools or inputs are recorded as **Not tested**. Docker is optional for normal Black and Gray use.

Private code and log review uses local Judges unless you explicitly opt in to a specific cloud use, per request. Studio never downloads model weights or pulls scanner images without your explicit action. See [SECURITY.md](SECURITY.md) for the threat boundary and how to report a vulnerability.

## Documentation

- [Simple guide](docs/simple-guide.md) — configuration, recovery, the synthetic demo and optional Docker.
- [Assurance guide](docs/assurance-guide.md) — testing modes, evidence labels and scanner setup.
- [API keys and testing-file locations](docs/api-keys.md) — independent Studio judge accounts and chatbot authentication. Studio does not need another chatbot's configuration file.
- [Reliable comparisons](docs/comparison-reliability.md) — decision limits and confidence.
- [Validating a Judge](docs/judge-validation.md) — the human-label calibration procedure.
- [Bias and governance guide](docs/bias-governance.md) — audit integrity, reproduction, retention and deletion.
- [Troubleshooting](docs/troubleshooting.md) — install, port, browser and optional-tool failures.
- [Open-source readiness](docs/open-source-readiness.md) — the release gate ledger and known limitations.
- [Architecture](docs/Architecture.md), [PRD](docs/PRD.md), [Design](docs/Design.md) and [working rules](docs/Rules.md) for contributors.
- [Shared-hosting readiness](docs/shared-hosting-readiness.md) records what multi-user hosting would require; this Studio is a local, single-user tool.
- [Previous documentation](docs/legacy-guide.md) and the older interface at `/index.html` remain available for historical runs.

Bias includes nine sub-tests under one bar. Open **Governance** to inspect audit integrity, reproduce runs, set retention or delete local results.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the locked development install, the change-to-test table and the review policy. Changes to evaluation behaviour need tests that cover failure boundaries, not only happy paths. Release steps are in [the release checklist](docs/release-checklist.md), and notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Moinuddeen Hussain.

Framework mappings to NIST AI RMF, ISO/IEC 42001 and EU AI Act themes are informational references, not certification or legal findings.
