#!/bin/bash
# signal-engine-daemon-watchdog — a PROBE, not a launcher. Silent when healthy.
#
# WHY THIS WAS REWRITTEN (2026-07-31)
# The previous version launched the daemon itself with `nohup ... &` and then
# `exit 0` unconditionally. From cron's launchd context that child died in under
# a second (measured: PID reported started 12:25:19, gone by 12:25:20, zero bytes
# written), because the venv interpreter python@3.12 has no TCC grant to read
# ~/Documents — it exits EX_CONFIG(78) before Python starts. The script reported
# "Started PID <n>" and last_status=ok 2,732 consecutive times while
# daemon.err.log went un-written for 37 days.
#
# The rule this encodes: a probe that can report "ok" without having OBSERVED the
# thing it claims is ok is worse than no probe at all. So:
#   1. launchd owns the process (com.signalengine.daemon, KeepAlive). We never
#      spawn an orphan — an orphan is precisely what nobody supervises.
#   2. The only recovery action allowed is `launchctl kickstart -k` on the real
#      unit, and it is ALWAYS followed by a re-check ${VERIFY_DELAY}s later.
#   3. Any state that is not "process alive AND heartbeat fresh" exits non-zero.
#      No branch can reach `exit 0` without having proved liveness first.
#
# Heartbeat = mtime of data_store/daemon_control.json, which daemon.py rewrites
# via write_state() on every cycle (daemon.py:292,310; tick_interval_sec=60).
# A live-but-wedged daemon therefore reads as `stalled`, not `ok` — pgrep alone
# cannot tell those apart, which is why mtime is the authority here.
set -u

REPO="$HOME/Documents/code/signalengine"
LABEL="com.signalengine.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# Anchored on the `-m <module>` argv pair, not the bare module name. The loose
# pattern 'signal_engine.daemon' false-positives on ANY command line quoting the
# module — measured 2026-07-31: it matched PID 1914, a hermes_queue.py submit
# whose alert text was "signal_engine.daemon was not running...". A probe that
# mistakes its own alert relay for the daemon reports a corpse as healthy.
# [-] is the bracket trick: matches a literal "-m" without pgrep parsing a flag.
GUARD='[-]m signal_engine\.daemon'
HEARTBEAT="$REPO/data_store/daemon_control.json"
STALE_AFTER=600                       # 10 tick_intervals; below this is normal jitter
VERIFY_DELAY=20                       # launchd throttle is 30s; a real boot logs well inside 20s
ALERT_COOLDOWN=3600                   # don't re-page for the same state signature within the hour
STAMP_DIR="$HOME/.hermes/state"
STAMP="$STAMP_DIR/signal-engine-probe.last-alert"
UID_NUM="$(id -u)"

mkdir -p "$STAMP_DIR" 2>/dev/null

# --- observations -----------------------------------------------------------

alive_pid() { pgrep -f "$GUARD" 2>/dev/null | head -1; }

heartbeat_age() {
  [ -f "$HEARTBEAT" ] || { echo "-1"; return; }
  python3 - "$HEARTBEAT" <<'PY' 2>/dev/null || echo "-1"
import os, sys, time
print(int(time.time() - os.path.getmtime(sys.argv[1])))
PY
}

# launchd's own view. Empty string when the unit is not loaded at all.
unit_print() { launchctl print "gui/$UID_NUM/$LABEL" 2>/dev/null; }
unit_field() { printf '%s\n' "$1" | grep -m1 "$2" | sed 's/.*= *//' | tr -d ' "'; }

# --- alerting ---------------------------------------------------------------
# Relay to Otto's queue rather than paging the founder raw, and only once per
# ALERT_COOLDOWN per distinct signature — a TCC grant that stays ungranted must
# not generate 288 alerts a day.
alert() {
  local sig="$1" msg="$2" now last prev_sig severity
  now="$(date +%s)"
  if [ -f "$STAMP" ]; then
    prev_sig="$(head -1 "$STAMP" 2>/dev/null)"
    last="$(sed -n '2p' "$STAMP" 2>/dev/null)"
    if [ "$prev_sig" = "$sig" ] && [ -n "${last:-}" ] \
       && [ $((now - last)) -lt "$ALERT_COOLDOWN" ]; then
      return 0
    fi
  fi
  printf '%s\n%s\n' "$sig" "$now" > "$STAMP"
  # Severity follows the signature: a self-heal that already proved itself
  # (VERIFY_DELAY re-check passed) is not an unresolved outage and must not
  # page at the same severity as one. Every other signature here means the
  # probe is exiting non-zero with the daemon still down/unproven — those stay
  # crit. Add new call sites to one of the two buckets, never a bare default.
  case "$sig" in
    recovered) severity="info" ;;
    *) severity="crit" ;;
  esac
  # Hard time limit on the relay. A normal submit takes ~0.1s (measured), but a
  # leaked one was found wedged for 5+ minutes (PID 1914, 2026-07-31) from the
  # old watchdog. Cron kills the whole job on script_timeout, so an unbounded
  # relay call could swallow the probe's own verdict. Report, never block.
  local to=""
  command -v timeout >/dev/null 2>&1 && to="timeout 15"
  $to python3 "$HOME/.hermes/scripts/hermes_queue.py" submit \
    --source signal-engine-probe --severity "$severity" --message "$msg" \
    >/dev/null 2>&1 || true
}

clear_alert_stamp() { rm -f "$STAMP" 2>/dev/null; }

# --- fast path: already healthy --------------------------------------------

PID="$(alive_pid)"
AGE="$(heartbeat_age)"

if [ -n "$PID" ] && [ "$AGE" -ge 0 ] && [ "$AGE" -lt "$STALE_AFTER" ]; then
  clear_alert_stamp
  exit 0
fi

# --- unhealthy: classify before acting --------------------------------------

PRINT="$(unit_print)"
LOADED=0; [ -n "$PRINT" ] && LOADED=1
STATE="$(unit_field "$PRINT" 'state = ')"
EXITCODE="$(unit_field "$PRINT" 'last exit code = ')"

if [ -n "$PID" ]; then
  # Process exists but the heartbeat is stale — wedged, not dead. Bouncing a
  # wedged daemon is safe (paper/sim modes are idempotent on restart) but only
  # launchd may do it, so a wedge with no unit loaded is reported, not killed.
  echo "⚠️  Signal Engine daemon PID $PID alive but heartbeat is ${AGE}s stale (limit ${STALE_AFTER}s)."
  if [ "$LOADED" -eq 0 ]; then
    echo "  Unit $LABEL is NOT loaded — this PID is unsupervised (manual/orphan launch)."
    echo "  Refusing to kill a process launchd does not own. Load the unit, then re-probe."
    alert "stalled-unsupervised" "Signal Engine wedged (${AGE}s stale) and running unsupervised; $LABEL not loaded"
    exit 1
  fi
elif [ "$LOADED" -eq 0 ]; then
  if [ ! -f "$PLIST" ]; then
    echo "❌ Signal Engine daemon DOWN and no LaunchAgent installed ($PLIST missing)."
    echo "   This probe does not launch daemons. Install the unit:"
    echo "     launchctl bootstrap gui/$UID_NUM $PLIST"
    alert "no-unit" "Signal Engine daemon down; LaunchAgent $LABEL is not installed"
    exit 1
  fi
  echo "❌ Signal Engine daemon DOWN. Plist exists but is not loaded."
  echo "   launchctl bootstrap gui/$UID_NUM $PLIST"
  alert "unit-unloaded" "Signal Engine daemon down; $LABEL installed but not loaded"
  exit 1
else
  echo "❌ Signal Engine daemon DOWN. Unit $LABEL loaded (state=${STATE:-?}, last exit=${EXITCODE:-?})."
  # 78 = EX_CONFIG. For this unit that has one proven cause: the venv interpreter
  # cannot read ~/Documents because python@3.12 has no TCC Full Disk Access grant
  # (TCC.db: python@3.14 -> 2, cpython-3.11.15 -> 0, python@3.12 -> absent).
  # launchd will KeepAlive-retry this forever and never succeed, so say so plainly
  # instead of letting it look like a transient crash loop.
  case "$EXITCODE" in
    78|78:*)
      echo "   EX_CONFIG(78): interpreter cannot read the repo — missing TCC grant."
      echo "   FIX (founder, one-time GUI action — cannot be scripted):"
      echo "     System Settings > Privacy & Security > Full Disk Access > + >"
      echo "     /usr/local/Cellar/python@3.12/3.12.8/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
      alert "tcc-denied" "Signal Engine daemon cannot start: EX_CONFIG(78), python@3.12 lacks Full Disk Access. Needs one-time founder grant."
      exit 1
      ;;
  esac
fi

# --- recovery: kickstart the real unit, then PROVE it took -------------------

echo "  Kickstarting $LABEL (launchctl kickstart -k)..."
if ! launchctl kickstart -k "gui/$UID_NUM/$LABEL" 2>&1; then
  echo "  ERROR: kickstart failed." >&2
  alert "kickstart-failed" "Signal Engine: launchctl kickstart of $LABEL failed"
  exit 1
fi

sleep "$VERIFY_DELAY"

NEW_PID="$(alive_pid)"
NEW_AGE="$(heartbeat_age)"
NEW_EXIT="$(unit_field "$(unit_print)" 'last exit code = ')"

if [ -n "$NEW_PID" ] && [ "$NEW_AGE" -ge 0 ] && [ "$NEW_AGE" -lt "$STALE_AFTER" ]; then
  echo "  ✅ Verified: PID $NEW_PID up, heartbeat ${NEW_AGE}s old."
  clear_alert_stamp
  alert "recovered" "Signal Engine daemon was down; kickstarted and VERIFIED alive (PID $NEW_PID)"
  exit 0
fi

# The whole point: a restart that did not take is a FAILURE, reported as one.
echo "  ❌ NOT VERIFIED after ${VERIFY_DELAY}s: pid='${NEW_PID:-none}' heartbeat_age='${NEW_AGE}s' last_exit='${NEW_EXIT:-?}'" >&2
echo "     Last 5 lines of daemon.err.log:" >&2
tail -5 "$REPO/daemon.err.log" 2>/dev/null | sed 's/^/       /' >&2
alert "restart-not-verified" "Signal Engine daemon restart did NOT take (last_exit=${NEW_EXIT:-?}); daemon is down"
exit 1
