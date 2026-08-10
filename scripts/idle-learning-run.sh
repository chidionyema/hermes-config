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
# MAX_RUNTIME must sit BELOW the cron hard cap (120s) or check_preempt is dead code:
# the scheduler SIGKILLs at 120s long before a 300s internal cap can fire, so the
# run dies mid-phase with no graceful "preempted" record. 100s leaves headroom for
# finish() to write the run log. PHASE_TIMEOUT bounds any SINGLE phase so one hung
# phase can't eat the whole budget before the between-phase check_preempt runs.
MAX_RUNTIME="${HERMES_IDLE_MAX_RUNTIME:-100}"
PHASE_TIMEOUT="${HERMES_IDLE_PHASE_TIMEOUT:-30}"
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

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
  # Bound each phase with `timeout --kill-after` so a hung phase is SIGKILLed (it
  # and its process group) instead of running until the cron cap. --kill-after
  # guarantees the group dies even if it ignores SIGTERM — no orphaned children.
  # `timeout` execs a binary, so it can't wrap a shell function (the two phases
  # that pipe through head): run those directly — their python is still bounded by
  # the between-phase check_preempt.
  if [ -n "$TIMEOUT_BIN" ] && ! declare -F "$1" >/dev/null 2>&1; then
    "$TIMEOUT_BIN" -s TERM --kill-after=5 "$PHASE_TIMEOUT" "$@"
  else
    "$@"
  fi
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "⚠️  PHASE FAILED: $label (exit $rc) — isolated, continuing pipeline"
    if [ "$rc" -eq 124 ]; then
      # rc=124 is `timeout`'s SIGTERM code — it says the phase ran out of WALL
      # clock, not that it is broken. Measured 2026-08-10: Phase 0a/0b exit 0 in
      # 8s/15s standalone, and every rc=124 clustered in a window where the
      # 12-CPU host ran at 1-min loadavg 115-283. Capture the load AT the moment
      # of the timeout so finish() can tell host starvation from a code fault.
      local load1
      load1=$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $2+0}')
      FAILED_PHASES+=("${label%%:*}(rc=124,load=${load1:-0})")
    else
      FAILED_PHASES+=("${label%%:*}(rc=$rc)")
    fi
  fi
  echo ""
}

# Two phases truncate their output for the log. `cmd | head -20` does NOT do that
# safely: once the writer exceeds the 64 KB pipe buffer, head has already exited and
# the writer takes SIGPIPE — CPython then fails to flush sys.stdout at shutdown and
# exits **120**. PIPESTATUS faithfully reports that 120, so a phase that did all its
# work and saved its report is recorded as FAILED and escalated to the relay queue.
# Measured 2026-08-07: idle-consolidation.py emits 1,847 lines, exits 0 unpiped and
# 120 through `head -20`; it only started failing on 2026-08-06T20:19Z, when the
# policy near-duplicate list pushed the report past the buffer. Nothing broke — the
# report grew. Phase 7 survives only by luck (35 lines fits one write).
# Write in full, truncate the DISPLAY, return the process's real exit status.
_run_truncated() {
  local out rc
  out="$(mktemp -t hermes-phase)"
  "$@" > "$out" 2>&1
  rc=$?
  head -20 "$out"
  rm -f "$out"
  return "$rc"
}
phase_consolidation() { _run_truncated "$VENV_PYTHON" "$HERMES_HOME/scripts/idle-consolidation.py"; }
phase_curiosity()     { _run_truncated "$VENV_PYTHON" "$HERMES_HOME/scripts/idle-curiosity.py"; }

# finish <exit_code> <reason> — record the run, escalate failures, exit.
finish() {
  local code="$1" reason="${2:-}"
  local failed="${FAILED_PHASES[*]:-}"
  printf '{"ts":"%s","exit":%d,"reason":"%s","failed_phases":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$code" "$reason" "$failed" >> "$RUN_LOG"
  if [ -n "$failed" ]; then
    # The old text said "ran all phases" unconditionally. A run that ends in
    # finish 0 "preempted" did NOT run all phases, so the alert was factually
    # false and pointed diagnosis at the phase scripts. Report the real reason.
    local source="idle-continuous-learning" severity="warn"
    # If EVERY failure is a timeout and the host was over-subscribed (>2x ncpu)
    # when it fired, this is host starvation, not a code fault: route it as info
    # under its own source so the actionable target is the box.
    local ncpu thresh all_124=1 max_load=0 entry load_part
    ncpu=$(sysctl -n hw.ncpu 2>/dev/null || echo 1)
    thresh=$(( ncpu * 2 ))
    for entry in "${FAILED_PHASES[@]:-}"; do
      case "$entry" in
        *"(rc=124,load="*)
          load_part="${entry##*load=}"; load_part="${load_part%)}"
          load_part="${load_part%%.*}"; load_part="${load_part:-0}"
          if [ "$((load_part + 0))" -gt "$((max_load + 0))" ]; then max_load="$load_part"; fi
          ;;
        *) all_124=0 ;;
      esac
    done
    if [ "$all_124" -eq 1 ] && [ "$((max_load + 0))" -gt "$((thresh + 0))" ]; then
      source="idle-learning-host-starvation"; severity="info"
    fi
    python3 "$HERMES_HOME/scripts/hermes_queue.py" submit \
      --source "$source" --severity "$severity" \
      --message "idle-learning [${reason:-unknown}] failed phases: $failed" \
      >/dev/null 2>&1 || true
  fi
  echo "=== Idle Learning ${reason:-Complete} (exit $code) ==="
  exit "$code"
}

echo "=== Idle Learning Run — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

# Kill-switch honesty: absent OFF_SWITCH = DISARMED. Do not mutate policies/corpus.
if [ ! -f "$HERMES_HOME/meta/OFF_SWITCH" ]; then
  echo "⛔ OFF_SWITCH absent — self-improvement DISARMED; idle-learning no-op."
  finish 0 "disarmed"
fi

run_phase "Phase 0: Preflight"                $VENV_PYTHON "$META_SCRIPT" --preflight
# Round F preflight: resilience checks (DB health + ticks rotation)
run_phase "Phase 0a: Resilience Preflight"      $VENV_PYTHON "$HERMES_HOME/scripts/resilience.py" --check
# Round D preflight: predictive scan
run_phase "Phase 0b: Predictor Scan"            $VENV_PYTHON "$HERMES_HOME/scripts/predictor.py" --all
run_phase "Phase 0.5: Post-Correction Reflection" $VENV_PYTHON "$HERMES_HOME/scripts/reflect-on-correction.py"
run_phase "Phase 1: Meta-Improvement"         $VENV_PYTHON "$META_SCRIPT" --analyze
run_phase "Phase 2: Gap-Finding"              $VENV_PYTHON "$HERMES_HOME/scripts/gap-finding.py" --report
run_phase "Phase 2.5: Ops Monitor"            $VENV_PYTHON "$HERMES_HOME/scripts/ops-monitor.py" --check all --json
# Round H2: Simulated agent traffic for policy firing
run_phase "Phase 2.6: Agent Simulator"        $VENV_PYTHON "$HERMES_HOME/scripts/agent_simulator.py" --run 3
run_phase "Phase 2.7: Auto-Fixer"             $VENV_PYTHON "$HERMES_HOME/scripts/auto_fixer.py" --fix --json
run_phase "Phase 2b: Cross-Project Bridge"    $VENV_PYTHON "$HERMES_HOME/scripts/cross-project-bridge.py"
run_phase "Phase 2c: Near-Miss Analysis"      $VENV_PYTHON "$HERMES_HOME/scripts/near-miss-analyzer.py"
run_phase "Phase 2d: Self-Audit (always)"     $VENV_PYTHON "$HERMES_HOME/scripts/self-audit.py" --force
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
# Round F3: backup verification
run_phase "Phase 8a: Backup Verification"      $VENV_PYTHON "$HERMES_HOME/scripts/resilience.py" --verify-backups
# Round H3: score regression check
run_phase "Phase 8b: Score Regression"         $VENV_PYTHON "$HERMES_HOME/scripts/score_driver.py" --regression

# Exit non-zero only if a phase failed — but every phase got to run first.
if [ "${#FAILED_PHASES[@]}" -gt 0 ]; then finish 1 "Complete-with-failures"; fi
finish 0 "Complete"
