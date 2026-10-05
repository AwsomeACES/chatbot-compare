param([int]$Port=2708)
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv; & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt }
if (-not (Test-Path '.env')) { Copy-Item .env.example .env }
Write-Host "AI Agent Testing Studio: http://127.0.0.1:$Port"
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port $Port

