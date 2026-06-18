#!/bin/bash
# otto-dispatch-probe — receipt for the Ball 17 relay topology.
# Proves, in an isolated HERMES_HOME (never touches the real queue/digest):
#   A. an auto-remediable issue whose fix-probe now PASSES is absorbed silently
#      (NOT shown to the user) while a crit user-worthy issue IS forwarded.
#   B. an auto-remediable issue whose fix-probe still FAILS IS escalated to the user.
#   C. an empty/healthy digest produces NO stdout (user is not bothered).
#   D. the curator writes pending-digest.json and stays SILENT on stdout.
set -u
SC="$HOME/.hermes/scripts"
D="$SC/otto-dispatch.py"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

TMP=$(mktemp -d); export HERMES_HOME="$TMP"
mkdir -p "$TMP/queue" "$TMP/scripts"

seed_digest() {  # $1 = json items array
  cat > "$TMP/queue/pending-digest.json" <<JSON
{"ts":"2026-01-01T00:00:00Z","open_fingerprints":9,"items":$1}
JSON
}
stub_probe() { printf '#!/bin/bash\nexit %s\n' "$1" > "$TMP/scripts/memory-capacity-probe.sh"; chmod +x "$TMP/scripts/memory-capacity-probe.sh"; }

# --- A: auto-remediation SUCCEEDS for memory-capacity + crit item forwarded ---
stub_probe 0
seed_digest '[{"severity":"warn","count":1,"source":"memory-capacity","fingerprint":"user.md at 95% of cap"},{"severity":"crit","count":2,"source":"dropped-ball-watchdog","fingerprint":"daemon down"}]'
OUT=$(python3 "$D"); rc=$?
{ echo "$OUT" | grep -q "dropped-ball-watchdog" \
  && ! echo "$OUT" | grep -q "memory-capacity" \
  && echo "$OUT" | grep -q "auto-remediated" && [ "$rc" = 0 ]; } \
  && ok "A: memory-capacity absorbed silently; crit forwarded to user (exit 0)" \
  || bad "A: triage wrong (rc=$rc):
$OUT"
# digest was consumed (moved to .processed)
[ ! -f "$TMP/queue/pending-digest.json" ] && [ -f "$TMP/queue/pending-digest.json.processed" ] \
  && ok "A: pending digest consumed (.processed)" || bad "A: digest not consumed"

# --- B: auto-remediation FAILS -> user IS told ---
stub_probe 2
seed_digest '[{"severity":"warn","count":1,"source":"memory-capacity","fingerprint":"user.md at 99% of cap"}]'
OUT=$(python3 "$D"); rc=$?
{ echo "$OUT" | grep -q "memory-capacity" && echo "$OUT" | grep -q "auto-remediation FAILED" && [ "$rc" = 0 ]; } \
  && ok "B: failed remediation escalated to user" \
  || bad "B: failed remediation not escalated (rc=$rc):
$OUT"

# --- C: empty digest -> SILENT ---
seed_digest '[]'
OUT=$(python3 "$D"); rc=$?
[ -z "$OUT" ] && [ "$rc" = 0 ] && ok "C: healthy/empty digest is silent (exit 0)" \
  || bad "C: empty digest produced output (rc=$rc): $OUT"

# --- D: curator carries REAL open items into the digest + is silent (would catch the
#        heredoc/stdin bug where the digest came out empty) + resolve clears them ---
H2="$TMP/home"; mkdir -p "$H2/.hermes/scripts" "$H2/.hermes/queue"
cp "$SC/queue-curate.sh" "$SC/hermes_queue.py" "$SC/hermes_fingerprint.py" "$H2/.hermes/scripts/" 2>/dev/null
COUT=$(HOME="$H2" bash -c '
Q="$HOME/.hermes/scripts/hermes_queue.py"
python3 "$Q" submit --source repo-health --severity crit --message "repo-health-check timed out after 120s" >/dev/null 2>&1
bash "$HOME/.hermes/scripts/queue-curate.sh"
' 2>&1); crc=$?
DW="$H2/.hermes/queue/pending-digest.json"
NITEMS=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["open_fingerprints"])' "$DW" 2>/dev/null || echo -1)
{ [ -z "$COUT" ] && [ "$crc" = 0 ] && [ "$NITEMS" -ge 1 ] \
  && python3 -c 'import json,sys;exit(0 if any(i["source"]=="repo-health" for i in json.load(open(sys.argv[1]))["items"]) else 1)' "$DW"; } \
  && ok "D: curator silent + wrote digest CONTAINING the open item ($NITEMS)" \
  || bad "D: curator did not carry open items into digest (rc=$crc, out='$COUT', n=$NITEMS)"

# --- E: probe-verified resolve clears the fingerprint from the open set ---
RBEFORE=$(HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" status 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["open_fingerprints"])')
FP=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["items"][0]["fingerprint"])' "$DW")
HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" resolve --fingerprint "$FP" >/dev/null 2>&1
RAFTER=$(HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" status 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["open_fingerprints"])')
[ "$RAFTER" -lt "$RBEFORE" ] && ok "E: resolve cleared the fingerprint ($RBEFORE -> $RAFTER)" \
  || bad "E: resolve did not clear ($RBEFORE -> $RAFTER)"

rm -rf "$TMP"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — curator->file->otto-dispatch->user topology verified; Otto absorbs mechanical issues, forwards only user-worthy ones."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
