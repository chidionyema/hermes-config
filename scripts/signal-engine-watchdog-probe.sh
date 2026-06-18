#!/bin/bash
# signal-engine-watchdog-probe — FIRE 1 loop-closer.
# Verifies the watchdog can actually SEE and (re)launch the daemon it supervises.
# A watchdog whose guard pattern does not match its own launch target silently
# restart-loops (the original bug: guard "signal-engine" never matched
# "signal_engine.daemon"). This probe fails loudly on that class of misconfig.
#
# Checks (receipts, not claims):
#   (a) launch interpreter exists and is executable
#   (b) guard pgrep pattern is consistent with the launched module path
#       (catches the hyphen/underscore mismatch even when the daemon is DOWN)
#   (c) if a daemon is running, the guard pattern actually matches its PID(s)
#
# Exit 0 = consistent. Exit 1 = misconfig (would restart-loop) or interpreter gone.
set -u

WATCHDOG="${1:-$HOME/.hermes/scripts/signal-engine-daemon-watchdog.sh}"
REPO="$HOME/Documents/code/signalengine"
fail=0
note() { printf '%s\n' "$*"; }
bad()  { printf 'FAIL: %s\n' "$*"; fail=1; }

[ -f "$WATCHDOG" ] || { bad "watchdog script not found: $WATCHDOG"; exit 1; }

# Parse the watchdog AS WRITTEN (not a hardcoded copy) so the probe tracks drift.
GUARD=$(grep -oE "GUARD='[^']+'" "$WATCHDOG" | head -1 | sed -E "s/GUARD='([^']+)'/\1/")
MODULE=$(grep -oE -- '-m [A-Za-z0-9_.]+' "$WATCHDOG" | head -1 | sed -E 's/-m //')
PY_RAW=$(grep -oE 'PY="[^"]+"' "$WATCHDOG" | head -1 | sed -E 's/PY="([^"]+)"/\1/')
PY="${PY_RAW/\$REPO/$REPO}"; PY="${PY/\$HOME/$HOME}"

note "watchdog   : $WATCHDOG"
note "guard      : ${GUARD:-<none found>}"
note "interpreter: ${PY:-<none found>}"
note "module     : ${MODULE:-<none found>}"
note "---"

# (a) interpreter exists & is executable
if [ -n "$PY" ] && [ -x "$PY" ]; then
  note "OK   (a) interpreter exists & executable: $PY"
else
  bad "(a) interpreter missing/not executable: '${PY:-<none>}' (old watchdog used 'uv run' — no fixed interpreter)"
fi

# (b) guard consistent with launch module — catches hyphen/underscore mismatch
#     even when the daemon is DOWN (the most valuable static check).
if [ -n "$GUARD" ] && [ -n "$MODULE" ] && printf '%s' "$MODULE" | grep -qE "$GUARD"; then
  note "OK   (b) guard '$GUARD' matches launch module '$MODULE'"
else
  bad "(b) guard '${GUARD:-<none>}' does NOT match launch module '${MODULE:-<none>}' — RESTART-LOOP RISK"
fi

# (c) live consistency: if something is running under the module path, the guard
#     must also see it; otherwise the watchdog is blind and will spawn a duplicate.
if [ -n "$MODULE" ]; then
  RUN=$(pgrep -f "$MODULE" 2>/dev/null | tr '\n' ' ')
  if [ -n "$RUN" ]; then
    SEEN=$(pgrep -f "$GUARD" 2>/dev/null | tr '\n' ' ')
    if [ -n "$SEEN" ]; then
      note "OK   (c) daemon running [pids: $RUN]; guard sees it [pids: $SEEN]"
    else
      bad "(c) daemon running [pids: $RUN] but guard '$GUARD' matches NOTHING — watchdog blind, will duplicate"
    fi
  else
    note "WARN (c) no process under '$MODULE' right now (watchdog will launch on next tick)"
  fi
fi

note "---"
if [ "$fail" -eq 0 ]; then
  note "PROBE: PASS — watchdog can see and launch its target."
  exit 0
else
  note "PROBE: FAIL — watchdog misconfigured (see FAIL lines)."
  exit 1
fi
