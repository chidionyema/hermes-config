#!/bin/bash
# test_signal_engine_watchdog.sh — executable proof for signal-engine-daemon-watchdog.sh
#
# Fixture-driven: a fake daemon process (unique guard, so the LIVE daemon is
# never matched), a temp heartbeat file with a controlled mtime, a stub
# `launchctl` on PATH (the real unit is never touched) and a stub alert queue
# that records severities instead of paging.
#
# T1 is the regression: the SAME fixture that made the OLD script exit 1 with
# "NOT VERIFIED" (the reported CRON_ERROR) must now exit 0.
#
# Usage: bash ~/.hermes/scripts/test_signal_engine_watchdog.sh
# Exit 0 = all pass.
set -u

NEW="$HOME/.hermes/scripts/signal-engine-daemon-watchdog.sh"
OLD="${OLD_SCRIPT:-$HOME/.hermes/backups/signal-engine-daemon-watchdog.sh.20260813-pre-bootgrace}"
TMP="$(mktemp -d /tmp/sewtest.XXXXXX)"
GUARD_TXT="signal_engine_testfixture.daemon"
TESTGUARD='[-]m signal_engine_testfixture\.daemon'
FAKE_PID=""
# A SECOND fixture process under its own guard, started at t=0 so it is already
# old by the time T9/T10 run — that is what makes "old PID survived the
# kickstart" reproducible without a 4-minute sleep. Never matched by TESTGUARD.
AGED_GUARD_TXT="signal_engine_agedfixture.daemon"
AGED_TESTGUARD='[-]m signal_engine_agedfixture\.daemon'
AGED_PID=""; AGED_START=0
PASS=0; FAIL=0

cleanup() { [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null
            [ -n "$AGED_PID" ] && kill "$AGED_PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# --- stubs ------------------------------------------------------------------
mkdir -p "$TMP/bin" "$TMP/state" "$TMP/repo"
cat > "$TMP/bin/launchctl" <<'STUB'
#!/bin/bash
case "$1" in
  print) echo "	state = running"; echo "	last exit code = ${STUB_EXIT_CODE:-0}"; exit 0 ;;
  kickstart) echo "kickstart-stub ok"; exit 0 ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/launchctl"
cat > "$TMP/queue.py" <<'STUB'
import sys, os
sev = sys.argv[sys.argv.index("--severity") + 1] if "--severity" in sys.argv else "?"
msg = sys.argv[sys.argv.index("--message") + 1] if "--message" in sys.argv else "?"
open(os.environ["ALERT_LOG"], "a").write(f"{sev}\t{msg}\n")
STUB
export ALERT_LOG="$TMP/alerts.log"
: > "$ALERT_LOG"

# fixture-pointed copy of the OLD script (its constants are hardcoded)
sed -e "s|^REPO=.*|REPO=\"$TMP/repo\"|" \
    -e "s|^GUARD=.*|GUARD='$TESTGUARD'|" \
    -e "s|^HEARTBEAT=.*|HEARTBEAT=\"$TMP/hb.json\"|" \
    -e "s|^STAMP_DIR=.*|STAMP_DIR=\"$TMP/state\"|" \
    -e "s|\$HOME/.hermes/scripts/hermes_queue.py|$TMP/queue.py|" \
    "$OLD" > "$TMP/old.sh"
chmod +x "$TMP/old.sh"

# --- helpers ----------------------------------------------------------------
start_fake_daemon() {
  python3 -c 'import time; time.sleep(600)' -m "$GUARD_TXT" &
  FAKE_PID=$!
  sleep 1
}
stop_fake_daemon() { [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; FAKE_PID=""; sleep 1; }

start_aged_daemon() {
  python3 -c 'import time; time.sleep(1800)' -m "$AGED_GUARD_TXT" &
  AGED_PID=$!
  AGED_START="$(date +%s)"
}
# Sleep only the shortfall: the aged fixture has been running through T1-T8.
age_aged_daemon_to() {  # $1 = required age in seconds
  local have=$(( $(date +%s) - AGED_START ))
  [ "$have" -lt "$1" ] && sleep $(( $1 - have ))
  return 0
}

set_heartbeat_age() {  # $1 = seconds old
  echo '{"state":{}}' > "$TMP/hb.json"
  python3 -c "import os,time,sys; t=time.time()-float(sys.argv[1]); os.utime('$TMP/hb.json',(t,t))" "$1"
}

run_new() { env PATH="$TMP/bin:$PATH" \
  SEW_GUARD="$TESTGUARD" SEW_HEARTBEAT="$TMP/hb.json" SEW_STAMP_DIR="$TMP/state" \
  SEW_QUEUE="$TMP/queue.py" SEW_ERRLOG="$TMP/repo/err.log" SEW_ALERT_COOLDOWN=0 \
  "$@" bash "$NEW" 2>&1; }

check() {  # $1=name $2=expected_exit $3=actual_exit $4=must_contain $5=output
  if [ "$2" = "$3" ] && printf '%s' "$5" | grep -q "$4"; then
    echo "  PASS  $1  (exit=$3)"; PASS=$((PASS+1))
  else
    echo "  FAIL  $1  expected exit=$2 + text '$4'; got exit=$3"; echo "$5" | sed 's/^/        | /'
    FAIL=$((FAIL+1))
  fi
}

echo "=== fixture: daemon ALIVE (young), heartbeat 900s stale, unit loaded ==="
start_aged_daemon        # ages in the background for T9/T10
start_fake_daemon
set_heartbeat_age 900

echo "--- T1a OLD script on this fixture (reproduces the CRON_ERROR) ---"
OUT="$(env PATH="$TMP/bin:$PATH" bash "$TMP/old.sh" 2>&1)"; RC=$?
check "T1a old-script-reproduces-failure" 1 "$RC" "NOT VERIFIED" "$OUT"

echo "--- T1b NEW script, identical fixture ---"
OUT="$(run_new)"; RC=$?
check "T1b new-script-boot-grace-ok" 0 "$RC" "boot grace" "$OUT"

echo "--- T2 NEW: boot grace disabled -> kickstart + poll -> restart TOOK ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
OUT="$(run_new SEW_BOOT_GRACE=1 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T2 restart-took-booting" 0 "$RC" "Restart TOOK" "$OUT"

echo "--- T3 NEW: teeth — 3rd consecutive unverified restart is crit ---"
OUT="$(run_new SEW_BOOT_GRACE=1 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC2=$?
OUT="$(run_new SEW_BOOT_GRACE=1 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T3 max-unverified-forces-crit" 1 "$RC" "consecutive unverified restarts" "$OUT"

echo "--- T4 NEW: fresh heartbeat DURING window -> verified ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
( sleep 3; touch "$TMP/hb.json" ) &
OUT="$(run_new SEW_BOOT_GRACE=1 SEW_VERIFY_WINDOW=12 SEW_VERIFY_POLL=2)"; RC=$?
check "T4 fresh-heartbeat-verified" 0 "$RC" "Verified" "$OUT"
[ -f "$TMP/state/signal-engine-probe.unverified" ] \
  && { echo "  FAIL  T4b counter-not-reset"; FAIL=$((FAIL+1)); } \
  || { echo "  PASS  T4b counter-reset-on-verify"; PASS=$((PASS+1)); }

# T5 REVISED 2026-08-13 (second pass): HARD_DOWN no longer VETOES restart
# evidence — a heartbeat stale by definition must not invalidate proof from the
# process table (design note (g)). It now raises its OWN crit, and only when
# restart evidence is absent. Fixture: old PID survives the kick (no new
# process), last exit 78 so the in-flight arm is correctly closed.
echo "--- T5 NEW: heartbeat older than HARD_DOWN, no restart evidence -> crit ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
set_heartbeat_age 900
age_aged_daemon_to 20
OUT="$(run_new SEW_GUARD="$AGED_TESTGUARD" STUB_EXIT_CODE=78 SEW_BOOT_GRACE=1 \
       SEW_HARD_DOWN=60 SEW_RESPAWN_SLACK=5 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T5 hard-down-clock-teeth" 1 "$RC" "HARD DOWN" "$OUT"

# T6 REVISED 2026-08-13 (second pass): "no PID yet" is RESTART IN FLIGHT, not an
# observed failure — launchd may not have respawned inside the window. Exit 0 on
# the first occurrence; the teeth are the COUNTER, proven by T10.
echo "--- T6 NEW: no process yet after kickstart -> in flight (exit 0), not a verdict ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
stop_fake_daemon
set_heartbeat_age 900
OUT="$(run_new SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T6 no-pid-is-in-flight-not-failure" 0 "$RC" "restart-in-flight" "$OUT"

echo "--- T7 healthy fast path stays silent ---"
start_fake_daemon
set_heartbeat_age 10
OUT="$(run_new)"; RC=$?
[ "$RC" = "0" ] && [ -z "$OUT" ] \
  && { echo "  PASS  T7 healthy-silent-exit0"; PASS=$((PASS+1)); } \
  || { echo "  FAIL  T7 healthy-silent-exit0 (rc=$RC out='$OUT')"; FAIL=$((FAIL+1)); }

echo "--- T8 alert severities: booting=info, teeth=crit ---"
if grep -q "^info	Signal Engine restarted" "$ALERT_LOG" && grep -q "^crit" "$ALERT_LOG"; then
  echo "  PASS  T8 severity-buckets"; PASS=$((PASS+1))
else
  echo "  FAIL  T8 severity-buckets"; cat "$ALERT_LOG" | sed 's/^/        | /'; FAIL=$((FAIL+1))
fi

# ---------------------------------------------------------------------------
# T9/T10 — the 2026-08-13 (second pass) CRON_ERROR: "NOT VERIFIED after 71s:
# pid='43761'" while the daemon was fine. The kicked process was STILL DYING, so
# alive_pid returned the PRE-kickstart PID, whose proc_age far exceeded
# ELAPSED+30 → the old age-only gate was unreachable → exit 1.
# Fixture: heartbeat stale > STALE_AFTER, kickstart returns 0, the fixture PID is
# UNCHANGED across the kickstart and older than VERIFY_WINDOW+30.
# (Numbered T9/T10 because T7/T8 were already taken by the fast-path and
# severity-bucket tests above.)
# ---------------------------------------------------------------------------
PRE="${PRE_SCRIPT:-$HOME/.hermes/backups/signal-engine-daemon-watchdog.sh.20260813-pre-inflight}"
run_pre() { env PATH="$TMP/bin:$PATH" \
  SEW_GUARD="$TESTGUARD" SEW_HEARTBEAT="$TMP/hb.json" SEW_STAMP_DIR="$TMP/state" \
  SEW_QUEUE="$TMP/queue.py" SEW_ERRLOG="$TMP/repo/err.log" SEW_ALERT_COOLDOWN=0 \
  "$@" bash "$PRE" 2>&1; }

echo "--- T9 restart in flight: pre-kick PID survives the kickstart ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
set_heartbeat_age 900
age_aged_daemon_to 45     # > VERIFY_WINDOW(6) + 30, so the OLD age gate cannot pass

if [ -f "$PRE" ]; then
  echo "--- T9a PRE-fix script on this fixture (reproduces the CRON_ERROR) ---"
  OUT="$(run_pre SEW_GUARD="$AGED_TESTGUARD" SEW_BOOT_GRACE=1 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
  check "T9a pre-fix-reproduces-failure" 1 "$RC" "NOT VERIFIED" "$OUT"
else
  echo "  SKIP  T9a (no pre-fix copy at $PRE)"
fi

rm -f "$TMP/state/signal-engine-probe.unverified"
: > "$ALERT_LOG"
OUT="$(run_new SEW_GUARD="$AGED_TESTGUARD" SEW_BOOT_GRACE=1 SEW_RESPAWN_SLACK=5 \
       SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T9b restart-in-flight-exit0" 0 "$RC" "restart-in-flight" "$OUT"
if grep -q "^info	Signal Engine restart in flight" "$ALERT_LOG"; then
  echo "  PASS  T9c in-flight-alert-severity-info"; PASS=$((PASS+1))
else
  echo "  FAIL  T9c in-flight-alert-severity-info"; sed 's/^/        | /' "$ALERT_LOG"; FAIL=$((FAIL+1))
fi

echo "--- T10 teeth: same fixture MAX_UNVERIFIED+1 times -> crit + exit 1 ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
: > "$ALERT_LOG"
for i in 1 2 3; do
  OUT="$(run_new SEW_GUARD="$AGED_TESTGUARD" SEW_BOOT_GRACE=1 SEW_RESPAWN_SLACK=5 \
         SEW_MAX_UNVERIFIED=2 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
  echo "    run $i -> exit=$RC"
done
check "T10a in-flight-teeth-exit1" 1 "$RC" "in flight" "$OUT"
if tail -1 "$ALERT_LOG" | grep -q "^crit"; then
  echo "  PASS  T10b in-flight-teeth-severity-crit"; PASS=$((PASS+1))
else
  echo "  FAIL  T10b in-flight-teeth-severity-crit"; sed 's/^/        | /' "$ALERT_LOG"; FAIL=$((FAIL+1))
fi

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
