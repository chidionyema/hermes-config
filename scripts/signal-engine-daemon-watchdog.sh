#!/bin/bash
# signal-engine-daemon-watchdog — silent when healthy
if pgrep -f "signal-engine" > /dev/null 2>&1; then
  exit 0
fi
echo "⚠️  Signal Engine daemon not running. Restarting..."
cd ~/Documents/code/signalengine
nohup uv run signal-engine-run > daemon.log 2>&1 &
echo "  Started PID $!"
exit 0
