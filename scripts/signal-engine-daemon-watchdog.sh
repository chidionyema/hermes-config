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
#      unit, and it is ALWAYS followed by a re-check.
#   3. No branch reaches `exit 0` on an assumption. Every exit 0 names the
#      evidence it observed, and every tolerated-but-unproven state is bounded
#      by a clock (HARD_DOWN) or a counter (MAX_UNVERIFIED) that eventually
#      forces a crit.
#
# Heartbeat = mtime of data_store/daemon_control.json, which daemon.py rewrites
# via write_state() on every cycle (daemon.py:292,310).
# A live-but-wedged daemon therefore reads as `stalled`, not `ok` — pgrep alone
# cannot tell those apart, which is why mtime is the authority here.
#
# ---------------------------------------------------------------------------
# WHY THE VERIFY WAS REWRITTEN (2026-08-13) — the CRON_ERROR this fixes
#
# Symptom (cron, recurring):
#   CRON_ERROR: signal-engine-daemon-watchdog errored: Script exited with code 1
#   ❌ NOT VERIFIED after 20s: pid='73697' heartbeat_age=...
# Note pid was NON-EMPTY: the restart HAD taken. Only the heartbeat check failed.
#
# Root cause, measured on this host 2026-08-13:
#   - write_state() runs at the END of a cycle (daemon.py:292), and a cycle is
#     warmup + a live-feed poll. PID 74963 started 14:26:21 (ps -o lstart) and
#     logged its first "Cycle complete" at 14:29:21 — TIME TO FIRST HEARTBEAT
#     = 180s. Observed cycle spans that day ran 43s–350s
#     (14:47:00 → 14:52:50), so 180s is typical, not an outlier.
#   - The old verify slept VERIFY_DELAY=20s once, then demanded
#     heartbeat_age < STALE_AFTER(600). After a kickstart the heartbeat file
#     still carries the PRE-restart mtime — which was ≥600s stale, because that
#     staleness is what triggered the restart. So at t+20s the test could not
#     pass even in principle: a SUCCESSFUL restart was reported as a failure,
#     every time, and paged "daemon is down" while the daemon was booting fine.
#   - Raising VERIFY_DELAY to 180s+ is NOT available: the cron scheduler kills
#     the job at 120s (cron/scheduler.py:855 _DEFAULT_SCRIPT_TIMEOUT = 120; no
#     cron.script_timeout_seconds override in ~/.hermes/config.yaml).
#
# The fix, therefore, is to stop demanding proof that cannot arrive inside the
# job's own lifetime, without ever letting an unproven state become permanent:
#   a. BOOT GRACE — a process younger than BOOT_GRACE with a stale heartbeat is
#      BOOTING, not wedged. Do not kickstart it: killing a booting daemon
#      restarts the 180s clock and is itself a restart loop.
#   b. The verify POLLS for a heartbeat mtime strictly NEWER than the one taken
#      before the kickstart — a fresh write is proof; an old file can no longer
#      masquerade as one, nor be demanded of a daemon that has not finished a
#      cycle yet.
#   c. If no fresh write lands inside the window but a process exists that
#      STARTED AT/AFTER the kickstart, the restart demonstrably took. That is
#      reported as boot-in-progress (exit 0, info) — and counted.
#   d. Teeth: heartbeat older than HARD_DOWN, or MAX_UNVERIFIED consecutive
#      unverified restarts, is crit + exit 1 no matter how healthy the process
#      looks. Worst case to a page is bounded by both.
# ---------------------------------------------------------------------------
set -u

# Tunables are env-overridable (SEW_*) with production values as defaults, so
# test_signal_engine_watchdog.sh can drive every branch against fixtures instead
# of the live unit. Nothing here changes behaviour when the vars are unset.
REPO="${SEW_REPO:-$HOME/Documents/code/signalengine}"
LABEL="${SEW_LABEL:-com.signalengine.daemon}"
PLIST="${SEW_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
# Anchored on the `-m <module>` argv pair, not the bare module name. The loose
# pattern 'signal_engine.daemon' false-positives on ANY command line quoting the
# module — measured 2026-07-31: it matched PID 1914, a hermes_queue.py submit
# whose alert text was "signal_engine.daemon was not running...". A probe that
# mistakes its own alert relay for the daemon reports a corpse as healthy.
# [-] is the bracket trick: matches a literal "-m" without pgrep parsing a flag.
GUARD="${SEW_GUARD:-[-]m signal_engine\.daemon}"
HEARTBEAT="${SEW_HEARTBEAT:-$REPO/data_store/daemon_control.json}"
STALE_AFTER="${SEW_STALE_AFTER:-600}"      # 10 min; above this a live PID is wedged
BOOT_GRACE="${SEW_BOOT_GRACE:-600}"        # measured time-to-first-heartbeat 180s; 3.3x margin
HARD_DOWN="${SEW_HARD_DOWN:-1800}"         # 30 min with no heartbeat = crit, no excuses
VERIFY_WINDOW="${SEW_VERIFY_WINDOW:-45}"   # poll budget after kickstart (scheduler kills at 120s)
VERIFY_POLL="${SEW_VERIFY_POLL:-5}"        # sample interval inside that window
MAX_UNVERIFIED="${SEW_MAX_UNVERIFIED:-3}"  # consecutive restarts w/o a fresh heartbeat -> crit
ALERT_COOLDOWN="${SEW_ALERT_COOLDOWN:-3600}" # don't re-page the same signature within the hour
STAMP_DIR="${SEW_STAMP_DIR:-$HOME/.hermes/state}"
STAMP="$STAMP_DIR/signal-engine-probe.last-alert"
UNVERIFIED="$STAMP_DIR/signal-engine-probe.unverified"
QUEUE="${SEW_QUEUE:-$HOME/.hermes/scripts/hermes_queue.py}"
UID_NUM="$(id -u)"

mkdir -p "$STAMP_DIR" 2>/dev/null

# The daemon's stderr goes where the PLIST says, NOT to $REPO/daemon.err.log.
# That repo file has been frozen since 2026-07-31 while the unit has written
# ~13 MB to StandardErrorPath — the old failure branch tailed the frozen one and
# printed 13-day-old lines as if they were the crash it was reporting.
ERRLOG="${SEW_ERRLOG:-}"
if [ -z "$ERRLOG" ]; then
  ERRLOG="$(/usr/libexec/PlistBuddy -c 'Print :StandardErrorPath' "$PLIST" 2>/dev/null)"
  [ -n "${ERRLOG:-}" ] || ERRLOG="$REPO/daemon.err.log"
fi

# --- observations -----------------------------------------------------------

alive_pid() { pgrep -f "$GUARD" 2>/dev/null | head -1; }

heartbeat_mtime() {
  [ -f "$HEARTBEAT" ] || { echo "-1"; return; }
  python3 - "$HEARTBEAT" <<'PY' 2>/dev/null || echo "-1"
import os, sys
print(int(os.path.getmtime(sys.argv[1])))
PY
}

heartbeat_age() {
  local m; m="$(heartbeat_mtime)"
  [ "$m" -ge 0 ] 2>/dev/null || { echo "-1"; return; }
  echo $(( $(date +%s) - m ))
}

# Process age in seconds. macOS ps has NO `etimes` keyword (verified: "ps: etimes:
# keyword not found"), only `etime` in [[dd-]hh:]mm:ss — so it is parsed here.
proc_age_secs() {
  local pid="${1:-}" et
  [ -n "$pid" ] || { echo "-1"; return; }
  et="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ -n "$et" ] || { echo "-1"; return; }
  python3 - "$et" <<'PY' 2>/dev/null || echo "-1"
import sys
s = sys.argv[1]; d = 0
if '-' in s:
    ds, s = s.split('-', 1); d = int(ds)
p = [int(x) for x in s.split(':')]
while len(p) < 3:
    p.insert(0, 0)
print(d * 86400 + p[0] * 3600 + p[1] * 60 + p[2])
PY
}

# launchd's own view. Empty string when the unit is not loaded at all.
unit_print() { launchctl print "gui/$UID_NUM/$LABEL" 2>/dev/null; }
unit_field() { printf '%s\n' "$1" | grep -m1 "$2" | sed 's/.*= *//' | tr -d ' "'; }

# --- unverified-restart counter ---------------------------------------------
# Bounds branch (c): a restart that takes but never produces a heartbeat is
# tolerated at most MAX_UNVERIFIED times (~15 min at the */5 schedule) before it
# is paged as crit. Reset ONLY by an observed fresh heartbeat.
unverified_count() { cat "$UNVERIFIED" 2>/dev/null | tr -dc '0-9' | head -c 4; }
unverified_bump()  { local n; n="$(unverified_count)"; echo $(( ${n:-0} + 1 )) > "$UNVERIFIED"; }
unverified_reset() { rm -f "$UNVERIFIED" 2>/dev/null; }

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
  # Severity follows the signature: a self-heal that already proved itself, or a
  # restart that demonstrably took and is still booting, is not an unresolved
  # outage and must not page at the same severity as one. Every other signature
  # here means the probe is exiting non-zero with the daemon down/unproven —
  # those stay crit. Add new call sites to one of the two buckets, never a bare
  # default.
  case "$sig" in
    recovered|restart-booting) severity="info" ;;
    *) severity="crit" ;;
  esac
  # Hard time limit on the relay. A normal submit takes ~0.1s (measured), but a
  # leaked one was found wedged for 5+ minutes (PID 1914, 2026-07-31) from the
  # old watchdog. Cron kills the whole job on script_timeout, so an unbounded
  # relay call could swallow the probe's own verdict. Report, never block.
  local to=""
  command -v timeout >/dev/null 2>&1 && to="timeout 15"
  $to python3 "$QUEUE" submit \
    --source signal-engine-probe --severity "$severity" --message "$msg" \
    >/dev/null 2>&1 || true
}

clear_alert_stamp() { rm -f "$STAMP" 2>/dev/null; }

# --- fast path: already healthy --------------------------------------------

PID="$(alive_pid)"
AGE="$(heartbeat_age)"

if [ -n "$PID" ] && [ "$AGE" -ge 0 ] && [ "$AGE" -lt "$STALE_AFTER" ]; then
  clear_alert_stamp
  unverified_reset
  exit 0
fi

# --- boot grace: a young process has not MISSED a heartbeat, it OWES one -----
# This branch is why the CRON_ERROR stopped: the daemon needs ~180s to reach its
# first write_state(), and launchd's KeepAlive can restart it at any moment.
# Bouncing it here would reset that clock forever. Bounded by HARD_DOWN.

if [ -n "$PID" ]; then
  PAGE="$(proc_age_secs "$PID")"
  if [ "$PAGE" -ge 0 ] && [ "$PAGE" -lt "$BOOT_GRACE" ] \
     && { [ "$AGE" -lt 0 ] || [ "$AGE" -lt "$HARD_DOWN" ]; }; then
    echo "⏳ Signal Engine PID $PID is ${PAGE}s old (< ${BOOT_GRACE}s boot grace); heartbeat ${AGE}s."
    echo "   First write_state() lands ~180s after boot (measured) — not restarting a booting daemon."
    exit 0
  fi
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

PRE_MTIME="$(heartbeat_mtime)"   # the bar a real write must clear; -1 if no file
KICK_AT="$(date +%s)"

echo "  Kickstarting $LABEL (launchctl kickstart -k)..."
if ! launchctl kickstart -k "gui/$UID_NUM/$LABEL" 2>&1; then
  echo "  ERROR: kickstart failed." >&2
  alert "kickstart-failed" "Signal Engine: launchctl kickstart of $LABEL failed"
  exit 1
fi

# Poll for a heartbeat mtime STRICTLY NEWER than the pre-kickstart one. The old
# code compared the surviving file's age to STALE_AFTER, which after a restart
# is a test of how long the daemon was ALREADY down — never of the restart.
FRESH=0
DEADLINE=$(( KICK_AT + VERIFY_WINDOW ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  sleep "$VERIFY_POLL"
  NOW_MTIME="$(heartbeat_mtime)"
  if [ "$NOW_MTIME" -gt "$PRE_MTIME" ] 2>/dev/null; then FRESH=1; break; fi
done

NEW_PID="$(alive_pid)"
NEW_AGE="$(heartbeat_age)"
NEW_PAGE="$(proc_age_secs "$NEW_PID")"
NEW_EXIT="$(unit_field "$(unit_print)" 'last exit code = ')"

if [ "$FRESH" -eq 1 ] && [ -n "$NEW_PID" ]; then
  echo "  ✅ Verified: PID $NEW_PID up, heartbeat written ${NEW_AGE}s ago (newer than pre-restart)."
  clear_alert_stamp
  unverified_reset
  alert "recovered" "Signal Engine daemon was down; kickstarted and VERIFIED alive (PID $NEW_PID)"
  exit 0
fi

# No fresh write yet. If a process exists that started at/after the kickstart,
# the restart itself demonstrably took — the daemon is inside its ~180s
# time-to-first-heartbeat. Tolerate, but only under both fences below.
ELAPSED=$(( $(date +%s) - KICK_AT ))
if [ -n "$NEW_PID" ] && [ "$NEW_PAGE" -ge 0 ] && [ "$NEW_PAGE" -le $(( ELAPSED + 30 )) ] \
   && { [ "$NEW_AGE" -lt 0 ] || [ "$NEW_AGE" -lt "$HARD_DOWN" ]; }; then
  unverified_bump
  N="$(unverified_count)"
  if [ "${N:-0}" -lt "$MAX_UNVERIFIED" ]; then
    echo "  ⏳ Restart TOOK: PID $NEW_PID is ${NEW_PAGE}s old (spawned by this kickstart)."
    echo "     No heartbeat inside the ${VERIFY_WINDOW}s window — expected, first write is ~180s in."
    echo "     Unverified restarts: ${N}/${MAX_UNVERIFIED}; next probe adjudicates."
    alert "restart-booting" "Signal Engine restarted (PID $NEW_PID) and is booting; heartbeat pending (${N}/${MAX_UNVERIFIED})"
    exit 0
  fi
  echo "  ❌ Restart keeps taking but NO heartbeat has EVER landed: ${N} consecutive unverified restarts." >&2
  echo "     PID $NEW_PID (${NEW_PAGE}s old), heartbeat_age='${NEW_AGE}s', last_exit='${NEW_EXIT:-?}'" >&2
  tail -5 "$ERRLOG" 2>/dev/null | sed 's/^/       /' >&2
  alert "restart-never-heartbeats" "Signal Engine: ${N} consecutive restarts took but produced no heartbeat; daemon is not completing a cycle"
  exit 1
fi

# The whole point: a restart that did not take is a FAILURE, reported as one.
echo "  ❌ NOT VERIFIED after ${ELAPSED}s: pid='${NEW_PID:-none}' proc_age='${NEW_PAGE}s' heartbeat_age='${NEW_AGE}s' last_exit='${NEW_EXIT:-?}'" >&2
echo "     Last 5 lines of $ERRLOG:" >&2
tail -5 "$ERRLOG" 2>/dev/null | sed 's/^/       /' >&2
alert "restart-not-verified" "Signal Engine daemon restart did NOT take (last_exit=${NEW_EXIT:-?}); daemon is down"
exit 1
