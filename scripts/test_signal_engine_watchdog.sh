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
PASS=0; FAIL=0

cleanup() { [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# --- stubs ------------------------------------------------------------------
mkdir -p "$TMP/bin" "$TMP/state" "$TMP/repo"
cat > "$TMP/bin/launchctl" <<'STUB'
#!/bin/bash
case "$1" in
  print) echo "	state = running"; echo "	last exit code = 0"; exit 0 ;;
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

echo "--- T5 NEW: heartbeat older than HARD_DOWN is crit despite live process ---"
rm -f "$TMP/state/signal-engine-probe.unverified"
set_heartbeat_age 900
OUT="$(run_new SEW_HARD_DOWN=60 SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T5 hard-down-clock-teeth" 1 "$RC" "NOT VERIFIED" "$OUT"

echo "--- T6 NEW: restart did NOT take (no process) -> still exit 1 ---"
stop_fake_daemon
set_heartbeat_age 900
OUT="$(run_new SEW_VERIFY_WINDOW=6 SEW_VERIFY_POLL=2)"; RC=$?
check "T6 restart-not-taken-still-fails" 1 "$RC" "NOT VERIFIED" "$OUT"

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

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
