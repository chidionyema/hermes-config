#!/bin/bash
# Self-improvement probe: finds common gaps and files structured failure entries
# Runs every 15m via cron. Silent when healthy.
set -e
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CORPUS="$HERMES_HOME/logs/self-regression-corpus.json"
PROBE_LOG="$HERMES_HOME/logs/maintenance/probe-findings.jsonl"
mkdir -p "$(dirname "$PROBE_LOG")"

FOUND=0

# Probe: Check gateway health — gateway runs as a process, NOT an HTTP server.
# The gateway process is: python -m hermes_cli.main gateway run --replace
# This is a Telegram message gateway (IPC/Unix socket), not HTTP.
GATEWAY_COUNT=$(ps aux | grep "python.*gateway" | grep -v grep | wc -l | tr -d ' ')
if [ "$GATEWAY_COUNT" -eq 0 ]; then
    echo "  ⚠️  Gateway not running"
    echo '{"source":"probe","domain":"infra/monitoring","trigger":"Gateway process not running","fix":"Start gateway: python -m hermes_cli.main gateway run --replace &","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
    FOUND=$((FOUND+1))
fi

# Only print summary if there are findings
if [ "$FOUND" -gt 0 ]; then
    echo "--- probe complete: $FOUND findings ---"
fi

# Resolution pass: close any probe findings whose conditions have cleared
if [ -f "$HERMES_HOME/scripts/alert-resolver.py" ]; then
    python3 "$HERMES_HOME/scripts/alert-resolver.py" --check "[]" --verbose 2>&1
fi
