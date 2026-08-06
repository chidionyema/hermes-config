#!/bin/bash
# Bring the Hermes web dashboard up and make it reachable from the phone.
#
# Why this script exists (2026-08-06): `hermes dashboard` runs `npm run build`
# (tsc -b && vite build) BEFORE it binds the port, so a plain launch sits silent
# for minutes and the URL reads as dead. --skip-build serves the prebuilt
# hermes_cli/web_dist directly. Two more traps this encodes:
#
#   * The server refuses any Host header other than the bound one (anti-DNS-
#     rebinding, GHSA-ppp5-vxwm-4cf7, web_server.py:374). A tunnel therefore
#     needs `--http-host-header 127.0.0.1:9119` or every request 400s.
#   * The session token is injected into the served HTML at web_server.py:10874,
#     so any browser that loads the page authenticates itself. That also means
#     THE URL IS THE CREDENTIAL — treat it as a secret.
#
# Writes ~/.hermes/state/dashboard_access.json, which /dashboard reads.
set -uo pipefail

PORT=9119
AGENT=~/.hermes/hermes-agent
STATE=~/.hermes/state
LOGDIR=~/.hermes/logs
mkdir -p "$STATE" "$LOGDIR"

TOKFILE=$STATE/dashboard_token
if [ ! -s "$TOKFILE" ]; then
  printf 'hermes-%s' "$(openssl rand -hex 16)" > "$TOKFILE"
  chmod 600 "$TOKFILE"
fi
TOKEN=$(cat "$TOKFILE")

say() { echo "[dashboard-up] $*"; }

# ---- 1. dashboard ---------------------------------------------------------
if curl -s -o /dev/null --max-time 4 "http://127.0.0.1:$PORT/"; then
  say "dashboard already serving on $PORT"
else
  say "starting dashboard on $PORT (skip-build)"
  HERMES_DASHBOARD_SESSION_TOKEN="$TOKEN" nohup "$AGENT/venv/bin/hermes" dashboard \
    --port "$PORT" --skip-build --no-open >> "$LOGDIR/dashboard.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/" && break
    sleep 2
  done
fi
if ! curl -s -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/"; then
  say "FAILED: dashboard did not bind $PORT — see $LOGDIR/dashboard.log"
  exit 1
fi
say "local  ✅ http://127.0.0.1:$PORT"

# ---- 2. tunnel ------------------------------------------------------------
URL=""
if pgrep -f "cloudflared tunnel --url http://127.0.0.1:$PORT" >/dev/null 2>&1; then
  URL=$(grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGDIR/dashboard-tunnel.log" 2>/dev/null | tail -1)
  say "tunnel already running: ${URL:-<url not in log>}"
fi
if [ -z "$URL" ]; then
  say "starting cloudflared quick tunnel"
  : > "$LOGDIR/dashboard-tunnel.log"
  nohup cloudflared tunnel --url "http://127.0.0.1:$PORT" \
    --http-host-header "127.0.0.1:$PORT" >> "$LOGDIR/dashboard-tunnel.log" 2>&1 &
  for _ in $(seq 1 30); do
    URL=$(grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGDIR/dashboard-tunnel.log" 2>/dev/null | head -1)
    [ -n "$URL" ] && break
    sleep 2
  done
fi

# ---- 3. verify the tunnel actually serves ---------------------------------
REACHABLE=false
if [ -n "$URL" ]; then
  for _ in $(seq 1 12); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "$URL/")" = "200" ]; then
      REACHABLE=true; break
    fi
    sleep 5
  done
fi
$REACHABLE && say "public ✅ $URL" || say "public ❌ tunnel not serving (falling back to local only)"

# ---- 4. publish for /dashboard -------------------------------------------
python3 - "$URL" "$TOKEN" "$PORT" "$REACHABLE" <<'PY'
import json, os, sys, pathlib
url, token, port, reachable = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "true"
p = pathlib.Path.home() / ".hermes" / "state" / "dashboard_access.json"
p.write_text(json.dumps({
    "url": url if reachable else "",
    "local_url": f"http://127.0.0.1:{port}",
    "token": token,
    "port": int(port),
    "public_reachable": reachable,
}, indent=2))
os.chmod(p, 0o600)
print(f"[dashboard-up] wrote {p}")
PY
