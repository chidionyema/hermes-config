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

# ADMISSION CONTROL (2026-08-13). The phases are not the defect — the host is.
# Measured: 12-CPU box at 1-min loadavg 317-405 while legitimate estate work ran
# (vitest, pytest, prospector generate, several `claude`). runaway-reaper.sh cannot
# and must not reap those (its contract is ARGV+age: recursive grep >300s, `pi`
# >3600s, chrome-headless >1800s — hence `matched=0 ... load=368.19`). The correct
# response to legitimate load is to DEFER, not to reap and not to keep launching
# 30s-bounded phases that get SIGTERMed at rc=124.
NCPU=$(sysctl -n hw.ncpu 2>/dev/null || echo 1)
MAX_LOAD="${HERMES_IDLE_MAX_LOAD:-$((NCPU * 2))}"

# host_load — 1-min loadavg as an INTEGER. The `+0` coercion is mandatory: awk and
# `[` compare as STRINGS unless an operand is numeric, and that produced a wrong
# threshold finding on 2026-08-06.
host_load() {
  local l
  l=$(sysctl -n vm.loadavg 2>/dev/null | awk '{printf "%d", $2+0}')
  echo "${l:-0}"   # empty (sysctl absent) must not become a `[ "" -gt N ]` syntax error
}
host_saturated() { [ "$(host_load)" -gt "$MAX_LOAD" ]; }

mkdir -p "$LOG_DIR"
FAILED_PHASES=()

check_preempt() {
  local elapsed=$(( $(date +%s) - STARTED_AT ))
  if [ "$elapsed" -gt "$MAX_RUNTIME" ]; then
    echo "🔄 Pre-empted: runtime exceeded ${MAX_RUNTIME}s"
    finish 0 "preempted"
  fi
  # Defer mid-run too: the host can saturate AFTER a clean start, and without this
  # the pipeline burns one 30s SIGTERM cycle per remaining phase on a dying box.
  if host_saturated; then
    echo "⏸  Deferred mid-run: load $(host_load) > ${MAX_LOAD}"
    finish 0 "deferred-host-load"
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
# --apply added 2026-08-17. Without it, idle-consolidation.py:300 sets apply=False and the
# whole promotion path is a dry run: it prints "Would promote" and changes nothing. Measured
# that day: pol-auto-fix-coordinator (hits=8 helped=7 hurt=0) and pol-auto-fix-cron
# (hits=7 helped=7 hurt=0) both sat provisional against PROMOTE_MIN_HITS=3, and the only
# policy ever promoted (pol-auto-fix-config_push, 2026-08-05) was promoted by a hand-run.
# So the learning loop counted gaps and never closed one. Phase 4 above already passes
# --apply to policy-composer.py; this line was the odd one out with no reason recorded.
# The evidence bar and the fence still apply: apply_promotions promotes only on
# hits>=PROMOTE_MIN_HITS with helped>hurt, and fences anything touching a guarded term.
phase_consolidation() { _run_truncated "$VENV_PYTHON" "$HERMES_HOME/scripts/idle-consolidation.py" --apply; }
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
    local submit=1
    if [ "$all_124" -eq 1 ] && [ "$((max_load + 0))" -gt "$((thresh + 0))" ]; then
      source="idle-learning-host-starvation"; severity="info"
      # SELF-AMPLIFYING NOISE (2026-08-13): every submit here spawns a strategist
      # `claude -p` — i.e. the host-starvation alert ADDS load to the starved host
      # (measured 35.1% CPU in `ps -Ao pcpu,rss,etime,command -r`). A single
      # starvation event is normal cohabitation, not an incident. Only escalate
      # once it RECURS: >3 starved runs in 24h.
      local starvation_recent
      starvation_recent=$(python3 - "$RUN_LOG" <<'PY' 2>/dev/null || echo 0
import json, sys
from datetime import datetime, timezone
cut = datetime.now(timezone.utc).timestamp() - 86400
n = 0
try:
    fh = open(sys.argv[1])
except OSError:
    print(0); raise SystemExit
for line in fh:
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
        ts = datetime.strptime(o["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        continue
    if ts >= cut and "rc=124,load=" in str(o.get("failed_phases", "")):
        n += 1
print(n)
PY
)
      starvation_recent="${starvation_recent:-0}"
      if [ "$((starvation_recent + 0))" -gt 3 ]; then
        severity="warn"   # recurring => a real host problem, escalate
      else
        submit=0          # one-off cohabitation => stay silent, add no load
      fi
      echo "ℹ️  host-starvation: ${starvation_recent} starved run(s)/24h (submit=${submit})"
    fi
    if [ "$submit" -eq 1 ]; then
      python3 "$HERMES_HOME/scripts/hermes_queue.py" submit \
        --source "$source" --severity "$severity" \
        --message "idle-learning [${reason:-unknown}] failed phases: $failed" \
        >/dev/null 2>&1 || true
    fi
  fi
  echo "=== Idle Learning ${reason:-Complete} (exit $code) ==="
  exit "$code"
}

# Sourcing this file defines the helpers WITHOUT running the pipeline, so
# host_load/host_saturated/finish are unit-testable. Under `bash script` or an
# exec from cron, BASH_SOURCE[0] == $0, so the pipeline runs exactly as before.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

# Read-only dry gate. Deliberately BEFORE the OFF_SWITCH check so it answers even
# when self-improvement is disarmed. Runs no phase, writes no $RUN_LOG record and
# never calls hermes_queue.py.
if [ "${1:-}" = "--check-load" ]; then
  if host_saturated; then
    echo "DEFER load=$(host_load) max=$MAX_LOAD"
  else
    echo "PROCEED load=$(host_load) max=$MAX_LOAD"
  fi
  exit 0
fi

echo "=== Idle Learning Run — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

# Kill-switch honesty: absent OFF_SWITCH = DISARMED. Do not mutate policies/corpus.
if [ ! -f "$HERMES_HOME/meta/OFF_SWITCH" ]; then
  echo "⛔ OFF_SWITCH absent — self-improvement DISARMED; idle-learning no-op."
  finish 0 "disarmed"
fi

# Startup admission control: never launch 30s-bounded phases into a saturated host.
# FAILED_PHASES is empty here, so finish() writes the run-log record and submits nothing.
if host_saturated; then
  echo "⏸  Deferred: 1-min load $(host_load) > ${MAX_LOAD} (ncpu=${NCPU})"
  finish 0 "deferred-host-load"
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
