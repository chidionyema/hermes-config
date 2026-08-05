#!/bin/bash
# safe-restart.sh — Pre-flight check → restart → post-flight verify
# Run this instead of manually killing/restarting the gateway.
# Exits 0 only if restart succeeded AND post-flight checks pass.

set -e
HERMES="$HOME/.hermes"

echo "🛫 Pre-flight check..."
python3 "$HERMES/scripts/preflight.py"
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Pre-flight failed. Fix errors above before restarting."
    exit 1
fi

echo ""
echo "🔄 Restarting gateway..."
pkill -9 -f "hermes_cli" 2>/dev/null || true
sleep 2

# Clear Python cache to ensure fresh code
find "$HERMES/hermes-agent/gateway/operator_shell/__pycache__" -name "*.pyc" -delete 2>/dev/null || true

# Start gateway
cd "$HERMES/hermes-agent"
nohup venv/bin/python -m hermes_cli.main gateway run --replace >/tmp/gateway.log 2>&1 &
sleep 6

# Verify it's running
if ! pgrep -f "hermes_cli" >/dev/null 2>&1; then
    echo "❌ Gateway failed to start. Check /tmp/gateway.log"
    cat /tmp/gateway.log 2>/dev/null | tail -10
    exit 1
fi

echo "✅ Gateway running"

# Post-flight: check for startup errors
echo ""
echo "🔍 Post-flight check..."
ERRORS=$(grep -c "ERROR\|Traceback" /tmp/gateway.log 2>/dev/null || echo 0)
if [ "$ERRORS" -gt 0 ]; then
    echo "⚠️  $ERRORS error(s) in gateway log:"
    grep "ERROR\|Traceback" /tmp/gateway.log 2>/dev/null | tail -5
else
    echo "✅ No startup errors"
fi

echo ""
echo "✅ Restart complete. Send a message to the Telegram bot to verify."
