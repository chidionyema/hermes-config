#!/bin/bash
## test-idle-learning-load-gate.sh — acceptance test for idle-learning admission control.
##
## Proves the four behaviours added on 2026-08-13 in response to
## "idle-learning [preempted] failed phases: Phase 3(rc=124,load=317.06)":
##   T1  syntax is valid
##   T2  --check-load is a read-only dry gate (DEFER / PROCEED, no side effects)
##   T3  --check-load answers even when self-improvement is DISARMED
##   T4  the load comparison is NUMERIC, not string ("100" vs "99" is the tell)
##   T5  startup admission gate defers instead of launching phases, and records it
##   T6  check_preempt defers MID-RUN when the host degrades after start
##   T7  finish() stays SILENT for a one-off starvation, escalates on recurrence,
##       and still submits normally for non-starvation failures
##
## Exit 0 = all pass. Non-zero = the count of failed assertions.

set -uo pipefail

SCRIPT="${HERMES_HOME:-$HOME/.hermes}/scripts/idle-learning-run.sh"
FAILS=0
PASSES=0

ok()   { PASSES=$((PASSES + 1)); echo "  PASS  $1"; }
bad()  { FAILS=$((FAILS + 1));   echo "  FAIL  $1"; echo "        got: $2"; }
check(){ # check <name> <haystack> <needle>
  case "$2" in *"$3"*) ok "$1";; *) bad "$1" "$(echo "$2" | tr '\n' '|')";; esac
}

# A throwaway HERMES_HOME so no test ever touches the live run-log or queue.
make_sandbox() {
  local d; d="$(mktemp -d -t idlegate)"
  mkdir -p "$d/meta" "$d/logs/maintenance" "$d/scripts"
  : > "$d/meta/OFF_SWITCH"              # ARMED
  cat > "$d/scripts/hermes_queue.py" <<'PY'
import sys, os
# stub: record the submit instead of spawning a strategist claude -p
open(os.environ["SUBMIT_LOG"], "a").write(" ".join(sys.argv[1:]) + "\n")
PY
  echo "$d"
}

echo "=== idle-learning load-gate acceptance ==="
echo "script: $SCRIPT"
[ -f "$SCRIPT" ] || { echo "FATAL: $SCRIPT missing"; exit 99; }

# ── T1 syntax ──────────────────────────────────────────────────────────────
if out=$(bash -n "$SCRIPT" 2>&1); then ok "T1 bash -n clean"; else bad "T1 bash -n clean" "$out"; fi

# ── T2 dry gate, both verdicts, no side effects ────────────────────────────
SB=$(make_sandbox); RL="$SB/logs/maintenance/idle-learning-runs.jsonl"
echo '{"ts":"2000-01-01T00:00:00Z","exit":0,"reason":"seed","failed_phases":""}' > "$RL"
before=$(wc -l < "$RL")
out=$(HERMES_HOME="$SB" HERMES_IDLE_MAX_LOAD=0 bash "$SCRIPT" --check-load 2>&1); rc=$?
check "T2a --check-load says DEFER when saturated" "$out" "DEFER load="
[ "$rc" -eq 0 ] && ok "T2b --check-load exits 0" || bad "T2b --check-load exits 0" "rc=$rc"
out2=$(HERMES_HOME="$SB" HERMES_IDLE_MAX_LOAD=999999 bash "$SCRIPT" --check-load 2>&1)
check "T2c --check-load says PROCEED when idle" "$out2" "PROCEED load="
case "$out$out2" in *"Phase"*) bad "T2d dry gate runs no phase" "$out$out2";; *) ok "T2d dry gate runs no phase";; esac
after=$(wc -l < "$RL")
[ "$before" -eq "$after" ] && ok "T2e dry gate appends no run-log record" \
  || bad "T2e dry gate appends no run-log record" "$before -> $after"
[ ! -f "$SB/submits.txt" ] && ok "T2f dry gate submits nothing" || bad "T2f dry gate submits nothing" "$(cat "$SB/submits.txt")"

# ── T3 dry gate reachable while DISARMED ───────────────────────────────────
rm -f "$SB/meta/OFF_SWITCH"
out=$(HERMES_HOME="$SB" HERMES_IDLE_MAX_LOAD=0 bash "$SCRIPT" --check-load 2>&1)
check "T3 --check-load answers when DISARMED" "$out" "DEFER load="
case "$out" in *DISARMED*) bad "T3b dry gate precedes OFF_SWITCH branch" "$out";; *) ok "T3b dry gate precedes OFF_SWITCH branch";; esac
: > "$SB/meta/OFF_SWITCH"

# ── T4 numeric, not string, comparison ─────────────────────────────────────
# "100" > "99" is FALSE as strings and TRUE as integers. A string compare here is
# exactly the class of bug that produced a wrong finding on 2026-08-06.
(
  export HERMES_HOME="$SB"
  # shellcheck disable=SC1090
  source "$SCRIPT"
  sysctl() { echo "{ 100.00 90.00 80.00 }"; }
  MAX_LOAD=99
  [ "$(host_load)" = "100" ] || { echo "T4-load-parse:$(host_load)"; exit 3; }
  host_saturated || exit 4
  MAX_LOAD=101
  host_saturated && exit 5
  exit 0
)
case $? in
  0) ok "T4 load compared numerically (100>99 saturated, 100<101 not)";;
  3) bad "T4 load compared numerically" "host_load did not print 100";;
  4) bad "T4 load compared numerically" "load=100 max=99 NOT flagged saturated (string compare)";;
  5) bad "T4 load compared numerically" "load=100 max=101 wrongly flagged saturated";;
  *) bad "T4 load compared numerically" "unexpected rc";;
esac

# ── T5 startup admission gate ──────────────────────────────────────────────
SB2=$(make_sandbox); RL2="$SB2/logs/maintenance/idle-learning-runs.jsonl"
out=$(HERMES_HOME="$SB2" HERMES_IDLE_MAX_LOAD=0 SUBMIT_LOG="$SB2/submits.txt" bash "$SCRIPT" 2>&1); rc=$?
check "T5a startup gate defers" "$out" "Deferred: 1-min load"
[ "$rc" -eq 0 ] && ok "T5b deferred run exits 0" || bad "T5b deferred run exits 0" "rc=$rc"
case "$out" in *"--- Phase"*) bad "T5c no phase launched into a saturated host" "$out";; *) ok "T5c no phase launched into a saturated host";; esac
check "T5d run-log records deferred-host-load" "$(cat "$RL2")" '"reason":"deferred-host-load"'
[ ! -f "$SB2/submits.txt" ] && ok "T5e deferral submits nothing" || bad "T5e deferral submits nothing" "$(cat "$SB2/submits.txt")"

# ── T6 mid-run deferral ────────────────────────────────────────────────────
out=$(
  export HERMES_HOME="$SB2"
  # shellcheck disable=SC1090
  source "$SCRIPT"
  sysctl() { echo "{ 317.06 300.00 250.00 }"; }
  MAX_LOAD=24
  check_preempt
  echo "NOT-DEFERRED"
)
check "T6a check_preempt defers mid-run" "$out" "Deferred mid-run: load 317"
case "$out" in *NOT-DEFERRED*) bad "T6b mid-run defer terminates the run" "$out";; *) ok "T6b mid-run defer terminates the run";; esac

# ── T7 finish(): starvation silence vs recurrence vs normal failure ────────
starv='{"ts":"TS","exit":0,"reason":"preempted","failed_phases":"Phase 3(rc=124,load=317.06)"}'
now_line() { echo "${starv/TS/$(date -u +%Y-%m-%dT%H:%M:%SZ)}"; }

run_finish() { # run_finish <n_recent_starved_lines> <failed_phase_entry>
  local n="$1" entry="$2" sb; sb=$(make_sandbox)
  local rl="$sb/logs/maintenance/idle-learning-runs.jsonl"
  : > "$rl"
  local i; for ((i = 0; i < n; i++)); do now_line >> "$rl"; done
  # a stale (>24h) starved line must NOT count
  echo "${starv/TS/2020-01-01T00:00:00Z}" >> "$rl"
  (
    export HERMES_HOME="$sb" SUBMIT_LOG="$sb/submits.txt"
    # shellcheck disable=SC1090
    source "$SCRIPT"
    FAILED_PHASES=("$entry")
    finish 0 "preempted"
  ) >/dev/null 2>&1
  echo "$sb"
}

sb=$(run_finish 2 "Phase 3(rc=124,load=317.06)")   # +this run = 3 => <=3 => silent
[ ! -f "$sb/submits.txt" ] && ok "T7a one-off starvation (3/24h) submits NOTHING" \
  || bad "T7a one-off starvation (3/24h) submits NOTHING" "$(cat "$sb/submits.txt")"

sb=$(run_finish 4 "Phase 3(rc=124,load=317.06)")   # +this run = 5 => >3 => warn
if [ -f "$sb/submits.txt" ]; then
  check "T7b recurring starvation submits" "$(cat "$sb/submits.txt")" "idle-learning-host-starvation"
  check "T7c recurring starvation severity=warn" "$(cat "$sb/submits.txt")" "--severity warn"
else
  bad "T7b recurring starvation submits" "no submit recorded"; bad "T7c recurring starvation severity=warn" "no submit"
fi

sb=$(run_finish 0 "Phase 1(rc=1)")                 # non-starvation => unchanged
if [ -f "$sb/submits.txt" ]; then
  check "T7d non-starvation failure still submits" "$(cat "$sb/submits.txt")" "idle-continuous-learning"
  check "T7e non-starvation severity=warn" "$(cat "$sb/submits.txt")" "--severity warn"
else
  bad "T7d non-starvation failure still submits" "no submit recorded"; bad "T7e non-starvation severity=warn" "no submit"
fi

echo ""
echo "=== $PASSES passed, $FAILS failed ==="
exit "$FAILS"
