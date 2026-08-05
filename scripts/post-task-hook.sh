#!/bin/bash
# post-task-hook.sh — Called after every Hermes task completes.
# Records the outcome and runs a quick constitutional check.
#
# Usage (in your task completion flow):
#   scripts/post-task-hook.sh "<task-id>" "<domain>" <exit-code> ["<stderr>"]
#
# This is the bridge between task execution and the self-improvement system.

TASK_ID="${1:-unknown}"
DOMAIN="${2:-unknown}"  
EXIT_CODE="${3:-0}"
STDERR="${4:-}"

cd "$HOME/.hermes" || exit 1

python3 scripts/integration.py \
    --task-outcome \
    --task-id "$TASK_ID" \
    --domain "$DOMAIN" \
    --exit-code "$EXIT_CODE" \
    --stderr "$STDERR" \
    2>/dev/null

# Only log on failures to avoid noise
if [ "$EXIT_CODE" != "0" ]; then
    echo "[post-task] $TASK_ID ($DOMAIN): exit=$EXIT_CODE" >> logs/post-task.log
fi
