#!/bin/bash
# Idle-time continuous learning runner.
# Runs all 3 engines: consolidation → regression → gap-finding.
# Pre-emptible: if a real task arrives mid-run (new file in task-queue/), exits cleanly.
# Token-capped: each engine calls the strategist at most once.
# Scheduled via cron every 2h during idle windows.
#
# Boundary: operates on the task-performance layer only.
# Never touches: model, reflection mechanism, or evaluation criteria.

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
TASK_QUEUE="$HERMES_HOME/task-queue"
VENV_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
LOG_DIR="$HERMES_HOME/logs/maintenance"
STARTED_AT=$(date +%s)
MAX_RUNTIME=120  # 2 minutes max for idle work

# Pre-empt check: if user has sent a message recently, skip this run
check_preempt() {
  # Check if too long since idle — skip if user sent a message in last 5 min
  LAST_MSG=$(find "$HERMES_HOME/logs/gateway.log" -mmin -5 2>/dev/null | head -1)
  if [ -n "$LAST_MSG" ]; then
    echo "🔄 Pre-empted: gateway activity in last 5 min — not idle"
    exit 0
  fi
  
  # Hard runtime cap
  ELAPSED=$(( $(date +%s) - STARTED_AT ))
  if [ "$ELAPSED" -gt "$MAX_RUNTIME" ]; then
    echo "🔄 Pre-empted: runtime exceeded $MAX_RUNTIME seconds"
    exit 0
  fi
}

echo "=== Idle Learning Run — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

mkdir -p "$LOG_DIR"

# Phase 1: Idle Consolidation
echo "--- Phase 1: Policy Consolidation ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/idle-consolidation.py" 2>&1 | head -20
echo ""

# Phase 2: Self-Regression
echo "--- Phase 2: Self-Regression ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --harvest 2>&1
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --report 2>&1
echo ""

# Phase 3: Gap-Finding
echo "--- Phase 3: Gap-Finding ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/gap-finding.py" --report 2>&1

echo ""
echo "=== Idle Learning Complete ==="
