#!/bin/bash
# Regression test for the `git status` timeout path in auto-push.sh.
#
# Root cause it locks down: the status call used `if ! CHANGES=$(timeout 30 git status ...)`.
# `timeout` SIGTERMs git, git prints nothing, so the script logged the bare line
# "git status failed: " with an empty message and exited 1 — logs/auto-push.log at
# 2026-08-18T04:01:26 and 07:01:49. rc=124 must be named, and a single slow status must be
# retried (soft_warn, run stays alive) rather than paging.
#
# The block under test is EXTRACTED FROM THE REAL SCRIPT so this cannot drift from it.
set -uo pipefail

SCRIPT="${1:-$HOME/.hermes/scripts/auto-push.sh}"
fails=0

BLOCK=$(sed -n '/^STATUS_TIMEOUT=/,/^done$/p' "$SCRIPT")
if [ -z "$BLOCK" ]; then
  echo "FAIL: could not extract the STATUS_TIMEOUT block from $SCRIPT"
  exit 1
fi

# Run the extracted block with a fake `timeout` that yields a scripted sequence of
# rc:stdout pairs, one per call. Prints the block's stdout/stderr and its exit code.
#
# The call counter lives in a FILE, not a variable: the block invokes timeout inside
# `CHANGES=$(...)`, which is a subshell, so a variable increment would be discarded and
# every call would replay the first element of the sequence.
run_block() {
  local seq="$1" cnt
  cnt=$(mktemp -t auto-push-status-test)
  echo 0 >"$cnt"
  SEQ="$seq" CNT="$cnt" bash -c '
    set -e
    log()       { printf "LOG %s\n" "$*"; }
    soft_warn() { printf "WARN: %s\n" "$*" >&2; log "WARN: $*"; }
    timeout() {
      local n spec rc out
      n=$(( $(cat "$CNT") + 1 ))
      echo "$n" >"$CNT"
      spec=$(printf "%s" "$SEQ" | cut -d"|" -f"$n")
      rc="${spec%%:*}"; out="${spec#*:}"
      [ -n "$out" ] && printf "%s\n" "$out"
      return "$rc"
    }
    sleep() { :; }   # keep the test instant; the real path sleeps 5s
    '"$BLOCK"'
    printf "CHANGES=[%s]\n" "$CHANGES"
  ' 2>&1
  local ec=$?
  printf 'EXIT=%s CALLS=%s\n' "$ec" "$(cat "$cnt")"
  rm -f "$cnt"
}

check() {
  local name="$1" out="$2" pat="$3" want="${4:-present}"
  if [ "$want" = present ]; then
    if printf '%s' "$out" | grep -qE "$pat"; then echo "  ok: $name"; else
      echo "  FAIL: $name — expected pattern /$pat/ in:"; printf '%s\n' "$out" | sed 's/^/    | /'
      fails=$((fails + 1)); fi
  else
    if printf '%s' "$out" | grep -qE "$pat"; then
      echo "  FAIL: $name — forbidden pattern /$pat/ in:"; printf '%s\n' "$out" | sed 's/^/    | /'
      fails=$((fails + 1)); else echo "  ok: $name"; fi
  fi
}

echo "case A: two consecutive rc=124 timeouts -> named failure, never a bare message"
outA=$(run_block '124:|124:')
check "retry was soft (WARN, not fatal, on attempt 1)" "$outA" 'WARN: git status timed out after 90s \(attempt 1\), retrying'
check "final message names the timeout and the count"  "$outA" 'git status timed out after 90s x2'
check "exits 1"                                        "$outA" 'EXIT=1'
check "no bare empty-message line"                     "$outA" 'git status failed: *$' absent
check "gave up after exactly 2 attempts"               "$outA" 'CALLS=2'

echo "case B: rc=124 once, then success -> run survives, CHANGES captured"
outB=$(run_block '124:|0: M cron/jobs.json')
check "warned once"        "$outB" 'WARN: git status timed out after 90s \(attempt 1\), retrying'
check "exits 0"            "$outB" 'EXIT=0'
check "CHANGES populated"  "$outB" 'CHANGES=\[ M cron/jobs.json\]'
check "no fatal line"      "$outB" 'x1|x2' absent
check "took exactly 2 attempts" "$outB" 'CALLS=2'

echo "case C: real git error (rc=128) -> fatal immediately, message preserved"
outC=$(run_block '128:fatal: Unable to create index.lock: File exists')
check "names rc and reason" "$outC" 'git status failed \(rc=128\): fatal: Unable to create index.lock'
check "exits 1"             "$outC" 'EXIT=1'
check "did NOT retry"       "$outC" 'retrying' absent
check "exactly 1 attempt"   "$outC" 'CALLS=1'

echo "case D: clean tree, first try -> exits 0, no warning at all"
outD=$(run_block '0:')
check "exits 0"      "$outD" 'EXIT=0'
check "no WARN"      "$outD" 'WARN' absent

if [ "$fails" -eq 0 ]; then
  echo "PASS: auto-push status-timeout retry behaves (4 cases)"
  exit 0
fi
echo "FAIL: $fails assertion(s) failed"
exit 1
