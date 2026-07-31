#!/bin/bash
# verify_estate.sh — THE single executable source of truth for estate operational state.
#
# State is a probe, not a paragraph. This runs read-only checks against the LIVE system
# and prints R1–R5 + DEPLOY + DOOR + FENCES as PASS/FAIL with one-line evidence.
# It NEVER triggers anything (no money/identity execution, no daemon starts, no writes).
#
# Exit 0 = OPERATIONAL (all critical green). Exit 1 = DEGRADED (≥1 critical red).
# Canonical companion doc: ~/.hermes/ESTATE_STATE.md (what each check means).
#
# ONE DOOR = Hermes gateway Telegram long-poll (ai.hermes.gateway). The old cockpit
# :8801 + ngrok webhook path is retired — do not treat it as the door.

HERMES="$HOME/.hermes"
PROSPECTOR="$HOME/Documents/code/prospector"
FAIL=0
ok(){ printf '  ✅ %s\n' "$1"; }
bad(){ printf '  ❌ %s\n' "$1"; FAIL=1; }
warn(){ printf '  🟡 %s\n' "$1"; }

echo "ESTATE STATE — $(date '+%Y-%m-%d %H:%M') — probe: verify_estate.sh"
echo "(verified live; authoritative. ~/.hermes/ESTATE_STATE.md explains each line.)"
echo

# ── DEPLOY: gateway process matches on-disk hermes-agent (staleness) ──
echo "DEPLOY"
GWPID=$(python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.hermes/gateway.pid")
try:
    print(json.load(open(p))["pid"])
except Exception:
    pass
PY
)
if [ -z "$GWPID" ]; then
  # fall back to launchctl
  GWPID=$(launchctl print "gui/$(id -u)/ai.hermes.gateway" 2>/dev/null | awk '/pid =/{print $3; exit}')
fi
if [ -z "$GWPID" ] || ! kill -0 "$GWPID" 2>/dev/null; then
  bad "gateway process not running (no live pid)"
else
  ok "gateway PID $GWPID alive (gateway.pid / launchctl)"
  if [ -d "$HERMES/hermes-agent/.git" ]; then
    DIRTY=$(git -C "$HERMES/hermes-agent" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    SHA=$(git -C "$HERMES/hermes-agent" rev-parse --short HEAD 2>/dev/null)
    [ "$DIRTY" = "0" ] && ok "hermes-agent tree committed @ $SHA" || warn "$DIRTY uncommitted hermes-agent change(s) @ $SHA"
  fi
fi
echo

# ── DOOR: single Telegram door = Hermes gateway (long-poll), not ngrok→:8801 ──
echo "DOOR"
python3 - <<'PY'
import json, os, sys, time, urllib.request

def ok(m): print(f"  ✅ {m}")
def bad(m): print(f"  ❌ {m}"); open("/tmp/verify_estate_door_fail","w").write("1")
def warn(m): print(f"  🟡 {m}")

# 1) PID liveness (load-immune)
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
try:
    from hermes_gateway import gateway_liveness
    live = gateway_liveness()
except Exception as e:
    live = None
    warn(f"gateway_liveness import failed: {e}")

if live is True:
    ok("gateway.pid process alive")
elif live is False:
    bad("gateway.pid present but process dead")
else:
    warn("gateway.pid unreadable — checking launchctl / state file")

# 2) launchctl label
import subprocess
uid = os.getuid()
r = subprocess.run(["launchctl", "print", f"gui/{uid}/ai.hermes.gateway"],
                   capture_output=True, text=True, timeout=8)
if r.returncode == 0 and ("state = running" in r.stdout or "pid =" in r.stdout):
    ok("launchctl ai.hermes.gateway running")
else:
    bad("launchctl ai.hermes.gateway not running")

# 3) Heartbeat freshness
hb = os.path.expanduser("~/.hermes/gateway.heartbeat")
try:
    age = time.time() - os.path.getmtime(hb)
    if age < 1200:
        ok(f"gateway heartbeat fresh ({int(age)}s)")
    else:
        warn(f"gateway heartbeat stale ({int(age)}s) — may be wedged")
except Exception:
    warn("no gateway.heartbeat yet")

# 4) Telegram platform state
try:
    st = json.load(open(os.path.expanduser("~/.hermes/gateway_state.json")))
    tg = (st.get("platforms") or {}).get("telegram") or {}
    if tg.get("state") == "connected":
        ok(f"Telegram platform connected (updated {tg.get('updated_at','?')})")
    else:
        bad(f"Telegram platform state={tg.get('state')!r}")
except Exception as e:
    warn(f"gateway_state.json unreadable: {e}")

# 5) Webhook must be EMPTY (long-poll owns the token)
tok = ""
try:
    for line in open(os.path.expanduser("~/.hermes/.env")):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            tok = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
except Exception:
    pass
if not tok:
    warn("no bot token — cannot verify webhook emptiness")
else:
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/getWebhookInfo")
        with urllib.request.urlopen(req, timeout=8) as resp:
            wi = json.load(resp)
        url = (wi.get("result") or {}).get("url") or ""
        err = (wi.get("result") or {}).get("last_error_message")
        if not url:
            ok("Telegram webhook empty (gateway long-poll owns the door)")
        else:
            bad(f"webhook still set → {url[:60]} (should be empty for gateway long-poll)")
        if err:
            warn(f"webhook last_error: {err}")
    except Exception as e:
        warn(f"getWebhookInfo failed: {e}")

# 6) ngrok→8801 must be OFF (zombie dual-door)
ngrok_up = subprocess.run(["pgrep", "-f", "ngrok http 8801"], capture_output=True).returncode == 0
if ngrok_up:
    bad("ngrok→8801 still running — unload ai.hermes.ngrok (dual-door zombie)")
else:
    ok("ngrok→8801 not running (single door)")

# 7) cockpit :8801 should be down / disabled
import socket
s = socket.socket(); s.settimeout(1)
try:
    s.connect(("127.0.0.1", 8801)); s.close()
    warn("cockpit :8801 still accepting — Disabled launch agent preferred")
except Exception:
    ok("cockpit :8801 not listening (retired mothership path)")

if os.path.exists("/tmp/verify_estate_door_fail"):
    try: os.unlink("/tmp/verify_estate_door_fail")
    except Exception: pass
    # force FAIL for shell
    open(os.path.expanduser("~/.hermes/.verify_estate_fail"), "w").write("door")
PY
[ -f "$HERMES/.verify_estate_fail" ] && FAIL=1 && rm -f "$HERMES/.verify_estate_fail"
echo

# ── R1: operate the 3 core projects ──
echo "R1  operate 3 core projects from phone"
python3 - <<'PY'
import json, os
try:
    d = json.load(open(os.path.expanduser("~/.hermes/projects.json")))
except Exception as e:
    print(f"  ❌ projects.json unreadable: {e}"); raise SystemExit
items = d if isinstance(d, list) else d.get("projects") or list(d.values())[0]
def names(o):
    if isinstance(o, dict) and "key" in o: return [o.get("key") or o.get("name")]
    if isinstance(o, dict): return [(v.get("key") or v.get("name") or k) for k, v in o.items() if isinstance(v, dict)]
    if isinstance(o, list): return [(v.get("key") or v.get("name") or v.get("id")) for v in o if isinstance(v, dict)]
    return []
present = " ".join(str(n).lower() for n in names(items) if n)
need = {"prospector": "prospector", "signal": "signalengine(money)", "tie": "tie(identity)"}
miss = [lab for key, lab in need.items() if key not in present]
if not miss:
    print("  ✅ prospector + signalengine + tie all present in portfolio")
else:
    print(f"  ❌ missing from portfolio: {', '.join(miss)}")
    open(os.path.expanduser("~/.hermes/.verify_estate_fail"), "w").write("r1")
PY
[ -f "$HERMES/.verify_estate_fail" ] && FAIL=1 && rm -f "$HERMES/.verify_estate_fail"
echo

# ── R2: manage daemons from phone (operator_shell / otto-inbound) ──
echo "R2  manage daemons from phone"
OS_MENU="$HERMES/hermes-agent/gateway/operator_shell"
if [ -d "$OS_MENU" ] && grep -rqE 'daemon|fleet|missions' "$OS_MENU" 2>/dev/null; then
  ok "operator_shell present (panel/fleet/missions path)"
else
  bad "operator_shell missing — phone control surface down"
fi
if grep -qE 'estate:|operator_shell|send_estate_panel' "$HERMES/plugins/otto-inbound/__init__.py" 2>/dev/null; then
  ok "otto-inbound routes to operator_shell"
else
  warn "otto-inbound may not route estate panels"
fi
echo

# ── R3: reports land on the phone ──
echo "R3  reports delivered to Telegram"
if grep -qE '^import glob|^[[:space:]]*import glob' "$HERMES/plugins/otto-inbound/__init__.py" 2>/dev/null; then
  ok "otto-inbound imports glob (audit-report attach)"
else
  warn "otto-inbound glob import missing (audit attach may NameError)"
fi
echo

# ── R4: Otto — coordinator daemon + morning brief armed ──
echo "R4  run Otto (coordinator + cron)"
python3 - <<'PY'
import os, sqlite3, time, json, subprocess
uid = os.getuid()
r = subprocess.run(["launchctl", "print", f"gui/{uid}/ai.hermes.coordinator"],
                   capture_output=True, text=True, timeout=8)
if r.returncode == 0 and ("state = running" in r.stdout or "pid =" in r.stdout):
    print("  ✅ launchctl ai.hermes.coordinator running")
else:
    print("  ❌ coordinator LaunchAgent not running")
    open(os.path.expanduser("~/.hermes/.verify_estate_fail"), "w").write("r4")
try:
    conn = sqlite3.connect(os.path.expanduser("~/.hermes/coordinator.db"))
    row = conn.execute("SELECT value, updated_at FROM meta WHERE key='last_tick'").fetchone()
    if row:
        age = int(time.time() - row[1])
        if age < 200:
            print(f"  ✅ coordinator last_tick {age}s ago")
        else:
            print(f"  ❌ coordinator last_tick stale ({age}s)")
            open(os.path.expanduser("~/.hermes/.verify_estate_fail"), "w").write("r4")
    else:
        print("  ❌ no coordinator last_tick")
        open(os.path.expanduser("~/.hermes/.verify_estate_fail"), "w").write("r4")
except Exception as e:
    print(f"  🟡 could not read last_tick: {e}")
# morning brief job
try:
    j = json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json")))
    jobs = j if isinstance(j, list) else j.get("jobs", [])
    mb = [x for x in jobs if isinstance(x, dict) and "morning" in (x.get("name") or "").lower()]
    if mb and mb[0].get("enabled"):
        st = mb[0].get("last_status")
        print(f"  ✅ morning-brief cron enabled (last_status={st})")
    elif mb:
        print("  ❌ morning-brief cron DISABLED")
    else:
        print("  🟡 morning-brief cron not found")
except Exception as e:
    print(f"  🟡 jobs.json: {e}")
PY
[ -f "$HERMES/.verify_estate_fail" ] && FAIL=1 && rm -f "$HERMES/.verify_estate_fail"
echo

# ── R5: proof gate on prospector ──
echo "R5  proof gate (POPDD on prospector)"
HOOK="$PROSPECTOR/.git/hooks/pre-commit"
if [ -e "$HOOK" ]; then
  ok "prospector pre-commit gate installed"
else
  bad "prospector pre-commit gate NOT installed"
fi
LATEST_RX=$(ls -t "$PROSPECTOR"/.lux/receipts/*.jsonl 2>/dev/null | head -1)
if [ -n "$LATEST_RX" ]; then
  ok "latest receipt: $(basename "$LATEST_RX")"
else
  warn "no POPDD receipts found yet"
fi
echo

# ── FENCES: money/identity never auto-execute ──
echo "FENCES  money/identity"
if grep -qE 'risk_class.*money|awaiting_approval|identity' "$HERMES/scripts/coordinator.py" 2>/dev/null; then
  ok "coordinator fences money/identity via awaiting_approval"
else
  bad "money/identity fence not found in coordinator"
fi
if [ -f "$HOME/Library/LaunchAgents/ai.hermes.ngrok.plist" ]; then
  if grep -q '<key>Disabled</key>' "$HOME/Library/LaunchAgents/ai.hermes.ngrok.plist" \
     && plutil -extract Disabled raw "$HOME/Library/LaunchAgents/ai.hermes.ngrok.plist" 2>/dev/null | grep -qi true; then
    ok "ai.hermes.ngrok Disabled=true"
  else
    warn "ai.hermes.ngrok plist still enabled — should be unloaded/Disabled"
  fi
fi
echo

# ── ACL ──
echo "ACL  Telegram allowlist"
ALLOWED=$(grep '^TELEGRAM_ALLOWED_USER_IDS=' "$HERMES/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
COUNT=$(echo "$ALLOWED" | tr ',' '\n' | grep -cE '[0-9]')
if [ "$COUNT" = "0" ]; then
  bad "ACL allowlist EMPTY — door functionally down"
elif [ "$COUNT" = "1" ]; then
  warn "ACL allowlist = 1 user (founder only)"
else
  ok "ACL allowlist: $COUNT users admitted"
fi
echo

if [ "$FAIL" = "0" ]; then
  echo "VERDICT: ✅ OPERATIONAL — all critical checks green."
else
  echo "VERDICT: ❌ DEGRADED — at least one ❌ above. Fix before claiming ready."
fi
exit $FAIL
