#!/bin/bash
# Proves ~/.hermes/scripts/runaway-reaper.sh matches on ARGV+AGE only, kills what
# it matches, spares what it must not, and writes a jsonl receipt per kill.
#
# All target processes are spawned BY THIS TEST and are harmless sleepers/greps
# over a temp dir. Age thresholds are lowered via the reaper's env knobs so the
# test does not have to wait 300s.
set -uo pipefail

REAPER="${HERMES_HOME:-$HOME/.hermes}/scripts/runaway-reaper.sh"
WORK="$(mktemp -d -t reaper-test)"
LOGDIR="$WORK/home/logs/maintenance"
mkdir -p "$WORK/corpus" "$LOGDIR"
for i in 1 2 3; do echo "needle-not-here" > "$WORK/corpus/f$i.txt"; done
ln -s /bin/sleep "$WORK/pi"
ln -s /bin/sleep "$WORK/chrome-headless-shell"

PASS=0; FAIL=0
ok()  { echo "  PASS $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1"; FAIL=$((FAIL+1)); }
alive() { kill -0 "$1" 2>/dev/null; }

cleanup() {
  for p in "${SPAWNED[@]:-}"; do [ -n "$p" ] && kill -KILL "$p" 2>/dev/null; done
  rm -rf "$WORK"
}
trap cleanup EXIT

SPAWNED=()

# --- positive controls -------------------------------------------------------
# a recursive grep that will not finish on its own (reads a fifo)
mkfifo "$WORK/never"
grep -r "needle" "$WORK/never" >/dev/null 2>&1 &
GREP_REC=$!; SPAWNED+=("$GREP_REC")
"$WORK/pi" 300 & PI=$!; SPAWNED+=("$PI")
"$WORK/chrome-headless-shell" 300 & CHROME=$!; SPAWNED+=("$CHROME")

# --- negative controls -------------------------------------------------------
# non-recursive grep (-v): same binary, no recursive flag -> must be spared
grep -v "needle" "$WORK/never" >/dev/null 2>&1 &
GREP_NONREC=$!; SPAWNED+=("$GREP_NONREC")
# a plain sleep with an unremarkable argv -> must be spared
/bin/sleep 300 & INNOCENT=$!; SPAWNED+=("$INNOCENT")

sleep 3   # let every child appear in ps with a non-zero etime

export HERMES_HOME="$WORK/home"

echo "=== STEP 1: --dry-run must MATCH the 3 hogs and kill nothing ==="
DRY="$(REAPER_GREP_MAX_AGE=1 REAPER_PI_MAX_AGE=1 REAPER_CHROME_MAX_AGE=1 \
       bash "$REAPER" --dry-run 2>&1)"
echo "$DRY" | sed 's/^/  | /'
[[ "$DRY" == *"pid=$GREP_REC "* ]]     && ok "matched recursive grep ($GREP_REC)"      || bad "recursive grep ($GREP_REC) not matched"
[[ "$DRY" == *"pid=$PI "* ]]           && ok "matched stale pi ($PI)"                  || bad "pi ($PI) not matched"
[[ "$DRY" == *"pid=$CHROME "* ]]       && ok "matched chrome-headless-shell ($CHROME)" || bad "chrome ($CHROME) not matched"
[[ "$DRY" != *"pid=$GREP_NONREC "* ]]  && ok "spared non-recursive grep -v ($GREP_NONREC)" || bad "grep -v ($GREP_NONREC) wrongly matched"
[[ "$DRY" != *"pid=$INNOCENT "* ]]     && ok "spared innocent sleep ($INNOCENT)"       || bad "innocent sleep ($INNOCENT) wrongly matched"
alive "$GREP_REC" && ok "dry-run killed nothing" || bad "dry-run KILLED pid $GREP_REC"

echo "=== STEP 2: thresholds respected — young hogs are spared ==="
YOUNG="$(REAPER_GREP_MAX_AGE=99999 REAPER_PI_MAX_AGE=99999 REAPER_CHROME_MAX_AGE=99999 \
         bash "$REAPER" --dry-run 2>&1)"
echo "$YOUNG" | sed 's/^/  | /'
[[ "$YOUNG" == *"matched=0"* ]] && ok "age gate holds (matched=0 under high thresholds)" \
                               || bad "age gate leaked: $YOUNG"

echo "=== STEP 3: real run must reap the 3 hogs and spare the 2 controls ==="
REAL="$(REAPER_GREP_MAX_AGE=1 REAPER_PI_MAX_AGE=1 REAPER_CHROME_MAX_AGE=1 REAPER_GRACE=3 \
        bash "$REAPER" 2>&1)"
echo "$REAL" | sed 's/^/  | /'
sleep 1
alive "$GREP_REC"    && bad "recursive grep ($GREP_REC) SURVIVED"     || ok "recursive grep reaped"
alive "$PI"          && bad "pi ($PI) SURVIVED"                       || ok "stale pi reaped"
alive "$CHROME"      && bad "chrome ($CHROME) SURVIVED"               || ok "chrome-headless-shell reaped"
alive "$GREP_NONREC" && ok "non-recursive grep still alive (spared)"  || bad "grep -v ($GREP_NONREC) was killed"
alive "$INNOCENT"    && ok "innocent sleep still alive (spared)"      || bad "innocent sleep ($INNOCENT) was killed"

echo "=== STEP 4: jsonl receipts ==="
RECEIPTS="$LOGDIR/runaway-reaper.jsonl"
if [ -s "$RECEIPTS" ]; then
  cat "$RECEIPTS" | sed 's/^/  | /'
  python3 - "$RECEIPTS" "$GREP_REC" "$PI" "$CHROME" <<'PY'
import json, sys
path, *pids = sys.argv[1:]
recs = [json.loads(l) for l in open(path) if l.strip()]
logged = {r["pid"] for r in recs}
missing = [p for p in map(int, pids) if p not in logged]
fields_ok = all({"ts","pid","age_s","rule","signal","argv"} <= set(r) for r in recs)
print("  PASS every reaped pid has a receipt" if not missing else f"  FAIL no receipt for {missing}")
print("  PASS receipts carry ts/pid/age_s/rule/signal/argv" if fields_ok else "  FAIL receipt missing fields")
sys.exit(0 if (not missing and fields_ok) else 1)
PY
  if [ $? -eq 0 ]; then PASS=$((PASS+2)); else FAIL=$((FAIL+1)); fi
else
  bad "no receipts written to $RECEIPTS"
fi

echo
echo "test_runaway_reaper: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
