# Troubleshooting

Purpose: resolve the failures a new installation actually hits.
Last updated: 2026-11-09.

Every failure below is reported by Studio as a readable error or as **Not tested** with a reason. A missing optional tool never becomes a pass.

## Contents

- [Installation and startup](#installation-and-startup)
- [The port is already in use](#the-port-is-already-in-use)
- [Browser and connector failures](#browser-and-connector-failures)
- [Judge and provider failures](#judge-and-provider-failures)
- [White-box scanner prerequisites](#white-box-scanner-prerequisites)
- [Results, history and exports](#results-history-and-exports)

## Installation and startup

**`py` or `python3` is not found.** Install Python 3.12 from python.org and reopen the terminal. On Windows `run.ps1` calls `py -3.12`; verify with `py -0p`. On macOS and Linux `start.sh` uses `python3` and refuses anything below 3.12; override the interpreter with `PYTHON=/path/to/python3.12 ./start.sh`.

**PowerShell refuses to run the launcher.** Use the documented form, which does not change your machine policy:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

**The dependency install fails on a hash mismatch.** `requirements.lock` pins exact hashes. A mismatch means the download was altered or truncated, or the lock was edited by hand. Delete `.venv`, retry, and if it persists report it — do not remove `--require-hashes` to work around it.

**The install fails behind a proxy or offline.** The first install needs network access to PyPI and to the Chromium download. There is no bundled offline installer.

**A path with spaces or non-ASCII characters.** Supported. Both launchers quote their own paths. If you invoke Python yourself, quote the path: `& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app`.

**`start.sh` is not executable.** Run `chmod +x start.sh`. If the file has Windows line endings after copying between machines, the shell reports a `\r` error; `.gitattributes` keeps it LF in the repository.

## The port is already in use

Studio binds `127.0.0.1:2708`. If something else holds that port, uvicorn exits with an address-in-use error.

Choose another port:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Port 2709
```

```sh
PORT=2709 ./start.sh
```

Find the current holder with `netstat -ano | findstr :2708` on Windows or `lsof -i :2708` elsewhere. Do not run two Studio instances against the same runtime folder; the SQLite database expects a single writer.

## Browser and connector failures

**Chromium is missing.** The web-chat connector drives a real browser. Install it inside the environment:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

On Linux you may also need system libraries; `python -m playwright install-deps chromium` lists them. Without Chromium, API-link targets still work — only the chat-page connector is unavailable, and it reports that rather than scoring zero.

**The bot link is rejected.** Paste either the chat page or the complete API endpoint, including the scheme. Studio validates the target before sending traffic and refuses a link it cannot classify.

**The bot's transport fails mid-Run.** A transport failure is recorded as such against the affected Cases rather than scored as a quality defect. Studio does not currently classify every individual HTTP status from a target bot into a distinct connector state; a per-status connector taxonomy is tracked as future work in [tasks.md](tasks.md).

## Judge and provider failures

Studio separates the chatbot under test from the Judge that evaluates it. A Judge failure never changes the target model.

| Condition                  | What Studio reports                        | Your action                                 |
| -------------------------- | ------------------------------------------ | ------------------------------------------- |
| Rejected authentication    | Auth failure with the provider identity    | Re-enter the key in the password field      |
| Exhausted billing or quota | The distinct exhausted state, not a pass   | Add credit, or switch to a local Judge      |
| Transient rate limit       | A bounded cooldown and retry               | Wait; do not retry in a loop                |
| Uncallable model           | Discoverable rather than ready             | Pick a model your account can actually call |
| Unusable verdict           | Insufficient reliable evidence, Not tested | Inspect the raw output in Results           |

**No key at all.** Run the synthetic demo, or disable the AI Judge and use deterministic literal checks. Both work with no provider account.

**Local fallback.** Install Ollama, run `ollama serve`, and install a text model. Studio discovers installed models; it never downloads weights by itself. A local fallback is recorded with its own identity and cost treatment, so a report never implies the originally requested Judge ran.

## White-box scanner prerequisites

White-box scanning needs Docker plus a deliberately prepared scanner image and vulnerability database. Studio does not pull images or enable scanner networking for you.

Prepare them with `scripts/prepare_scanner_data.py`, then re-run the scan. Until the image and database exist, every affected check stays **Not tested** with setup guidance. A completed scanner that found no supported target is also not a pass.

An unresolved dependency version is never reported as a confirmed installed vulnerable version.

## Results, history and exports

**History is empty.** Expected before the first Run. Use **Refresh history** after a Run completes.

**A Run looks incomplete.** Stopped and resumed Runs keep partial evidence and state which Cases were never scored. Resume reuses the checkpoint only for the exact same Run, bot, Case, repeat and prompt; a new Run or a new repeat always calls the bot afresh.

**PDF export fails or takes too long.** Rendering is bounded. A report whose evidence is too large to render returns an actionable error instead of hanging, and the JSON export remains available with the same data.

**Costs show Unknown.** Intended. An unknown price, unknown usage or a failed-but-possibly-billed call stays **Unknown** rather than becoming $0. Only a genuinely known zero shows zero.

**A saved result will not open.** Malformed or partially written saved data is reported as such instead of rendering a blank screen. Governance can delete a specific local result when you choose to.
