# Reading and maintaining the Studio

Start with `app/main.py`, then `app/blackbox_app.py`. The frontend is plain HTML,
CSS and JavaScript. Node is only needed for development checks, not serving the app.
Generated runtime data and third-party dependencies are not maintained source.

Read these first: [docs/Architecture.md](docs/Architecture.md) maps the components,
[docs/PRD.md](docs/PRD.md) defines intended behaviour, [docs/Design.md](docs/Design.md)
records the actual screens, and [docs/Rules.md](docs/Rules.md) holds the working rules,
the change-to-test table and the definition of done. Current work is in
[docs/tasks.md](docs/tasks.md).

## Code map

| Module                                                      | Responsibility                                                  |
| ----------------------------------------------------------- | --------------------------------------------------------------- |
| `app/blackbox_app.py`                                       | FastAPI endpoints, admission, settings, imports and exports     |
| `app/blackbox/schema.py`                                    | Validated target, judge and run settings                        |
| `app/blackbox/easy_setup.py`, `readiness.py`                | Simple defaults and prerequisite preview                        |
| `app/blackbox/catalog.py`, `cases/`                         | Scenario selection, provenance and case data                    |
| `app/blackbox/runner.py`                                    | Run lifecycle, case execution, persistence and summaries        |
| `app/blackbox/scheduling.py`                                | Shared concurrency, pacing and exclusive speed phases           |
| `app/blackbox/connectors.py`                                | HTTP, SSE and browser conversations                             |
| `app/blackbox/judge.py`, `deterministic.py`, `evidence.py`  | Rubric judging, exact assertions and supporting quotes          |
| `app/blackbox/comparisons.py`, `baselines.py`               | Pairwise confidence and regression snapshots                    |
| `app/blackbox/metering.py`, `pricing.py`, `cost_summary.py` | Attempt ledger, budget reservations, price snapshots and totals |
| `app/blackbox/reports.py`                                   | PDF and JSON report content                                     |
| `app/database.py`                                           | SQLite persistence and connection lifetime                      |
| `app/blackbox_static/`                                      | Setup, progress, evidence, charts and costs                     |
| `tests/`                                                    | Local fixture-based regressions                                 |
| `app/blackbox/governance.py`, `governance_routes.py`        | Audit chain, consent, retention, redaction and overrides        |
| `app/blackbox/demo_bot.py`, `scripts/demo_bot.py`           | Deterministic synthetic demo bot and its Cases                  |
| `app/assurance/`                                            | Gray-box and White-box engines, intake and scanner evidence     |
| `scripts/package_release.py`                                | Validated source-only ZIP export                                |
| `scripts/check_docs.py`                                     | Requirement coverage and local document links                   |

## Run lifecycle

1. Validate settings and preview prerequisites.
2. `build_cases()` selects authored/imported/reference cases and records missing
   requirements. It never creates passing filler cases.
3. `make_run()` records planned slots. `execute()` delegates to `EvaluationExecutor`,
   whose mutable state belongs to one run.
4. Discover target interfaces, collect quality conversations under shared limits,
   judge answers and compare the same case evidence across targets.
5. Speed tests use exclusive sequential access. `finish()` saves results, explains
   missing work and releases resources on execution exit paths.
6. Aggregate quality separately from coverage and export saved evidence.

## Development setup

Install from the **hash-locked** requirements so every contributor and CI resolve
the same versions. Do not install the unpinned `requirements-dev.txt` directly;
regenerate the locks with `scripts/lock_dependencies.py` when a dependency changes.

**Windows (PowerShell)**, from the repository folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe -m playwright install chromium
npm ci --ignore-scripts --no-audit --no-fund
```

**macOS and Linux**:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m playwright install chromium
npm ci --ignore-scripts --no-audit --no-fund
```

CI uses Python 3.12 and Node 24. Optional model engines are not needed for core
tests. **Never copy a production `.env` into fixtures**, and never point tests at a
real chatbot or a paid provider.

Substitute `.venv/bin/python` for `.\.venv\Scripts\python.exe` in every command
below if you are not on Windows.

## Format and check

```powershell
.\.venv\Scripts\python.exe -m ruff format app tests scripts sample_project
.\.venv\Scripts\python.exe -m ruff check --fix app tests scripts sample_project
npm run format
```

Before submitting:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts sample_project
.\.venv\Scripts\python.exe -m ruff check app tests scripts sample_project
npm run format:check
npm run check:js
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check-exact-compare.py
```

The browser check starts an isolated server on port 2710 and closes it afterward.
Keep that port free. It uses synthetic results and makes no paid calls. Older
`check-*.cjs` scripts may target retired screens or specific local installations;
formatting/parsing them does not establish compatibility with today's UI. CI runs
the current isolated browser check only.

## Conventions

- Four-space Python indentation, one statement per line; Ruff targets 100 columns.
  Split long prose literals without changing their values.
- Two-space frontend indentation with Prettier. Do not hand-minify maintained code.
- Use named helpers with one responsibility. Explain non-obvious constraints,
  such as preserving evidence on cancellation, rather than commenting every line.
- Preserve public functions and stored schemas during readability changes.
  Add regression coverage for behavior changes.
- Keep Not tested distinct from failure. Disclose missing evidence, unknown cost,
  consent requirements and incomplete coverage.
- Record supported decisions in `DECISIONS.md`; give incomplete capabilities an
  explicit task and acceptance criteria in `BACKLOG.md`.
- Do not format/package `.venv/`, `node_modules/`, `runtime/`, credentials or
  generated reports. Use the source exporter instead of zipping the working folder.

## Your first contribution

The demo needs no account and exercises the whole path, so it is the quickest way to
see Studio working before you change anything:

1. Install with the locked requirements above.
2. Start Studio, and start the demo bot in a second terminal with
   `python scripts/demo_bot.py`.
3. Follow [the demo walkthrough](docs/simple-guide.md) and look at Results,
   Governance and both exports.
4. Run `python -m pytest -q` once so you know the suite is green before your change.

Good first changes: a new demo Case in `app/blackbox/demo_bot.py`, a clearer error
message, a document fix, or a test that covers an existing failure boundary. Please
avoid a first pull request that changes scoring, the Judge rubric or saved schemas —
those need a recorded decision and a migration plan.

## Contribution workflow

1. **Open an issue first** for anything beyond a typo, using the bug or feature
   template. Agreeing the boundary before coding saves rework.
2. **Branch** from `master`. Use a short descriptive name; agent-created branches
   use a `codex/` prefix.
3. **Work in small phases.** Keep the diff reviewable and scoped to one concern.
4. **Add tests that can fail.** A test that passes against the unfixed code proves
   nothing. State which boundary it exercises.
5. **Run the checks** in the section above, plus the targeted tests the
   change-to-test table in [docs/Rules.md](docs/Rules.md#tests-and-definition-of-done)
   names for your change.
6. **Update the documents** your change affects, and run `python scripts/check_docs.py`.
7. **Open a pull request** using the template. Paste the commands you ran and their
   real output, including anything you could not verify.

### Review policy

This is a small project with a single maintainer, so expect review to be
asynchronous and occasionally slow. A pull request is merged when:

- The behaviour change is understood and wanted, and its scope matches an issue.
- Tests cover the change and its failure paths, and the full suite passes.
- Implemented versus Planned boundaries stay truthful in both code and documents.
- No check was turned from **Not tested** into a pass without new evidence, and no
  unknown cost became zero.
- Formatter, linter and the documents checker pass.

A pull request that weakens an assertion, skips a failing test, or widens the release
manifest in order to get a green run will be asked to change course rather than
merged. If a gate genuinely needs to move, say so explicitly and explain why.

**Licensing.** Contributions are accepted under the repository's
[MIT license](LICENSE). Only submit work you have the right to contribute.

## Adding a connector, scenario set or Judge

[docs/Rules.md](docs/Rules.md#extension-guides) holds the step-by-step extension
guides and the privacy boundaries each one must respect. In summary:

- **A connector** goes in `app/blackbox/connectors.py`, keeps one session per
  conversation, keeps turns sequential, routes every call through the existing
  metering and scheduling layers, and classifies a transport failure as a
  connector failure rather than a quality defect.
- **A scenario set or Category** is versioned configuration under `app/studio/`
  and `app/blackbox/cases/`. Increment the protocol version, preserve saved Run
  snapshots, and never count repeats or paraphrases as independent coverage.
- **A Judge model or provider** is catalogue metadata in
  `app/studio/settings.json` plus credentials through `judge_credentials.py` and
  requests through `metering.completion()`. Model IDs must come from real account
  or installed-model discovery. Add a price to editable configuration or the cost
  stays **Unknown** — never hardcode a rate in evaluation code, and never change
  the bot's model because its Judge failed.
- **An Engine** implements `required_inputs`, `plan` and async `run` in
  `app/assurance/`, returning the real `Finding` schema. There is no auto-discovered
  plugin registry; registration is explicit.
