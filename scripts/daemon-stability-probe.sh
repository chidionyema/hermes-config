#!/bin/bash
# daemon-stability-probe — fires when signal_engine.daemon restarts 2+ times in 1h.
#
# The alive-check watchdog only sees "is it up right now" and so is blind to a flapping
# daemon that dies and gets restarted between checks. This probe reads the restart
# evidence directly: each crash leaves a fresh "Signal Engine Daemon starting..." line
# in daemon.err.log. >= HERMES_DAEMON_RESTART_MAX (default 2) starts within the last
# hour == a restart loop -> submit to the relay queue and exit 2. A stable daemon (0-1
# starts in the window) is silent, exit 0.
set -u
REPO="${SIGNALENGINE_REPO:-$HOME/Documents/code/signalengine}"
LOG="$REPO/daemon.err.log"
MAX="${HERMES_DAEMON_RESTART_MAX:-2}"
Q="$HOME/.hermes/scripts/hermes_queue.py"

[ -f "$LOG" ] || { echo "daemon-stability: no log ($LOG) — PASS"; exit 0; }

N=$(grep "Daemon starting" "$LOG" 2>/dev/null \
  | sed -E 's/^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+).*/\1/' \
  | python3 -c "
import sys,datetime
now=datetime.datetime.now()
n=0
for line in sys.stdin:
    line=line.strip()
    try: t=datetime.datetime.fromisoformat(line)
    except ValueError: continue
    if (now-t).total_seconds() <= 3600: n+=1
print(n)
")

if [ "${N:-0}" -ge "$MAX" ]; then
  msg="signal_engine.daemon restarted ${N}x in last 1h (restart loop) — see daemon.err.log"
  [ -f "$Q" ] && python3 "$Q" submit --source signal-engine-stability --severity crit \
    --message "$msg" --fingerprint "signal-engine-restart-loop" >/dev/null 2>&1
  echo "daemon-stability: FAIL — $msg"
  exit 2
fi
echo "daemon-stability: ${N:-0} restart(s) in last 1h (< $MAX) — PASS"
exit 0
