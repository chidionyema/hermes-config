#!/bin/bash
# signal-engine-daemon-watchdog — silent when healthy.
#
# Launches the LOOPING daemon (signal_engine.daemon:main), NOT the one-shot batch
# job (signal-engine-run -> run_m1:run_e2e). The old script launched the batch,
# which runs once and exits by design, so the watchdog "restarted" it every 5 min
# forever. The guard pattern now matches the daemon's ACTUAL argv
# ("signal_engine.daemon", underscore); the old pattern "signal-engine" (hyphen)
# could never match it, so the watchdog was also blind to any real daemon.
set -u

REPO="$HOME/Documents/code/signalengine"
PY="$REPO/.venv/bin/python"
GUARD='signal_engine.daemon'   # MUST match the `-m` target on the launch line below

# Already running?  (matches `<python> -m signal_engine.daemon`)
if pgrep -f "$GUARD" > /dev/null 2>&1; then
  exit 0
fi

echo "⚠️  Signal Engine daemon not running. Restarting..."

if [ ! -x "$PY" ]; then
  echo "  ERROR: interpreter not found/executable: $PY" >&2
  exit 1
fi

cd "$REPO" || { echo "  ERROR: cannot cd $REPO" >&2; exit 1; }

# cron inherits VIRTUAL_ENV pointing at the hermes-agent venv; unset it so nothing
# tries to reconcile it against this project's .venv (the boot warning's source).
unset VIRTUAL_ENV

# PYTHONUNBUFFERED so a real crash flushes its traceback to daemon.err.log instead
# of dying with a block-buffered, empty log. stdout/stderr are SPLIT and APPENDED
# (>>) so a crash loop leaves every traceback on disk for forensics.
PYTHONUNBUFFERED=1 nohup "$PY" -m signal_engine.daemon \
  >> "$REPO/daemon.out.log" 2>> "$REPO/daemon.err.log" &
DAEMON_PID=$!

# Relay (FIRE 0): submit to Otto's queue so Otto triages this restart instead of the
# user getting a raw alert. Never let a queue hiccup break the watchdog (|| true).
python3 "$HOME/.hermes/scripts/hermes_queue.py" submit \
  --source signal-engine-watchdog --severity crit \
  --message "signal_engine.daemon was not running; restarted PID $DAEMON_PID" \
  >/dev/null 2>&1 || true

echo "  Started PID $DAEMON_PID ($PY -m signal_engine.daemon)"
exit 0
