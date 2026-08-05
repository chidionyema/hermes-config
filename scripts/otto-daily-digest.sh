#!/bin/bash
# 9am briefing: yesterday's prospector stats, cron health, engine status, top
# actions. Sends itself to Telegram via `hermes send`, which reuses the
# gateway's own credentials and needs no agent loop.
#
# Why this wrapper exists (2026-08-05): the cron job `otto-daily-digest` carried
#   "command": "python3 ~/.hermes/scripts/daily-digest.py | hermes send --to telegram"
# and cron/scheduler.py never reads "command" (see otto-db-cleanup.sh for the
# full diagnosis). The job reported ok daily and sent nothing. The pipe is kept
# here rather than moved to the scheduler's `deliver` field because this job has
# no `origin` block, so deliver=origin would fail to resolve a target.
#
# stdout is deliberately left empty on success: the send already happened, and a
# no_agent job with empty stdout is a silent run rather than a duplicate message.
set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DIGEST="$(/usr/local/bin/python3 "$HERMES_HOME/scripts/daily-digest.py")"
if [ -z "${DIGEST//[[:space:]]/}" ]; then
    echo "daily-digest.py produced no output — nothing sent" >&2
    exit 1
fi
printf '%s' "$DIGEST" | "$HOME/.local/bin/hermes" send --to telegram >/dev/null
