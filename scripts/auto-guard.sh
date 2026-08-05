#!/bin/bash
# auto-guard.sh — File watcher that auto-runs preflight + safe restart on code changes.
# Run once and leave it: nohup ./scripts/auto-guard.sh &
# Watches the gateway operator_shell directory for .py changes.
# On change: waits for settle (no changes for 3s), runs preflight, restarts if safe.

HERMES="$HOME/.hermes"
WATCH_DIR="$HERMES/hermes-agent/gateway/operator_shell"
DEBOUNCE=3  # Wait 3s after last change before acting

echo "🛡️ Auto-Guard watching: $WATCH_DIR"
echo "   Debounce: ${DEBOUNCE}s · Preflight gates every restart"
echo ""

if ! command -v fswatch &>/dev/null; then
    echo "Installing fswatch..."
    brew install fswatch 2>/dev/null || pip3 install fswatch 2>/dev/null || {
        echo "❌ Cannot install fswatch. Using polling fallback."
        # Fallback: poll every 5 seconds
        POLL_MODE=1
    }
fi

last_mtime=0
restart_count=0

while true; do
    if [ -n "$POLL_MODE" ]; then
        # Polling mode
        current=$(find "$WATCH_DIR" -name "*.py" -newer "$HERMES/scripts/.auto-guard-timestamp" 2>/dev/null | head -1)
        if [ -n "$current" ]; then
            touch "$HERMES/scripts/.auto-guard-timestamp"
            changed=1
        else
            changed=0
        fi
        sleep 3
    else
        # fswatch mode — blocks until change
        fswatch -1 --latency="$DEBOUNCE" "$WATCH_DIR" --include="\.py$" 2>/dev/null
        changed=1
    fi
    
    if [ "$changed" -eq 1 ]; then
        # Wait for settle
        sleep "$DEBOUNCE"
        
        echo ""
        echo "📝 $(date '+%H:%M:%S') — Change detected"
        
        # Run preflight
        if python3 "$HERMES/scripts/preflight.py" >/tmp/preflight.log 2>&1; then
            echo "✅ Preflight passed — restarting..."
            bash "$HERMES/scripts/safe-restart.sh" 2>&1 | tail -3
            restart_count=$((restart_count + 1))
            echo "   Restarts today: $restart_count"
        else
            echo "❌ Preflight FAILED — NOT restarting"
            grep "❌" /tmp/preflight.log 2>/dev/null | head -5
            echo "   Fix errors above. Auto-guard will retry on next change."
        fi
    fi
done
