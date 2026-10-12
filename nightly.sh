#!/usr/bin/env bash
# Nightly regression check: start any bot that isn't running, run every bot that has a baseline (regress.py run),
# then stop the bots this script started. The report goes to runs/nightly.log and, when REGRESSION_WEBHOOK is set
# (e.g. in .env), to that Slack-style webhook. Exit code is regress.py's: 0 clean, 1 warnings, 2 critical, 3 error.
#
# Install (2 a.m. every night):  crontab -e, then add
#   0 2 * * * ~/projects/chatbot-compare/nightly.sh >> ~/projects/chatbot-compare/runs/nightly.log 2>&1
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECTS="$(dirname "$HERE")"
LOGS="$HERE/runs/bot-logs"
mkdir -p "$LOGS"
started=()
# The free Gemini key (GOOGLE_API_KEY) lives in this project's .env; the bots get it in their environment, so their
# own .env files need no key.
set -a; [ -f "$HERE/.env" ] && . "$HERE/.env"; set +a

up() { curl -s -m 3 -o /dev/null "http://localhost:$1/"; }

start() { # port, name, directory, command...
  local port=$1 name=$2 dir=$3; shift 3
  if up "$port"; then return; fi
  if [ ! -d "$dir" ]; then echo "$name: $dir not found, not started"; return; fi
  (cd "$dir" && exec "$@" >> "$LOGS/$name.log" 2>&1) &
  started+=($!)
  for _ in $(seq 1 30); do up "$port" && { echo "$name started on :$port"; return; }; sleep 2; done
  echo "$name did not come up on :$port (see $LOGS/$name.log)"
}

stop_started() { for pid in "${started[@]}"; do kill "$pid" 2>/dev/null; done; }
trap stop_started EXIT

echo "=== $(date '+%F %T') nightly regression check"
start 11434 ollama "$HERE" ollama serve  # VoltKart's free local model
start 8000 voltkart "$PROJECTS/reliance-digital-chatbot" .venv/bin/uvicorn app:app --port 8000
HUSSAIN="$PROJECTS/hussain-bot/digital-multi-agent-ai-main/backend"
start 8001 hussain "$HUSSAIN" env RAG_DATA_ROOT="$HUSSAIN/../data" CHROMA_PATH="$HUSSAIN/../data/chroma_db" \
  "$HERE/.bots/reliance222-venv/bin/uvicorn" main:app --port 8001
# Mouni's GitHub version, on its own test database (the adapter closes finished test chats there)
start 5000 mouni "$PROJECTS/mouni-bot/github-latest/backend" env GEMINI_API_KEY="${GOOGLE_API_KEY:-}" \
  DATABASE_URL=sqlite:///compare-test.db AI_PROVIDER=gemini GEMINI_MODEL=gemini-3.6-flash .venv-local/bin/python app.py

cd "$HERE" && .venv/bin/python regress.py run "$@"
status=$?
.venv/bin/python compliance.py purge  # retention policy in governance.json (keeps baselines and signed-off runs)
exit $status
