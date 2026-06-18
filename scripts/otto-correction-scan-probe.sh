#!/bin/bash
# otto-correction-scan-probe — receipt for the continuous-audit trigger.
# Proves: (1) a correcting message is detected + escalated to the queue (exit 2),
# (2) a clean message is not (exit 0), (3) the audit request actually lands in the
# relay queue. Runs in an isolated HERMES_HOME so it never touches the real queue.
set -u
SC="$HOME/.hermes/scripts"
S="$SC/otto-correction-scan.py"
TMP=$(mktemp -d); export HERMES_HOME="$TMP"
fail=0
ok(){  printf 'OK  %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

# 1. a real correction (verbatim-style user phrasing) -> DETECTED, exit 2
OUT=$(python3 "$S" scan --text "you didn't verify that — that's another dropped ball, you shouldn't have to be told"); rc=$?
{ echo "$OUT" | grep -q "CORRECTION DETECTED" && [ "$rc" = 2 ]; } \
  && ok "correction message detected + escalated (exit 2)" \
  || bad "correction not detected (rc=$rc): $OUT"

# 2. a clean status message -> NOT flagged, exit 0
OUT=$(python3 "$S" scan --text "the daemon is running fine, queue drained, all probes pass"); rc=$?
{ echo "$OUT" | grep -q "no correction markers" && [ "$rc" = 0 ]; } \
  && ok "clean message not flagged (exit 0)" \
  || bad "clean message false-flagged (rc=$rc): $OUT"

# 3. escalation landed in the relay queue
python3 "$SC/hermes_queue.py" drain >/dev/null 2>&1
NCA=$(python3 "$SC/hermes_queue.py" status 2>/dev/null | python3 -c \
  'import json,sys;d=json.load(sys.stdin);print(sum(1 for i in d["items"] if i["source"]=="correction-audit"))' 2>/dev/null || echo 0)
[ "${NCA:-0}" -ge 1 ] && ok "audit request reached relay queue ($NCA)" \
  || bad "no correction-audit event in queue (got $NCA)"

rm -rf "$TMP"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — correction detected & auto-escalated; clean message ignored."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
