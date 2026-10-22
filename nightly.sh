#!/usr/bin/env bash
# Nightly regression check: start any bot server that isn't running (the "servers" in bots.json), run every bot that
# has a baseline (regress.py run), then stop the servers this script started. The report goes to runs/nightly.log
# and, when REGRESSION_WEBHOOK is set (e.g. in .env), to that Slack-style webhook. Exit code is regress.py's:
# 0 clean, 1 warnings, 2 critical, 3 error.
#
# Install (2 a.m. every night):  crontab -e, then add
#   0 2 * * * ~/projects/chatbot-compare/nightly.sh >> ~/projects/chatbot-compare/runs/nightly.log 2>&1
# Or, on an always-on Linux host, the systemd timer in deploy/ (see README, "Nightly off the laptop").
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 3
# The free Gemini key (GOOGLE_API_KEY) lives in this project's .env; the servers get it in their environment, so
# their own .env files need no key.
set -a; [ -f "$HERE/.env" ] && . "$HERE/.env"; set +a

export SERVERS_PIDS_FILE="$HERE/runs/nightly-servers.pids"  # "down" stops only the servers this script started

echo "=== $(date '+%F %T') nightly regression check"
.venv/bin/python servers.py up
trap '.venv/bin/python servers.py down' EXIT

.venv/bin/python regress.py run "$@"
status=$?
.venv/bin/python compliance.py purge  # retention policy in governance.json (keeps baselines and signed-off runs)
.venv/bin/python compliance.py anchor --reason nightly  # the audit log's head, off this machine (webhook / S3)
exit $status
