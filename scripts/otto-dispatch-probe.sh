#!/bin/bash
# otto-dispatch-probe — receipt for the PROACTIVE dispatcher (registry + auto-claim + dedup).
# Isolated HERMES_HOME; never touches the real queue. Proves with exit codes:
#   A self-heal : known auto_fix class, handler exits 0 -> SILENT (user not bothered)
#   B new-class : unknown class -> escalated to the user (rule a)
#   C dedup     : same user-worthy set within DEDUP_MIN -> 2nd delivery SILENT
#   D crit-gate : crit that cannot self-heal -> escalated (rule c)
#   E curator   : curator carries real open items into the digest + stays silent
#   F resolve   : probe-verified resolve clears the fingerprint from the open set
set -u
SC="$HOME/.hermes/scripts"
D="$SC/otto-dispatch.py"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

env_new(){ local t; t=$(mktemp -d); mkdir -p "$t/queue"; ln -s "$SC" "$t/scripts"; echo "$t"; }
digest(){ printf '{"items": %s}' "$2" > "$1/queue/pending-digest.json"; }

# A: prospector is auto_fix; prospector-run.sh exits 0 (repo present or missing-skip) -> silent
T=$(env_new)
digest "$T" '[{"source":"prospector","fingerprint":"fp-p","severity":"warn","count":1}]'
OUT=$(HERMES_HOME="$T" python3 "$D" 2>/dev/null)
[ -z "$OUT" ] && ok "A: known auto_fix class self-healed -> SILENT" \
              || bad "A: expected silence, got: $OUT"

# B: unknown class must reach the user
T=$(env_new)
digest "$T" '[{"source":"brand-new-failure","fingerprint":"fp-new","severity":"warn","count":1}]'
OUT=$(HERMES_HOME="$T" python3 "$D" 2>/dev/null)
echo "$OUT" | grep -q "need you" && ok "B: NEW class -> escalated to user" \
                                 || bad "B: new class not escalated: $OUT"

# C: same set twice within window -> 2nd silent
T=$(env_new)
digest "$T" '[{"source":"new-x","fingerprint":"fp-x","severity":"warn","count":1}]'
O1=$(HERMES_HOME="$T" HERMES_DISPATCH_DEDUP_MIN=30 python3 "$D" 2>/dev/null)
digest "$T" '[{"source":"new-x","fingerprint":"fp-x","severity":"warn","count":1}]'
O2=$(HERMES_HOME="$T" HERMES_DISPATCH_DEDUP_MIN=30 python3 "$D" 2>/dev/null)
{ [ -n "$O1" ] && [ -z "$O2" ]; } && ok "C: duplicate digest within 30m -> SILENT (delivered once)" \
                                  || bad "C: dedup failed: first='$O1' second='$O2'"

# D: crit that can't self-heal -> escalate. proving-ground is a probe class whose handler
#    exits 1 against an empty HERMES_CODE_DIR => still failing + crit => escalate (rule c).
T=$(env_new); EMPTY=$(mktemp -d)
digest "$T" '[{"source":"proving-ground","fingerprint":"fp-pg","severity":"crit","count":1}]'
OUT=$(HERMES_HOME="$T" HERMES_CODE_DIR="$EMPTY" python3 "$D" 2>/dev/null)
echo "$OUT" | grep -q "need you" && ok "D: crit that can't self-heal -> escalated (rule c)" \
                                 || bad "D: crit not escalated: $OUT"
rm -rf "$EMPTY"

# E + F: curator carries real open items into the digest (silent), resolve clears them
H2=$(mktemp -d); mkdir -p "$H2/.hermes/scripts" "$H2/.hermes/queue"
cp "$SC/queue-curate.sh" "$SC/hermes_queue.py" "$SC/hermes_fingerprint.py" "$H2/.hermes/scripts/" 2>/dev/null
COUT=$(HOME="$H2" bash -c '
Q="$HOME/.hermes/scripts/hermes_queue.py"
python3 "$Q" submit --source repo-health --severity crit --message "repo-health-check timed out after 120s" >/dev/null 2>&1
bash "$HOME/.hermes/scripts/queue-curate.sh"' 2>&1); crc=$?
DW="$H2/.hermes/queue/pending-digest.json"
NITEMS=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["open_fingerprints"])' "$DW" 2>/dev/null || echo -1)
{ [ -z "$COUT" ] && [ "$crc" = 0 ] && [ "$NITEMS" -ge 1 ] \
  && python3 -c 'import json,sys;exit(0 if any(i["source"]=="repo-health" for i in json.load(open(sys.argv[1]))["items"]) else 1)' "$DW"; } \
  && ok "E: curator silent + wrote digest CONTAINING the open item ($NITEMS)" \
  || bad "E: curator did not carry open items (rc=$crc, out='$COUT', n=$NITEMS)"

RBEFORE=$(HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" status 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["open_fingerprints"])')
FP=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["items"][0]["fingerprint"])' "$DW")
HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" resolve --fingerprint "$FP" >/dev/null 2>&1
RAFTER=$(HOME="$H2" python3 "$H2/.hermes/scripts/hermes_queue.py" status 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["open_fingerprints"])')
[ "$RAFTER" -lt "$RBEFORE" ] && ok "F: resolve cleared the fingerprint ($RBEFORE -> $RAFTER)" \
                             || bad "F: resolve did not clear ($RBEFORE -> $RAFTER)"

rm -rf "$T" "$H2"
echo "---"
[ "$fail" = 0 ] && { echo "PROBE: PASS — proactive dispatcher live (auto-claim + gate + dedup)"; exit 0; } \
                || { echo "PROBE: FAIL"; exit 1; }
