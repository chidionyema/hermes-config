#!/bin/bash
# Tests the ALERTS section of verify_estate.sh — the pull-side proof that escalation
# still reaches the founder.
#
# Run: bash ~/.hermes/scripts/test_verify_estate_alerts.sh
#
# This section is the estate's last line of defence: when the push channel is the
# thing that is broken, every other alarm is by definition unable to say so. A false
# GREEN here therefore costs more than a false red anywhere else — it is the exact
# state the estate was in for 46 days. So the green branch is asserted to require a
# fresh AND verified proof, and every other input is asserted to fail.
#
# The section is extracted from the real script by marker; the extraction is itself
# asserted, so drift aborts instead of silently testing nothing.
set -uo pipefail
SRC="${1:-$HOME/.hermes/scripts/verify_estate.sh}"

SECTION="$(awk '
  /^echo "ALERTS  escalation reaches you"/ { on = 1 }
  on { print }
  on && /^fi$/ { exit }
' "$SRC")"

for anchor in 'DELIVERY_PROOF=' 'DELIVERY_MAX_AGE_S=' 'first-run' 'peer_failures'; do
  case "$SECTION" in
    *"$anchor"*) ;;
    *) echo "ABORT: extraction from $SRC lost the '$anchor' anchor — the section moved."
       exit 2 ;;
  esac
done

pass=0; fail=0
TMPHOME="$(mktemp -d)"; mkdir -p "$TMPHOME/state"
trap 'rm -rf "$TMPHOME"' EXIT

run() { # run <json for state/delivery_proof.json, or the literal string NONE>
  if [ "$1" = NONE ]; then rm -f "$TMPHOME/state/delivery_proof.json"
  else printf '%s' "$1" > "$TMPHOME/state/delivery_proof.json"; fi
  OUT="$(
    HERMES="$TMPHOME" bash -c '
      ok(){ printf "  OK %s\n" "$1"; }
      bad(){ printf "  BAD %s\n" "$1"; FAIL=1; }
      warn(){ printf "  WARN %s\n" "$1"; }
      FAIL=0
      '"$SECTION"'
      echo "__FAIL=$FAIL"
    '
  )"
  FAIL="$(printf '%s' "$OUT" | sed -n 's/.*__FAIL=\(.*\)/\1/p' | tail -1)"
  [ "$FAIL" = "1" ] && FAIL=FAIL || FAIL=OK
}
check() { # check <name> <substring> <FAIL|OK>
  if printf '%s' "$OUT" | grep -qF "$2" && [ "$FAIL" = "$3" ]; then
    echo "  PASS  $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1"; printf '%s\n' "$OUT" | sed 's/^/        /'
    echo "        verdict=$FAIL want=$3"; fail=$((fail+1))
  fi
}

NOW="$(python3 -c 'import time;print(int(time.time()))')"
OLD="$(python3 -c 'import time;print(int(time.time()-20*86400))')"

echo "ALERTS section behaviour"

run "{\"checked_at\": $NOW, \"verified\": true, \"detail\": \"arrived\"}"
check "a fresh verified proof is green" "OK escalation delivery proven 0.0d ago" OK

run "{\"checked_at\": $OLD, \"verified\": true, \"detail\": \"arrived\"}"
check "a STALE proof is red even though it says verified" \
      "BAD delivery last checked 20.0d ago — the canary itself has stopped running" FAIL

run "{\"checked_at\": $NOW, \"verified\": false, \"reason\": \"delivery-failed\", \"detail\": \"chat not found\"}"
check "a fresh failed proof is red" "BAD escalation NOT reaching you [delivery-failed]" FAIL

run "{\"checked_at\": $NOW, \"verified\": false, \"reason\": \"first-run\"}"
check "first run warns without failing the estate" "WARN delivery canary installed" OK

run "{\"checked_at\": $NOW, \"verified\": false, \"reason\": \"peer\", \"detail\": \"d\", \"peer_failures\": [{\"job\": \"otto-dispatch\", \"at\": \"t\", \"error\": \"chat not found\"}]}"
check "a peer delivery failure is named, not just counted" \
      "BAD otto-dispatch failed to deliver at t: chat not found" FAIL

run NONE
check "a missing proof file is red, never assumed fine" \
      "BAD no delivery proof at all" FAIL

run "{ this is not json"
check "an unreadable proof file is red, not skipped" "BAD delivery proof unreadable" FAIL

run "{\"verified\": true, \"detail\": \"no timestamp\"}"
check "a proof with no checked_at cannot be fresh" "BAD delivery last checked" FAIL

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
