# Reading and maintaining the Studio

Start with `app/main.py`, then `app/blackbox_app.py`. The frontend is plain HTML,
CSS and JavaScript. Node is only needed for development checks, not serving the app.
Generated runtime data and third-party dependencies are not maintained source.

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
| `scripts/package_release.py`                                | Validated source-only ZIP export                                |

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

## Development setup (PowerShell)

From the repository folder, after creating `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
npm ci --ignore-scripts --no-audit --no-fund
```

CI uses Python 3.12 and Node 24. Optional model engines are not needed for core
tests. Never copy a production `.env` into fixtures.

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
