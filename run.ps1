param(
    [int]$Port = 2708
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# First-time setup only. Existing local configuration is preserved.
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & .\.venv\Scripts\python.exe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path '.env')) {
    Copy-Item .env.example .env
}

$env:PORT = "$Port"
Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\python.exe" -ArgumentList 'scripts/open_browser.py' -WindowStyle Hidden
Write-Host "AI Agent Testing Studio: http://127.0.0.1:$Port"
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
