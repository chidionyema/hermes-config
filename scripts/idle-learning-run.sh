#!/bin/bash
## Idle-Time Self-Improvement Pipeline (resilient).
##
## Runs autonomously during idle windows. RESILIENCE CONTRACT (Ball 16):
##   - Every phase is ISOLATED: a phase that exits non-zero is logged and the
##     pipeline CONTINUES to the next phase. One broken phase no longer aborts all.
##     (Previously `set -e` + an unguarded Phase 1 crash killed phases 2-8 every run.)
##   - On ANY phase failure the run SUBMITS to the relay queue (Otto triages it),
##     instead of only emitting a raw CRON_ERROR that alert-resolver false-clears.
##   - Every run appends a record to logs/maintenance/idle-learning-runs.jsonl so
##     idle-learning-probe.sh can fire when failures recur (>1 in 24h).
##   - Still pre-emptible (user message / runtime cap) and that is NOT a failure.
##
## Pipeline order: 0 preflight, 0.5 post-correction reflection, 1 meta-improvement,
##   2 gap-finding, 2b cross-project bridge, 2c near-miss, 3 self-regression,
##   3b self-detect, 4 policy composition, 4b conflict resolution, 5 trend,
##   6 consolidation, 7 idle curiosity, 8 postflight.

set -uo pipefail   # NOTE: no `set -e` — per-phase isolation handles errors explicitly.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
TASK_QUEUE="$HERMES_HOME/task-queue"
VENV_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
LOG_DIR="$HERMES_HOME/logs/maintenance"
META_SCRIPT="$HERMES_HOME/scripts/meta-improver.py"
RUN_LOG="$LOG_DIR/idle-learning-runs.jsonl"
STARTED_AT=$(date +%s)
MAX_RUNTIME=300

mkdir -p "$LOG_DIR"
FAILED_PHASES=()

check_preempt() {
  local elapsed=$(( $(date +%s) - STARTED_AT ))
  if [ "$elapsed" -gt "$MAX_RUNTIME" ]; then
    echo "🔄 Pre-empted: runtime exceeded ${MAX_RUNTIME}s"
    finish 0 "preempted"
  fi
}

# run_phase <label> <cmd...> — isolate a phase. Non-zero exit is recorded, never fatal.
run_phase() {
  local label="$1"; shift
  check_preempt
  echo "--- $label ---"
  "$@"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "⚠️  PHASE FAILED: $label (exit $rc) — isolated, continuing pipeline"
    FAILED_PHASES+=("${label%%:*}(rc=$rc)")
  fi
  echo ""
}

# Two phases truncate output through head; preserve the python exit via PIPESTATUS.
phase_consolidation() { $VENV_PYTHON "$HERMES_HOME/scripts/idle-consolidation.py" 2>&1 | head -20; return "${PIPESTATUS[0]}"; }
phase_curiosity()     { $VENV_PYTHON "$HERMES_HOME/scripts/idle-curiosity.py"     2>&1 | head -20; return "${PIPESTATUS[0]}"; }

# finish <exit_code> <reason> — record the run, escalate failures, exit.
finish() {
  local code="$1" reason="${2:-}"
  local failed="${FAILED_PHASES[*]:-}"
  printf '{"ts":"%s","exit":%d,"reason":"%s","failed_phases":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$code" "$reason" "$failed" >> "$RUN_LOG"
  if [ -n "$failed" ]; then
    python3 "$HERMES_HOME/scripts/hermes_queue.py" submit \
      --source idle-continuous-learning --severity warn \
      --message "idle-learning ran all phases but these failed: $failed" \
      >/dev/null 2>&1 || true
  fi
  echo "=== Idle Learning ${reason:-Complete} (exit $code) ==="
  exit "$code"
}

echo "=== Idle Learning Run — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

run_phase "Phase 0: Preflight"                $VENV_PYTHON "$META_SCRIPT" --preflight
run_phase "Phase 0.5: Post-Correction Reflection" $VENV_PYTHON "$HERMES_HOME/scripts/reflect-on-correction.py"
run_phase "Phase 1: Meta-Improvement"         $VENV_PYTHON "$META_SCRIPT" --analyze
run_phase "Phase 2: Gap-Finding"              $VENV_PYTHON "$HERMES_HOME/scripts/gap-finding.py" --report
run_phase "Phase 2b: Cross-Project Bridge"    $VENV_PYTHON "$HERMES_HOME/scripts/cross-project-bridge.py"
run_phase "Phase 2c: Near-Miss Analysis"      $VENV_PYTHON "$HERMES_HOME/scripts/near-miss-analyzer.py"
run_phase "Phase 3: Self-Regression harvest"  $VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --harvest
run_phase "Phase 3: Self-Regression report"   $VENV_PYTHON "$HERMES_HOME/scripts/self-regression.py" --report
run_phase "Phase 3b: Self-Detected Failure Scan" $VENV_PYTHON "$HERMES_HOME/scripts/self-detect.py" --scan --quiet
run_phase "Phase 4: Policy Composition analyze" $VENV_PYTHON "$HERMES_HOME/scripts/policy-composer.py" --analyze
run_phase "Phase 4: Policy Composition apply"   $VENV_PYTHON "$HERMES_HOME/scripts/policy-composer.py" --apply
run_phase "Phase 4b: Conflict Resolution"     $VENV_PYTHON "$HERMES_HOME/scripts/conflict-resolver.py" --run
run_phase "Phase 5: Trend Analysis"           $VENV_PYTHON "$HERMES_HOME/scripts/trend-analyzer.py"
run_phase "Phase 6: Policy Consolidation"     phase_consolidation
run_phase "Phase 7: Idle Curiosity"           phase_curiosity
run_phase "Phase 8: Postflight"               $VENV_PYTHON "$META_SCRIPT" --postflight

# Exit non-zero only if a phase failed — but every phase got to run first.
if [ "${#FAILED_PHASES[@]}" -gt 0 ]; then finish 1 "Complete-with-failures"; fi
finish 0 "Complete"
