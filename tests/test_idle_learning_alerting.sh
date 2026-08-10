#!/bin/bash
# Proves the two idle-learning-run.sh alerting fixes against the REAL code:
#   1. finish() reports the actual run reason (never "ran all phases" for a
#      preempted run).
#   2. run_phase() stamps the 1-min loadavg onto an rc=124 failure, and finish()
#      downgrades an all-timeout run on an over-subscribed host to
#      --source idle-learning-host-starvation --severity info.
#
# It does NOT copy the logic: it loads the real script's header (everything above
# the first `run_phase` invocation) so the functions under test are the shipped
# ones, then drives them with a stub hermes_queue.py and a stub `sysctl`.
set -uo pipefail

REAL="${HERMES_HOME:-$HOME/.hermes}/scripts/idle-learning-run.sh"
WORK="$(mktemp -d -t idle-alert-test)"
trap 'rm -rf "$WORK"' EXIT

# --- carve out the function definitions (real bytes, no edits) ---------------
CUT=$(grep -n '^echo "=== Idle Learning Run' "$REAL" | head -1 | cut -d: -f1)
[ -n "$CUT" ] || { echo "FAIL: could not locate pipeline start in $REAL"; exit 1; }
head -n $((CUT - 1)) "$REAL" > "$WORK/lib.sh"

# --- fake HERMES_HOME with a stub queue that records its argv ----------------
mkdir -p "$WORK/home/scripts" "$WORK/home/logs/maintenance"
cat > "$WORK/home/scripts/hermes_queue.py" <<'PY'
import sys, os
with open(os.environ["STUB_OUT"], "w") as fh:
    fh.write("\x00".join(sys.argv[1:]))
PY

# run_case <name> <fake_1min_load> <phase-spec...>  -> prints the captured argv
run_case() {
  local name="$1" load="$2"; shift 2
  local out="$WORK/$name.argv"
  STUB_OUT="$out" HERMES_HOME="$WORK/home" HERMES_IDLE_PHASE_TIMEOUT=1 \
  FAKE_LOAD="$load" CASE_SPEC="$*" bash -c '
    source "'"$WORK"'/lib.sh"
    # override sysctl so the test controls loadavg / ncpu deterministically
    sysctl() {
      case "$2" in
        # real format is "{ <1min> <5min> <15min> }" -- the 1-min value is the
        # FIRST number, which is awk field $2 (field $1 is the literal "{").
        vm.loadavg) echo "{ $FAKE_LOAD 0.20 0.30 }" ;;
        hw.ncpu)    echo 12 ;;
      esac
    }
    for spec in $CASE_SPEC; do
      case "$spec" in
        timeout) run_phase "Phase T: hang" sleep 5 ;;
        fail1)   run_phase "Phase F: broken" /usr/bin/false ;;
      esac
    done
    finish 0 "preempted"
  ' >/dev/null 2>&1
  tr '\000' ' ' < "$out"; echo
}

PASS=0; FAIL=0
check() { # check <label> <haystack> <needle>
  if [[ "$2" == *"$3"* ]]; then echo "  PASS $1"; PASS=$((PASS+1));
  else echo "  FAIL $1 -- expected to contain: $3"; echo "        got: $2"; FAIL=$((FAIL+1)); fi
}
check_not() {
  if [[ "$2" != *"$3"* ]]; then echo "  PASS $1"; PASS=$((PASS+1));
  else echo "  FAIL $1 -- must NOT contain: $3"; echo "        got: $2"; FAIL=$((FAIL+1)); fi
}

echo "CASE 1: all-timeout on starved host (load 300 > 2x12)"
A="$(run_case case1 300 timeout)"
echo "  argv: $A"
check     "source is host-starvation" "$A" "--source idle-learning-host-starvation"
check     "severity is info"          "$A" "--severity info"
check     "message states reason"     "$A" "idle-learning [preempted] failed phases:"
check     "load stamped on rc=124"    "$A" "(rc=124,load=300)"
check_not "no false 'ran all phases'" "$A" "ran all phases"

echo "CASE 2: all-timeout on IDLE host (load 3 < 2x12) stays a warn"
B="$(run_case case2 3 timeout)"
echo "  argv: $B"
check "source unchanged" "$B" "--source idle-continuous-learning"
check "severity warn"    "$B" "--severity warn"

echo "CASE 3: genuine non-timeout failure stays a warn even on a starved host"
C="$(run_case case3 300 fail1)"
echo "  argv: $C"
check "source unchanged" "$C" "--source idle-continuous-learning"
check "severity warn"    "$C" "--severity warn"
check "rc recorded"      "$C" "Phase F(rc=1)"

echo "CASE 4: mixed timeout + real failure is NOT downgraded"
D="$(run_case case4 300 "timeout fail1")"
echo "  argv: $D"
check "source unchanged" "$D" "--source idle-continuous-learning"
check "severity warn"    "$D" "--severity warn"

echo
echo "test_idle_learning_alerting: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
