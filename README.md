# AI Agent Testing Studio

Local FastAPI MVP for ZIP upload, safe archive validation, source inspection, evidence-based HTTP tests, optional pytest/coverage, security review, performance checks, SQLite persistence and HTML/JSON reports.

## Run

```powershell
Set-Location D:\AI-Agent-Testing-Studio
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Open http://127.0.0.1:8000. Use Upload Project, inspect the analysis, configure local target tests, start a run, then download the report.

## Safety

Uploaded code is untrusted. Static analysis never imports uploaded code. Existing pytest execution requires explicit consent, uses a temporary copy, bounded timeout/output and reduced environment, but is not a sandbox: filesystem and network access are not isolated. Do not run public or administrator-hosted deployments. Dependencies are never auto-installed and application startup is unsupported.

## Limits

Loopback HTTP targets only. JS/TS execution and coverage, dependency CVE database checks, tool trace verification and universal quality scores are unavailable. LLM evaluations need an API key, model and consent; otherwise they remain unavailable. Blocked and needs-review results are reported honestly.

## API

GET /api/health; POST /api/projects/upload; GET /api/projects; GET /api/projects/{id}; POST /api/projects/{id}/analyze; POST /api/projects/{id}/tests/run; GET /api/runs/{id}; GET /api/runs/{id}/results; GET /api/runs/{id}/progress; POST /api/runs/{id}/stop; GET /api/runs/{id}/report; GET /api/runs/{id}/report/download?format=html|json.
