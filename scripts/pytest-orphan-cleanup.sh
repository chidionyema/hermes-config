#!/bin/bash
# pytest-orphan-cleanup.sh — kills pytest processes whose PPID is 1
# (launchd-orphaned, the parent session died). Prevents the 243-pytest pile-up
# caused by the morning-briefing cron running pytest with no timeout.
#
# Idempotent: no-op if no orphans.
# Safe: leaves PID 1228 (signal_engine.daemon) alone — its argv is not "pytest".
set -u

ORPHANS=$(ps -axo pid,ppid,command 2>/dev/null | awk '$2==1 && /pytest/ {print $1}')
if [ -z "$ORPHANS" ]; then
  exit 0
fi

KILLED=0
for pid in $ORPHANS; do
  ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  if [ "$ppid" = "1" ] && [ "$pid" != "1228" ]; then
    kill -9 "$pid" 2>/dev/null && KILLED=$((KILLED+1))
  fi
done

if [ "$KILLED" -gt 0 ]; then
  echo "pytest-orphan-cleanup: killed $KILLED orphan pytest process(es)"
fi
exit 0