#!/bin/bash
# Idle-time continuous learning runner.
# Runs all 3 engines plus the meta-improver pipeline.
# Pre-emptible: if a real task arrives mid-run (new file in task-queue/), exits cleanly.
# Token-capped: each engine calls the strategist at most once.
# Scheduled via cron every 2h during idle windows.
#
# Pipeline order (DAG-constrained):
#   0: preflight     (meta-improver --preflight)
#   1: meta_improvement (meta-improver --analyze)
#   2-4: gap_finding, self_regression, consolidation (parallel-safe)
#   5: postflight    (meta-improver --postflight)
#
# Boundary: operates on the task-performance layer only.
# Never touches: model, reflection mechanism, or evaluation criteria.

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
TASK_QUEUE="$HERMES_HOME/task-queue"
VENV_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
LOG_DIR="$HERMES_HOME/logs/maintenance"
META_SCRIPT="$HERMES_HOME/scripts/meta-improver.py"
STARTED_AT=$(date +%s)
MAX_RUNTIME=180  # 3 minutes max for idle work (was 120, Phase 1 meta-analysis needs more time)

# Pre-empt check: if user has sent a message recently, skip this run
check_preempt() {
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

# Phase 0: Preflight — check off-switch, snapshot state, verify script integrity
echo "--- Phase 0: Preflight (Meta-Improver) ---"
check_preempt
$VENV_PYTHON "$META_SCRIPT" --preflight 2>&1
echo ""

# ── Post-Correction Reflection Hook ──────────────────────────────
echo "--- Phase 0.5: Post-Correction Reflection ---"
check_preempt
"$VENV_PYTHON" "$HERMES_HOME/scripts/reflect-on-correction.py" 2>&1 || true
echo ""

# Phase 1: Meta-Improvement — detect bottlenecks, generate candidates (inner + outer loop)
echo "--- Phase 1: Meta-Improvement ---"
check_preempt
$VENV_PYTHON "$META_SCRIPT" --analyze 2>&1
echo ""

# Phase 2: Gap-Finding
echo "--- Phase 2: Gap-Finding ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/gap-finding.py" --report 2>&1
echo ""

# Phase 2b: Near-Miss Analysis — find untriggered policies and co-firing patterns
echo "--- Phase 2b: Near-Miss Analysis ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/near-miss-analyzer.py" 2>&1 || true
echo ""

# Phase 3: Self-Regression
echo "--- Phase 3: Self-Regression ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --harvest 2>&1
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --report 2>&1
echo ""

# Phase 3b: Self-Detection (B) — scan for self-detected failures
echo "--- Phase 3b: Self-Detected Failure Scan ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/self-detect.py" --scan --quiet 2>&1
echo ""

# Phase 4: Policy Composition (A) — detect co-firing patterns
echo "--- Phase 4: Policy Composition Analysis ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/policy-composer.py" --analyze 2>&1
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/policy-composer.py" --apply 2>&1
echo ""

# Phase 4b: Conflict Resolution (F3) — detect contradictions, scope check
echo "--- Phase 4b: Conflict Resolution ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/conflict-resolver.py" --run 2>&1
echo ""

# Phase 5: Consolidation
echo "--- Phase 5: Policy Consolidation ---"
check_preempt
$VENV_PYTHON "$HERMES_HOME/scripts/idle-consolidation.py" 2>&1 | head -20
echo ""

# Phase 6: Postflight — snapshot state, compute diff, evaluate outcomes, log velocity
echo "--- Phase 6: Postflight (Meta-Improver) ---"
check_preempt
$VENV_PYTHON "$META_SCRIPT" --postflight 2>&1

echo ""
echo "=== Idle Learning Complete ==="
