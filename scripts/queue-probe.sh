#!/bin/bash
# queue-probe — FIRE 0 receipt.
# Proves the relay queue: (1) ingests events, (2) dedups by canonical fingerprint
# so PID/timestamp-varying messages collapse to ONE (the false-split bug that broke
# alert-resolver), (3) archives atomically with no partial files, (4) exposes open
# issues to Otto. Runs against an ISOLATED temp HERMES_HOME — never touches real state.
set -u
SCRIPTS="$HOME/.hermes/scripts"
Q="$SCRIPTS/hermes_queue.py"
TMP=$(mktemp -d)
export HERMES_HOME="$TMP"
fail=0
note(){ printf '%s\n' "$*"; }
bad(){ printf 'FAIL: %s\n' "$*"; fail=1; }

# 0. shared canonicalizer self-test (the heart of the dedup)
if python3 "$SCRIPTS/hermes_fingerprint.py" >/dev/null 2>&1; then
  note "OK  canonicalizer self-test passed"
else
  bad "canonicalizer self-test failed"
fi

# 1. two events: SAME condition, PID + timestamp vary (the false-split case)
python3 "$Q" submit --source watchdog --severity crit \
  --message "daemon not running. Started PID 111 at 2026-06-18 19:01" >/dev/null
python3 "$Q" submit --source watchdog --severity crit \
  --message "daemon not running. Started PID 222 at 2026-06-18 19:06" >/dev/null
# 2. one genuinely different condition
python3 "$Q" submit --source repo-health --severity warn \
  --message "git dirty: 12 files" >/dev/null

N_IN=$(ls "$TMP/queue/incoming"/*.json 2>/dev/null | wc -l | tr -d ' ')
[ "$N_IN" = "3" ] && note "OK  3 events enqueued" || bad "expected 3 incoming, got $N_IN"

# 3. drain / triage
note "drain: $(python3 "$Q" drain)"

# 4. dedup: 2 PID-variants must collapse to ONE fingerprint -> 2 total (watchdog+repo)
OPEN=$(python3 "$Q" status)
N_FP=$(printf '%s' "$OPEN" | python3 -c 'import json,sys;print(json.load(sys.stdin)["open_fingerprints"])')
[ "$N_FP" = "2" ] \
  && note "OK  dedup works: 2 fingerprints (not 3) — PID/timestamp variants collapsed" \
  || bad "expected 2 fingerprints, got $N_FP — FALSE-SPLIT NOT FIXED"

WD=$(printf '%s' "$OPEN" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(max((i["count"] for i in d["items"] if i["source"]=="watchdog"),default=0))')
[ "$WD" = "2" ] && note "OK  watchdog fingerprint count=2 (both variants tracked under one issue)" \
  || bad "expected watchdog count=2, got $WD"

# 5. atomicity + archival
N_TMP=$(ls "$TMP/queue/incoming"/.tmp-* 2>/dev/null | wc -l | tr -d ' ')
[ "$N_TMP" = "0" ] && note "OK  no partial .tmp files (atomic writes)" || bad "$N_TMP leftover .tmp files"
N_PROC=$(ls "$TMP/queue/processed"/*.json 2>/dev/null | wc -l | tr -d ' ')
[ "$N_PROC" = "3" ] && note "OK  3 events archived to processed/" || bad "expected 3 processed, got $N_PROC"
[ -f "$TMP/queue/digest.jsonl" ] && note "OK  digest.jsonl written (Otto's read surface)" || bad "no digest.jsonl"

rm -rf "$TMP"
note "---"
if [ "$fail" = 0 ]; then note "PROBE: PASS — relay queue ingests, dedups, archives atomically."; exit 0
else note "PROBE: FAIL — see FAIL lines."; exit 1; fi
