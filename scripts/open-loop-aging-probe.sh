#!/bin/bash
# open-loop-aging-probe — follow-through for the mentor lesson of 2026-08-18
# ("Otto racks up open loops because it starts new tasks without closing the
# last one"). The relay queue tracked open vs resolved but never AGE, so open
# fingerprints piled up silently. This probe is the receipt for the new
# `hermes_queue.py stale` check, and then runs it against the real estate.
#
#   1. a FRESH fingerprint is not stale          -> exit 0
#   2. a BACK-DATED fingerprint is stale         -> exit 2, name printed
#   3. after `resolve`, the stale check is clean -> exit 0
#
# Self-test runs in an isolated HERMES_HOME (same idiom as dropped-ball-probe.sh
# and closed-loop-proof.sh) so it never touches the real queue. The final
# section reads the REAL queue and escalates one aggregate event when open loops
# are aging; the probe's own exit code stays driven by the self-test.
set -u
SC="$HOME/.hermes/scripts"
Q="$SC/hermes_queue.py"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

TMP=$(mktemp -d)
mkdir -p "$TMP/queue"
export HERMES_HOME="$TMP"

FRESH="synthetic-fresh-loop"
OLD="synthetic-old-loop"

python3 "$Q" submit --source synthetic-probe --severity warn \
  --message "fresh synthetic open loop" --fingerprint "$FRESH" >/dev/null
python3 "$Q" submit --source synthetic-probe --severity warn \
  --message "old synthetic open loop" --fingerprint "$OLD" >/dev/null
# the two fingerprints the check must never count, submitted now so the single
# drain below is the last one (drain's own 24h EXPIRY would delete back-dated
# records, so all back-dating happens after the last drain).
python3 "$Q" submit --source open-loop-aging --severity warn \
  --message "synthetic self escalation" --fingerprint "open-loop-aging-24h" >/dev/null
python3 "$Q" submit --source mentor-reflection --severity warn \
  --message "synthetic mentor lesson" --fingerprint "mentor-lesson-2000-01-01" >/dev/null
python3 "$Q" drain >/dev/null

# 1. nothing is over-age yet
OUT=$(python3 "$Q" stale --max-age-hours 24); rc=$?
{ [ "$rc" = 0 ] && echo "$OUT" | grep -q "STALE_OPEN_LOOPS=0"; } \
  && ok "fresh fingerprints are not stale (exit 0)" \
  || bad "fresh fingerprints reported stale (rc=$rc): $OUT"

# back-date the real open loop 48h, and both self-excluded ones 72h
python3 - "$TMP/queue/state.json" "$OLD" <<'PY'
import json, sys, time
from datetime import datetime, timedelta, timezone
path, old_fp = sys.argv[1], sys.argv[2]
st = json.load(open(path))
def backdate(fp, hours):
    rec = st["fingerprints"][fp]
    rec["last_seen"] = (datetime.now(timezone.utc)
                        - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["last_epoch"] = time.time() - hours * 3600
backdate(old_fp, 48)
backdate("open-loop-aging-24h", 72)
backdate("mentor-lesson-2000-01-01", 72)
json.dump(st, open(path, "w"), indent=2)
PY

# 2. the back-dated one is reported, the fresh one is not
OUT=$(python3 "$Q" stale --max-age-hours 24); rc=$?
{ [ "$rc" = 2 ] && echo "$OUT" | grep -q "$OLD" && echo "$OUT" | grep -q "STALE_OPEN_LOOPS=1"; } \
  && ok "back-dated fingerprint reported stale (exit 2, name in stdout)" \
  || bad "back-dated fingerprint not flagged (rc=$rc): $OUT"
echo "$OUT" | grep -q "$FRESH" && bad "fresh fingerprint wrongly listed as stale" \
  || ok "fresh fingerprint stayed out of the stale list"

# 2b. self-exclusion: 72h-old open-loop-aging + mentor-lesson records are older
# than the flagged one, yet the count stays 1 — the probe cannot feed itself.
{ ! echo "$OUT" | grep -q "open-loop-aging-24h"; } \
  && { ! echo "$OUT" | grep -q "mentor-lesson-2000-01-01"; } \
  && ok "72h-old open-loop-aging + mentor-lesson fingerprints self-excluded" \
  || bad "self-exclusion failed, probe can feed itself: $OUT"

# 3. resolving the stale fingerprint clears the check
python3 "$Q" resolve --fingerprint "$OLD" >/dev/null
OUT=$(python3 "$Q" stale --max-age-hours 24); rc=$?
{ [ "$rc" = 0 ] && echo "$OUT" | grep -q "STALE_OPEN_LOOPS=0"; } \
  && ok "resolve clears the stale check (exit 0)" \
  || bad "stale check still firing after resolve (rc=$rc): $OUT"

rm -rf "$TMP"
unset HERMES_HOME

# --- real estate: surface aging open loops instead of counting them silently ---
# Threshold is overridable ONLY so the escalation branch can be exercised on
# demand; cron runs the 24h default.
MAX_AGE="${OPEN_LOOP_MAX_AGE_HOURS:-24}"
echo "--- real estate (HERMES_HOME=$HOME/.hermes, max-age=${MAX_AGE}h) ---"
REAL=$(HERMES_HOME="$HOME/.hermes" python3 "$Q" stale --max-age-hours "$MAX_AGE"); real_rc=$?
printf '%s\n' "$REAL" | sed 's/^/    /'
if [ "$real_rc" = 2 ]; then
  N=$(printf '%s\n' "$REAL" | sed -n 's/^STALE_OPEN_LOOPS=//p')
  HERMES_HOME="$HOME/.hermes" python3 "$Q" submit \
    --source open-loop-aging --severity warn \
    --fingerprint "open-loop-aging-24h" \
    --message "$N open loop(s) have been open >24h with no terminal state; run: hermes_queue.py stale --max-age-hours 24"
  echo "    escalated: open-loop-aging-24h ($N aging open loop(s))"
else
  echo "    no aging open loops — nothing escalated"
fi

echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — stale check flags over-age open loops, self-excludes, and clears on resolve."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
