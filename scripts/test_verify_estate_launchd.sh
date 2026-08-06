#!/bin/bash
# Tests the LAUNCHD section of verify_estate.sh.
#
# Run: bash ~/.hermes/scripts/test_verify_estate_launchd.sh
#
# Why this file exists
# --------------------
# That section reads `launchctl list` and decides whether an estate unit is failing.
# Both directions are dangerous and neither is observable in normal operation:
#   - too strict -> a permanent false red (what happened to ai.hermes.gateway, which
#     exits 1 BY DESIGN on an unexpected SIGTERM so KeepAlive revives it, leaving a
#     stale `last exit=1` forever). A section that is always red is a section nobody
#     reads, which is how a real failure hides.
#   - too lax   -> the regression the section was written for comes back: com.tie
#     .ai-review exited 78 on every run for weeks and nothing looked.
# So every case is asserted in BOTH directions.
#
# The code under test is EXTRACTED FROM THE REAL SCRIPT by marker, never copied here.
# A copy would drift and keep passing against a version that no longer ships. The
# extraction is itself asserted below: if the markers move, this aborts loudly rather
# than testing an empty string and reporting success.
set -uo pipefail
SRC="${1:-$HOME/.hermes/scripts/verify_estate.sh}"

SECTION="$(awk '
  /^LAUNCHD_SETTLED_S=/ { on = 1 }
  on { print }
  on && /verify_estate_fail/ && /FAIL=1/ { exit }
' "$SRC")"

for anchor in 'LAUNCHD_SETTLED_S=' '_pid_uptime_s' 'flapping' 'not running' 'third-party'; do
  case "$SECTION" in
    *"$anchor"*) ;;
    *) echo "ABORT: extraction from $SRC lost the '$anchor' anchor — the section moved."
       echo "       Fix the awk markers above; do NOT ship a green run from this."
       exit 2 ;;
  esac
done

pass=0; fail=0
run() { # run <launchctl-rows-with-\t-and-\n> <etime-string-ps-should-print>
  OUT="$(
    LC_ROWS="$1" ETIME="$2" HERMES="$TMPHOME" bash -c '
      launchctl() { printf "PID\tStatus\tLabel\n"; printf "%b" "$LC_ROWS"; }
      ps() { [ -n "$ETIME" ] && printf "%s\n" "$ETIME"; }
      export -f launchctl ps 2>/dev/null || true
      FAIL=0
      '"$SECTION"'
      echo "__FAIL=$FAIL"
    '
  )"
  FAIL="$(printf '%s' "$OUT" | sed -n 's/.*__FAIL=\(.*\)/\1/p' | tail -1)"
  [ "$FAIL" = "1" ] && FAIL=FAIL || FAIL=OK
}
check() { # check <name> <expected substring> <FAIL|OK>
  if printf '%s' "$OUT" | grep -qF "$2" && [ "$FAIL" = "$3" ]; then
    echo "  PASS  $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1"; printf '%s\n' "$OUT" | sed 's/^/        /'
    echo "        verdict=$FAIL want=$3"; fail=$((fail+1))
  fi
}

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT
echo "LAUNCHD section behaviour"

# The false red that prompted the change: healthy unit carrying a stale nonzero code.
run "2108\t1\tai.hermes.gateway\n" "         46:08"
check "long-running estate unit with a stale exit=1 is NOT a fault" \
      "✅ ai.hermes.gateway running 2768s (pid 2108) — last exit=1 is history" OK

# The other direction: a unit that really is respawning must still go red. If this
# ever passes as OK, the section has become decorative.
run "4321\t1\tai.hermes.gateway\n" "         00:12"
check "recently respawned estate unit with exit=1 IS a fault" \
      "❌ ai.hermes.gateway last exit=1 and respawned 12s ago — flapping" FAIL

# The original regression (one-shot, no pid, nonzero exit) must survive untouched.
run "-\t78\tcom.tie.ai-review\n" ""
check "dead one-shot unit with a nonzero exit IS a fault" \
      "❌ com.tie.ai-review last exit=78 and not running — job is failing every run" FAIL

run "-\t78\tcom.expressvpn.ExpressVPN.agent\n" ""
check "third-party unit warns, does not fail the estate" \
      "🟡 com.expressvpn.ExpressVPN.agent last exit=78 (third-party" OK

# Asserted by ABSENCE: checking that the header printed would pass regardless.
run "-\t1\tcom.apple.something\n" ""
if printf '%s' "$OUT" | grep -qF "com.apple.something" || [ "$FAIL" != OK ]; then
  echo "  FAIL  apple units are skipped entirely"; fail=$((fail+1))
else
  echo "  PASS  apple units are skipped entirely"; pass=$((pass+1))
fi

# macOS ps prints [[dd-]hh:]mm:ss. A parser that only handles mm:ss reads a unit up
# for days as seconds-old and reports the healthy unit as flapping.
run "2108\t1\tai.hermes.gateway\n" "      3-04:05:06"
check "multi-day etime parses (3-04:05:06 = 273906s)" "running 273906s" OK

# launchctl's pid can be gone by the time we stat it; that is not-running, not settled.
run "9999\t1\tai.hermes.gateway\n" ""
check "vanished pid falls back to the not-running red" \
      "and not running — job is failing every run" FAIL

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
