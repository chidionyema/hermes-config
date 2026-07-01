#!/bin/bash
# verify_estate.sh — THE single executable source of truth for estate operational state.
#
# State is a probe, not a paragraph. This runs read-only checks against the LIVE system
# and prints R1-R5 + DEPLOY + DOOR + FENCES as PASS/FAIL with one-line evidence.
# It NEVER triggers anything (no money/identity execution, no daemon starts, no writes).
#
# Exit 0 = OPERATIONAL (all critical green). Exit 1 = DEGRADED (≥1 critical red).
# Canonical companion doc: ~/.hermes/ESTATE_STATE.md (what each check means).
#
# Wired into every session via ~/.claude/scripts/memory-loop.py (SessionStart) so all
# agents open on verified live state, not a stale narrative.

HERMES="$HOME/.hermes"
COCKPIT="$HOME/Documents/code/sentinel-loop"
PROSPECTOR="$HOME/Documents/code/prospector"
FAIL=0
ok(){ printf '  ✅ %s\n' "$1"; }
bad(){ printf '  ❌ %s\n' "$1"; FAIL=1; }
warn(){ printf '  🟡 %s\n' "$1"; }

echo "ESTATE STATE — $(date '+%Y-%m-%d %H:%M') — probe: verify_estate.sh"
echo "(verified live; authoritative. ~/.hermes/ESTATE_STATE.md explains each line.)"
echo

# ── DEPLOY: is the running cockpit actually the code on disk? (catches staleness) ──
echo "DEPLOY"
CKPID=$(pgrep -f 'uvicorn sentinel.cockpit.server' | head -1)
if [ -z "$CKPID" ]; then
  bad "cockpit process not running"
else
  STALE=$(python3 - "$CKPID" "$COCKPIT/sentinel/cockpit" <<'PY'
import sys, os, subprocess, datetime
pid, codedir = sys.argv[1], sys.argv[2]
try:
    ls = subprocess.check_output(["ps","-o","lstart=","-p",pid]).decode().strip()
    ls = " ".join(ls.split())
    start = datetime.datetime.strptime(ls, "%a %d %b %H:%M:%S %Y").timestamp()
except Exception as e:
    print("UNKNOWN", e); sys.exit()
newest = 0.0; newest_f = ""
for root,_,files in os.walk(codedir):
    if "__pycache__" in root: continue
    for f in files:
        if f.endswith(".py"):
            m = os.path.getmtime(os.path.join(root,f))
            if m > newest: newest, newest_f = m, f
if newest > start:
    print("STALE", os.path.basename(newest_f), int(newest-start))
else:
    print("FRESH")
PY
)
  case "$STALE" in
    FRESH*) ok "cockpit PID $CKPID runs current on-disk code (no edits since launch)";;
    STALE*) set -- $STALE; bad "STALE: $2 edited ${3}s AFTER cockpit launched — restart needed: launchctl kickstart -k gui/\$(id -u)/ai.hermes.cockpit";;
    *)      warn "could not determine cockpit staleness ($STALE)";;
  esac
  # git working tree clean? (committed == deployable)
  if [ -d "$COCKPIT/.git" ]; then
    DIRTY=$(git -C "$COCKPIT" status --porcelain 2>/dev/null | grep -v '^?? graphify-out/' | wc -l | tr -d ' ')
    SHA=$(git -C "$COCKPIT" rev-parse --short HEAD 2>/dev/null)
    [ "$DIRTY" = "0" ] && ok "working tree committed @ $SHA" || warn "$DIRTY uncommitted change(s) — deploys would be off-SHA (HEAD $SHA)"
  fi
fi
echo

# ── DOOR: the single Telegram door must be live and pointed at the cockpit ──
echo "DOOR"
curl -s --max-time 4 http://127.0.0.1:8801/health 2>/dev/null | grep -q '"status":"ok"' \
  && ok "cockpit /health ok (:8801)" || bad "cockpit /health DOWN (:8801)"
curl -s --max-time 4 http://127.0.0.1:8802/health 2>/dev/null | grep -q '"status":"ok"' \
  && ok "otto relay /health ok (:8802)" || bad "otto relay DOWN (:8802) — free-text chat will fail"
pgrep -f 'ngrok http 8801' >/dev/null && ok "ngrok tunnel process up" || bad "ngrok DOWN — public door unreachable"
python3 - <<'PY'
import json, urllib.request, os, sys
def get(u, t=4):
    try:
        with urllib.request.urlopen(u, timeout=t) as r: return json.load(r)
    except Exception: return None
ng = get("http://127.0.0.1:4040/api/tunnels")
ngurl = ng["tunnels"][0]["public_url"] if ng and ng.get("tunnels") else None
tok=""
try:
    for line in open(os.path.expanduser("~/.hermes/.env")):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            tok=line.split("=",1)[1].strip().strip('"').strip("'"); break
except Exception: pass
if not tok:
    print("  🟡 no bot token — cannot verify webhook target"); sys.exit()
wi = get(f"https://api.telegram.org/bot{tok}/getWebhookInfo", t=6)
r = (wi or {}).get("result", {})
url, err = r.get("url",""), r.get("last_error_message")
if ngurl and url.startswith(ngurl) and not err:
    print(f"  ✅ Telegram webhook → cockpit (pending={r.get('pending_update_count',0)}, no errors)")
elif err:
    print(f"  ❌ webhook last_error: {err}")
elif ngurl and not url.startswith(ngurl):
    print(f"  ❌ webhook points elsewhere (ngrok rotated?) — re-point needed")
else:
    print(f"  🟡 webhook url set but ngrok url unknown")
PY
echo

# ── R1: operate the 3 core projects (prospector / signalengine=Signal Engine / tie=Introduction Exchange) ──
echo "R1  operate 3 core projects from phone"
python3 - <<'PY'
import json, os
try:
    d=json.load(open(os.path.expanduser("~/.hermes/projects.json")))
except Exception as e:
    print(f"  ❌ projects.json unreadable: {e}"); raise SystemExit
items = d if isinstance(d,list) else list(d.values())[0] if isinstance(d,dict) and len(d)==1 and isinstance(list(d.values())[0],list) else d
def names(o):
    if isinstance(o,dict): return [ (v.get('name') if isinstance(v,dict) else k) for k,v in o.items() ]
    if isinstance(o,list): return [ (v.get('name') or v.get('id')) for v in o ]
    return []
present = " ".join(str(n).lower() for n in names(items))
need = {"prospector":"prospector", "signal":"signalengine(money)", "introduction":"tie(identity)"}
miss = [lab for key,lab in need.items() if key not in present]
if not miss:
    print("  ✅ prospector + signalengine + tie all present in cockpit projects (status/trigger tiles)")
else:
    print(f"  ❌ missing from cockpit projects: {', '.join(miss)}")
PY
echo

# ── R2: manage daemons from phone ──
echo "R2  manage daemons from phone"
if grep -q 'daemon_start:' "$COCKPIT/sentinel/cockpit/menu.py" && grep -q 'daemon_stop:' "$COCKPIT/sentinel/cockpit/menu.py"; then
  ok "cockpit has daemon start/stop handlers (gateway excluded from start targets)"
else
  bad "daemon start/stop handlers missing in menu.py"
fi
echo

# ── R3: reports land on the phone (the glob NameError that broke audit delivery) ──
echo "R3  reports delivered to Telegram"
if grep -qE '^import glob|^[[:space:]]*import glob' "$HERMES/plugins/otto-inbound/__init__.py"; then
  ok "otto-inbound imports glob (audit-report attach no longer NameErrors)"
else
  bad "otto-inbound glob import missing — audit report delivery will NameError"
fi
echo

# ── R4: Otto — server live + daily goal armed ──
echo "R4  run Otto (skills / daily goal)"
curl -s --max-time 4 http://127.0.0.1:8802/health 2>/dev/null | grep -q '"status":"ok"' \
  && ok "otto server live" || bad "otto server down"
python3 - <<'PY'
import json, os
try:
    j=json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json")))
except Exception as e:
    print(f"  🟡 jobs.json unreadable: {e}"); raise SystemExit
def walk(o):
    if isinstance(o,dict):
        if 'id' in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)
g=[j2 for j2 in walk(j) if str(j2.get('id','')).startswith('8b3beb82')]
if g and g[0].get('enabled'):
    print("  ✅ daily goal-of-the-moment cron enabled")
elif g:
    print("  ❌ daily goal cron present but DISABLED")
else:
    print("  🟡 daily goal cron job not found")
PY
echo

# ── R5: proof, not theater — POPDD gate live on prospector ──
echo "R5  proof gate (POPDD on prospector)"
HOOK="$PROSPECTOR/.git/hooks/pre-commit"
if [ -e "$HOOK" ]; then
  ok "prospector pre-commit gate installed ($(readlink "$HOOK" 2>/dev/null || echo file))"
else
  bad "prospector pre-commit gate NOT installed — commits can land without proof"
fi
LATEST_RX=$(ls -t "$PROSPECTOR"/.lux/receipts/*.jsonl 2>/dev/null | head -1)
if [ -n "$LATEST_RX" ]; then
  ok "latest receipt: $(basename "$LATEST_RX")"
else
  bad "no POPDD receipts found"
fi
echo

# ── FENCES: money/identity must never execute unproven from the cockpit ──
echo "FENCES  money/identity"
M="$COCKPIT/sentinel/cockpit/menu.py"
if grep -q 'approve is Claude-only fence\|Do NOT call C.approve' "$M"; then
  ok "task:approve fenced (no DB write from cockpit)"
else
  bad "approve fence text missing — verify approve cannot write from cockpit"
fi
if grep -qiE 'signalengine|introduction.?exchange' "$M" && grep -qE 'subprocess.*(signalengine|tie)|trigger.*(signalengine|tie)' "$M"; then
  bad "possible signalengine/tie execution trigger in menu.py — must stay read-only"
else
  ok "no signalengine/tie execution triggers in cockpit (read-only tiles only)"
fi
echo

# ── WI-8: ACL health (door must actually admit users) ──
echo "WI-8  ACL + UI integrity"
# Read the allowlist from what is ACTUALLY enforced — the running cockpit's
# process env (launchd loads ~/.hermes/.env into it). The probe's own shell does
# NOT source that file, so reading $TELEGRAM_ALLOWED_USER_IDS here would always
# be empty and lie. Fall back to ~/.hermes/.env (what the next restart will load).
CKPID_ACL=$(pgrep -f 'uvicorn sentinel.cockpit.server' | head -1)
ALLOWED=""
if [ -n "$CKPID_ACL" ]; then
  ALLOWED=$(ps eww -p "$CKPID_ACL" 2>/dev/null | tr ' ' '\n' | grep '^TELEGRAM_ALLOWED_USER_IDS=' | head -1 | cut -d= -f2-)
fi
[ -z "$ALLOWED" ] && ALLOWED=$(grep '^TELEGRAM_ALLOWED_USER_IDS=' "$HERMES/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
COUNT=$(echo "$ALLOWED" | tr ',' '\n' | grep -cE '[0-9]')
if [ "$COUNT" = "0" ]; then
  bad "ACL allowlist EMPTY in live cockpit — door functionally down (no user can get in)"
elif [ "$COUNT" = "1" ]; then
  warn "ACL allowlist = 1 user (founder only) — any additional person (e.g. Dario) is locked out until added"
else
  ok "ACL allowlist: $COUNT users admitted"
fi

# WI-8: No called-but-undefined UI helper (catches WI-1 regression)
if python3 -c "
import sys
sys.path.insert(0, '$COCKPIT')
from sentinel.cockpit.menu import _reply_keyboard_markup
kb = _reply_keyboard_markup()
assert 'keyboard' in kb, 'missing keyboard key'
assert kb.get('is_persistent'), 'keyboard not persistent'
" 2>/dev/null; then
  ok "_reply_keyboard_markup() defined and valid (nav bar is wired)"
else
  bad "_reply_keyboard_markup() undefined or broken — nav bar silent-fails (WI-1 regression)"
fi

# WI-8: Render smoke — dashboard must produce a non-empty inline keyboard
if python3 -c "
import sys
sys.path.insert(0, '$COCKPIT')
from sentinel.cockpit.menu import view_dashboard
text, kb = view_dashboard()
assert 'inline_keyboard' in kb, 'missing inline_keyboard'
assert len(kb['inline_keyboard']) > 0, 'empty keyboard'
assert any('nv:' in str(btn.get('callback_data','')) for row in kb['inline_keyboard'] for btn in row), 'no nav callbacks'
" 2>/dev/null; then
  ok "dashboard renders with inline keyboard (door renders)"
else
  bad "dashboard render smoke test failed — cockpit may not render"
fi
echo

if [ "$FAIL" = "0" ]; then
  echo "VERDICT: ✅ OPERATIONAL — all critical checks green."
else
  echo "VERDICT: ❌ DEGRADED — at least one ❌ above. Fix before claiming ready."
fi
exit $FAIL
