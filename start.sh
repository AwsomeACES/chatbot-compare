#!/usr/bin/env bash
# Start from any directory. Keep credentials and runtime data local.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,12), "Install Python 3.12 or newer first."'
if [ ! -x .venv/bin/python ]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama installed. Start ollama serve and install a model to enable local fallback."
else
  echo "Ollama is optional: install it from https://ollama.com if you want a local judge."
fi
# Install the browser used by the platform-owned web chat connector.
.venv/bin/python -m playwright install chromium
export PORT="${PORT:-2708}"
.venv/bin/python scripts/open_browser.py &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
