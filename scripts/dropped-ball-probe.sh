#!/bin/bash
# dropped-ball-probe — receipt for the dropped-ball watchdog (hermes_claims.py).
# Proves the mechanism actually catches self-certification and escalates it,
# rather than trusting the docstring. Runs in an isolated HERMES_HOME so it
# never touches the real ledger/queue.
set -u
SC="$HOME/.hermes/scripts"
C="$SC/hermes_claims.py"
TMP=$(mktemp -d); export HERMES_HOME="$TMP"
fail=0
ok(){  printf 'OK  %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

# 1. claim backed by a PASSING probe -> VERIFIED, exit 0
OUT=$(python3 "$C" assert --claim "daemon is up" --probe "true"); rc=$?
{ echo "$OUT" | grep -q "VERIFIED" && [ "$rc" = 0 ]; } \
  && ok "passing-probe claim -> VERIFIED (exit 0)" \
  || bad "passing-probe claim not verified (rc=$rc): $OUT"

# 2. claim backed by a FAILING probe -> DROPPED BALL, exit 2
OUT=$(python3 "$C" assert --claim "reset cleared equity" --probe "false"); rc=$?
{ echo "$OUT" | grep -q "DROPPED BALL" && [ "$rc" = 2 ]; } \
  && ok "failing-probe claim -> DROPPED BALL (exit 2)" \
  || bad "failing-probe claim not flagged (rc=$rc): $OUT"

# 3. claim with NO probe -> DROPPED BALL (self-certification), exit 2
OUT=$(python3 "$C" assert --claim "memory was saved"); rc=$?
{ echo "$OUT" | grep -q "DROPPED BALL" && [ "$rc" = 2 ]; } \
  && ok "no-probe claim -> DROPPED BALL self-certification (exit 2)" \
  || bad "no-probe claim not flagged (rc=$rc): $OUT"

# 4. audit re-verifies all 3 open claims: finds the 2 balls, exits 2
OUT=$(python3 "$C" audit); rc=$?
printf '    --- audit ---\n'; printf '%s\n' "$OUT" | sed 's/^/    /'
[ "$rc" = 2 ] && ok "audit exits 2 (dropped balls present)" || bad "audit should exit 2, got $rc"
echo "$OUT" | grep -q "2 DROPPED BALL" && ok "audit counted 2 dropped balls" || bad "audit miscounted"

# 5. escalation: the 2 balls reached the relay queue as dropped-ball events
python3 "$SC/hermes_queue.py" drain >/dev/null 2>&1
NDB=$(python3 "$SC/hermes_queue.py" status 2>/dev/null | python3 -c \
  'import json,sys;d=json.load(sys.stdin);print(sum(1 for i in d["items"] if i["source"]=="dropped-ball-watchdog"))' 2>/dev/null || echo 0)
[ "${NDB:-0}" -ge 1 ] && ok "dropped balls escalated to relay queue ($NDB fingerprint(s))" \
  || bad "no dropped-ball events reached the queue (got $NDB)"

rm -rf "$TMP"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — dropped-ball watchdog flags no-probe + failing-probe claims and escalates them."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
