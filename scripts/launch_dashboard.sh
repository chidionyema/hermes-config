#!/bin/bash
# launch_dashboard.sh — Otto Dashboard with Cloudflare tunnel
# Usage: ./launch_dashboard.sh  or  `dashboard` (if alias set in ~/.zshrc)

set -e
HERMES="$HOME/.hermes"
PORT=8800
PIDFILE="/tmp/dashboard.pid"
CF_LOG="/tmp/cf_tunnel.log"

# Already running?
if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
    URL=$(grep -o "https://[a-z-]*\.trycloudflare\.com" "$CF_LOG" 2>/dev/null | tail -1)
    echo "✅ Dashboard running: ${URL:-see Telegram}"
    exit 0
fi

echo "=== Otto Dashboard ==="
echo $$ > "$PIDFILE"

# 1. Server
echo "[1/2] Server on :$PORT..."
cd "$HERMES"
PYTHONPATH="$HERMES/hermes-agent:$PYTHONPATH" \
    nohup python3 scripts/mini_app_server.py --port "$PORT" &>/tmp/miniapp.log &
sleep 2
if ! curl -sf http://127.0.0.1:$PORT/api/health >/dev/null 2>&1; then
    echo "❌ Server failed"
    rm -f "$PIDFILE"
    exit 1
fi
echo "   ✅ Ready"

# 2. Cloudflare tunnel (background, never piped — stays alive)
echo "[2/2] Tunnel..."
cloudflared tunnel --url http://localhost:$PORT >"$CF_LOG" 2>&1 &

# Wait for URL
for i in $(seq 1 15); do
    sleep 1
    URL=$(grep -o "https://[a-z-]*\.trycloudflare\.com" "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$URL" ]; then
        echo "   ✅ $URL"
        python3 -c "
import subprocess
msg = '\U0001f447 *Otto Dashboard*\n\n[\U0001f4f1 Open Dashboard]($URL)\n\n_Score \u00b7 Pipeline \u00b7 Activity \u00b7 Incidents_'
subprocess.run(['hermes', 'send', '--to', 'telegram', msg], capture_output=True, timeout=10)
" 2>/dev/null
        break
    fi
done

echo ""
echo "Ready. Kill: rm -f $PIDFILE; pkill -f mini_app_server; pkill -f cloudflared"
