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
# The section above is headed "staleness" but only proves a pid is alive and a tree is committed.
# Neither says the running process contains that code. This does: it compares each daemon's start
# time to the last change of the hermes-agent tree it hosts. Added 2026-08-17, when the coordinator
# was found 25h behind cron/scheduler.py and three fixes to it had never run.
if [ -f "$HERMES/scripts/check-daemon-staleness.py" ]; then
  STALE_OUT=$(python3 "$HERMES/scripts/check-daemon-staleness.py" 2>&1); STALE_RC=$?
  echo "$STALE_OUT"
  [ "$STALE_RC" = "1" ] && bad "a daemon is running code older than the tree (restart lines above)"
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

# ── EXECUTOR: Otto can ACT, not merely run ──
#
# Added 2026-08-06. The coordinator daemon ran continuously from 2026-08-04 17:49 while its
# tool-capable executor was 100% dead, and NOTHING in this file noticed — R4 above asks only
# whether the process is up and its tick is fresh, and both stayed green the whole time. The
# installed plist had drifted to invoke coordinator.py directly, bypassing coordinator-daemon.sh,
# which dropped COORD_AGENTIC_EXEC=1 (the gate in agentic_execute) AND the wrapper's PATH — so
# ~/.local/bin/claude was unreachable under launchd's bare PATH and every executor spawn raised
# FileNotFoundError, falling through to the chat-narration tier. MEASURED on coordinator.db:
# every task closed between 2026-08-02 and 2026-08-06 18:55 carried a fallback marker. Four days
# of "done" rows, zero real work, no probe red.
#
# PRESENCE IS NOT CAPABILITY. These four ask the live system whether it can act:
#   1. is the gate armed in the RUNNING process (ps eww is the fact; a plist on disk is a claim)
#   2. does the daemon's OWN PATH resolve the tool CLI, and does that CLI answer
#   3. could a reinstall from the repo plist copy silently disarm it again
#   4. has any real (non-fallback) work actually closed lately
# Read-only throughout: `claude --version` is a local version print (MEASURED <1s), the DB is
# opened mode=ro, and nothing here starts, stops or writes to anything.
echo "EXECUTOR  Otto can ACT (agentic tier)"
python3 - <<'PY'
import ast, os, re, shutil, sqlite3, subprocess, time

H = os.path.expanduser("~/.hermes")
def ok(m):   print(f"  ✅ {m}")
def warn(m): print(f"  🟡 {m}")
def bad(m):
    print(f"  ❌ {m}")
    open(os.path.join(H, ".verify_estate_fail"), "w").write("executor")

# 1) The gate, in the RUNNING process.
pid, env = "", {}
try:
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/ai.hermes.coordinator"],
                       capture_output=True, text=True, timeout=8)
    m = re.search(r"pid = (\d+)", r.stdout)
    pid = m.group(1) if m else ""
except Exception as e:
    warn(f"launchctl unreadable: {e}")
if pid:
    try:
        pe = subprocess.run(["ps", "eww", pid], capture_output=True, text=True, timeout=8)
        for tok in pe.stdout.split():
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
                k, _, v = tok.partition("=")
                env[k] = v
    except Exception as e:
        warn(f"could not read pid {pid} environment: {e}")

if not pid:
    bad("coordinator not running — executor capability cannot be asserted")
elif env.get("COORD_AGENTIC_EXEC") == "1":
    ok(f"agentic executor ARMED in live pid {pid} (COORD_AGENTIC_EXEC=1)")
else:
    bad(f"pid {pid} is running WITHOUT COORD_AGENTIC_EXEC=1 — executor is chat-only (plist drift)")

# 2) The tool CLI, resolved on the DAEMON's PATH — not on the PATH of whoever runs this probe.
dpath = env.get("PATH", "")
if pid and not dpath:
    warn("could not read the daemon's PATH from ps eww — CLI reachability unproven")
elif dpath:
    cli = shutil.which("claude", path=dpath)
    if not cli:
        bad(f"`claude` NOT on the daemon's own PATH ({dpath}) — every executor spawn raises FileNotFoundError")
    else:
        try:
            v = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=25,
                               env={**os.environ, "PATH": dpath})
            if v.returncode == 0:
                ok(f"tool CLI live from the daemon's PATH: {(v.stdout or '').strip()[:60]}")
            else:
                bad(f"`claude --version` rc={v.returncode} under the daemon's env: "
                    f"{((v.stderr or v.stdout) or '').strip()[:100]}")
        except Exception as e:
            bad(f"tool CLI did not answer under the daemon's env: {type(e).__name__}: {str(e)[:80]}")

# 3) Both plists must arm the executor: the installed one governs now, the repo one governs the
#    next reinstall. Byte drift between them is fine (timeouts get tuned); losing either of these
#    two strings is the exact regression that caused the outage.
for label, p in (("installed", os.path.expanduser("~/Library/LaunchAgents/ai.hermes.coordinator.plist")),
                 ("repo", os.path.join(H, "ai.hermes.coordinator.plist"))):
    try:
        t = open(p).read()
    except Exception as e:
        bad(f"{label} coordinator plist unreadable ({p}): {e}")
        continue
    missing = [s for s in ("coordinator-daemon.sh", "COORD_AGENTIC_EXEC") if s not in t]
    if missing:
        bad(f"{label} plist would disarm the executor — missing {', '.join(missing)}")
    else:
        ok(f"{label} plist arms the executor (wrapper + COORD_AGENTIC_EXEC)")

# 4) Outcome. The markers are READ from coordinator.py, never re-typed here: the original Layer 0
#    bug was a gate testing a fourth spelling that nothing emitted, and a probe with its own
#    private copy of the strings would reintroduce exactly that.
#    Parsed with ast, NOT a regex: `FALLBACK_MARKERS\s*=\s*\((.*?)\)` matched up to the first
#    ')' — which lives inside a marker's trailing comment — and silently skipped this check.
markers = []
try:
    src = open(os.path.join(H, "scripts", "coordinator.py")).read()
    for node in ast.parse(src).body:                     # parse, never import: no side effects
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "FALLBACK_MARKERS" for t in node.targets):
            markers = list(ast.literal_eval(node.value))
    if not markers:
        warn("FALLBACK_MARKERS not found in coordinator.py — outcome check skipped")
except Exception as e:
    warn(f"could not read FALLBACK_MARKERS from coordinator.py ({e}) — outcome check skipped")

if markers:
    conn = None
    try:
        conn = sqlite3.connect(f"file:{os.path.join(H, 'coordinator.db')}?mode=ro", uri=True)
        where = " AND ".join(["COALESCE(result,'') NOT LIKE ?"] * len(markers))
        last = conn.execute(
            f"SELECT MAX(completed_at) FROM tasks WHERE status='done' AND {where}",
            [f"%{m}%" for m in markers]).fetchone()[0]
        recent = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done' AND completed_at > ?",
            (time.time() - 48 * 3600,)).fetchone()[0]
    except Exception as e:
        warn(f"outcome check not evaluated: {e}")
        last, recent = 0, 0
    finally:
        if conn is not None:
            conn.close()   # `with sqlite3.connect(...)` commits but does NOT close the handle
    # Severity ladder, set by the counterfactual rather than by taste. At 2026-08-06 18:00 the
    # last non-fallback close was 2026-07-31 06:28 — 6.5 DAYS — and exactly 0 tasks had closed in
    # the preceding 48h. A rule that only reddens when closes are happening would have sat at 🟡
    # through the whole outage, so silence past STALE_H is red on its own: with 243 failed tasks
    # queued and a tick every few minutes, six days without one tool-capable close is a stall,
    # not idleness.
    STALE_H = 96
    if last:
        hrs = (time.time() - float(last)) / 3600.0
        if hrs <= 48:
            ok(f"real (non-fallback) work last closed {hrs:.1f}h ago")
        elif recent:
            bad(f"{recent} task(s) closed in 48h but NONE did real work — last non-fallback close "
                f"{hrs/24:.1f}d ago (fabricated-progress signature)")
        elif hrs > STALE_H:
            bad(f"no real work in {hrs/24:.1f}d and nothing closing — executor stalled")
        else:
            warn(f"no closes at all in 48h; last real work {hrs/24:.1f}d ago — idle or stalled")
    elif last is not None:
        warn("no non-fallback close on record at all")
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

# ── SIGNAL_ENGINE: the money daemon is alive AND supervised ──
#
# Added 2026-07-31. Before this, R1 only checked that "signalengine" appeared in
# projects.json — a portfolio membership test that stayed green through a 37-day
# outage (daemon dead since 2026-06-24 15:58 while its watchdog reported ok 2,732
# times). Membership is not liveness. This asks the live system three questions:
# is a process running, is its heartbeat fresh, and will anything restart it.
#
# "running but unsupervised" is a FAIL, not a warning: a hand-started daemon dies
# at the next reboot with nobody watching, which is the exact shape of the outage
# this check exists to make impossible.
echo "SIGNAL_ENGINE  money daemon liveness"
python3 - <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))
fail = os.path.expanduser("~/.hermes/.verify_estate_fail")
try:
    # Same verdict function the phone panel renders, so the probe and the panel can
    # never disagree about what "healthy" means.
    from gateway.operator_shell.signal_engine import health, is_armed
except Exception as exc:
    print(f"  🟡 signal_engine panel not importable: {str(exc)[:70]}")
    raise SystemExit
try:
    h = health()
    rail = "ARMED" if is_armed() else "paper"
except Exception as exc:
    print(f"  ❌ signal_engine health check itself failed: {type(exc).__name__}: {str(exc)[:60]}")
    open(fail, "w").write("signal_engine")
    raise SystemExit
v = str(h.get("verdict"))
hb = h.get("heartbeat_s")
hb_txt = "never" if hb is None else f"{hb}s ago"
eq = h.get("equity")
eq_txt = f"${float(eq):,.2f}" if isinstance(eq, (int, float)) else "?"
detail = f"pid {h.get('pid') or 'none'} · heartbeat {hb_txt} · equity {eq_txt} · rail {rail}"
if v == "ok":
    print(f"  ✅ com.signalengine.daemon healthy (launchd-supervised) · {detail}")
elif v == "unsupervised":
    print(f"  ❌ daemon RUNNING BUT UNSUPERVISED — launchd does not own it · {detail}")
    print("     nothing restarts it; it dies at reboot. Load com.signalengine.daemon.")
    open(fail, "w").write("signal_engine")
elif v == "tcc_denied":
    print(f"  ❌ launchd cannot start it: EX_CONFIG(78), interpreter denied Full Disk Access · {detail}")
    print("     one-time founder fix: System Settings > Privacy & Security > Full Disk Access")
    open(fail, "w").write("signal_engine")
elif v == "stalled":
    print(f"  ❌ process alive but heartbeat STALE (wedged) · {detail}")
    open(fail, "w").write("signal_engine")
else:
    print(f"  ❌ daemon {v.upper()} · {detail}")
    open(fail, "w").write("signal_engine")
PY
[ -f "$HERMES/.verify_estate_fail" ] && FAIL=1 && rm -f "$HERMES/.verify_estate_fail"
# The probe cron job must itself be the verifying kind — a watchdog that launches
# orphans is how the outage was hidden. Assert it never spawns the daemon.
if grep -q 'nohup .*signal_engine.daemon' "$HERMES/scripts/signal-engine-daemon-watchdog.sh" 2>/dev/null; then
  bad "signal-engine watchdog still LAUNCHES the daemon (orphan spawn) — must be probe-only"
else
  ok "signal-engine cron job is probe-only (does not spawn orphans)"
fi
echo

# ── LAUNCHD: no estate-owned unit is quietly failing ──
#
# Added 2026-07-31 after the audit that followed the signalengine outage found two
# more silent failures nobody was watching: com.tie.ai-review had exited 78 on every
# run since 2026-06-12 (its script had been renamed review/orchestrator.py ->
# consensus/engine.py and the plist never followed), and both com.haworks.* jobs had
# exited 1 on every run since the claude-sonnet-4 retirement on 2026-06-15.
#
# Neither was hidden by anything clever. Nothing looked. A nonzero last-exit is
# already sitting in `launchctl list`; this just reads it out loud.
#
# Negative codes are signals (-15 SIGTERM on restart, -9 on a deliberate kill), not
# faults. Third-party vendor agents warn rather than fail: they are not ours to fix,
# and a permanent red would train the eye to ignore this whole section.
#
# 2026-08-06: that last sentence had come true on our own gateway. `launchctl list`
# keeps the exit code of the LAST run forever; it does not claim the unit is failing
# NOW. ai.hermes.gateway exits 1 by design on an unexpected SIGTERM (gateway/run.py
# :17201-17206) precisely so KeepAlive revives it — so one external SIGTERM stamps a
# permanent `last exit=1`, and this section then printed "job is failing every run"
# about a process that had been serving continuously for 46 minutes. A red that is
# false while the unit is healthy is the CREDITS_ERROR failure again: it trains the
# eye to skip the section, which is where a real red then dies.
#
# The discriminator is uptime of the CURRENT instance, which a crash-loop cannot
# accumulate: launchd throttles respawns to ~10s, so a looping unit is observed with
# either no pid or a seconds-old one. Held longer than the settle window => the
# nonzero code is history. Known blind spot, stated rather than hidden: a unit that
# dies on a cycle LONGER than the window reads green here; slow degradation is the
# reliability watchdog's job (scripts/reliability_report.py), not this line's.
LAUNCHD_SETTLED_S=300

# macOS ps has no `etimes` (seconds); only `etime` as [[dd-]hh:]mm:ss. Same family as
# the missing flock(1) — the portable-looking spelling fails here, and it fails LOOKING
# like "process not found", i.e. it would have reported every healthy unit as red.
_pid_uptime_s() {
  case "$1" in ''|*[!0-9]*) return 0 ;; esac
  ps -o etime= -p "$1" 2>/dev/null | awk '
    NF {
      d = 0; t = $1
      if (split($1, a, "-") == 2) { d = a[1]; t = a[2] }
      n = split(t, b, ":")
      s = (n == 3) ? b[1]*3600 + b[2]*60 + b[3] : b[1]*60 + b[2]
      print d*86400 + s
    }'
}

# Is this job PERIODIC (calendar/interval) rather than a daemon? A daemon that is not
# running is broken; a 04:30 job that is not running at 21:00 is doing exactly what it was
# configured to do. The section below could not tell them apart, so it printed "job is
# failing every run" — a claim about EVERY run, drawn from one job that had run once.
# Measured 2026-08-08: ai.hermes.rsi was the estate's only ❌ on that sentence.
_launchd_plist() {
  p="$HOME/Library/LaunchAgents/$1.plist"
  [ -f "$p" ] && { printf '%s\n' "$p"; return 0; }
  # Not in the usual place: ask launchctl where it loaded it from rather than guess.
  launchctl print "gui/$(id -u)/$1" 2>/dev/null | awk -F' = ' '/^[[:space:]]*path = /{print $2; exit}'
}
_is_periodic() {
  p="$(_launchd_plist "$1")"
  [ -n "$p" ] && [ -f "$p" ] && grep -qE 'StartCalendarInterval|StartInterval' "$p"
}

echo "LAUNCHD  scheduled jobs"
launchctl list 2>/dev/null | awk 'NR>1 && $2 != "0" && $2 != "-" && $2 !~ /^-/ {print $3, $2, $1}' \
| while read -r label code pid; do
    case "$label" in
      com.apple.*) continue ;;
      com.estate.costsentinel)
        # Estate-owned, but its exit code is a SIGNAL, not a status: 1 = warn
        # threshold crossed, 2 = halt cap breached, 0 = neither (see
        # ~/.claude/scripts/estate_cost_sentinel.py main()). It fell into the
        # "third-party, not estate-owned" arm below, so on 2026-08-06 the estate's
        # own spend rail reported exit=1 on a $1,091 day and the probe filed it
        # under somebody else's software. Routing it through the generic
        # estate-owned arm would be the opposite error: every over-cap day would
        # flip the whole estate verdict RED for a rail working exactly as designed.
        case "$code" in
          1) printf '  🟡 %s exit=1 — SPEND WARN threshold crossed (working as designed)\n' "$label" ;;
          2) printf '  ❌ %s exit=2 — SPEND HALT cap breached; PAUSE written\n' "$label"
             echo "$label" >> "$HERMES/.verify_estate_fail" ;;
          *) printf '  ❌ %s exit=%s — spend rail is erroring, spend is UNMEASURED\n' "$label" "$code"
             echo "$label" >> "$HERMES/.verify_estate_fail" ;;
        esac ;;
      ai.hermes.rsi)
        # Same shape as costsentinel above: the exit code is a DECISION, not a status.
        # ~/.hermes/scripts/rsi-autorun.sh classifies its own outcomes and deliberately
        # propagates the tuner's code instead of ending `exit 0` — because ending exit 0
        # unconditionally is how ~2 months of zero staged candidates stayed invisible. Its
        # own log for the 2026-08-08 04:30 run reads:
        #   prompt-tune(EXECUTE_PROMPT) exit=2 (2=ruler exhausted; 3=no authority; 124=timed out)
        # Filing those declines as a crash re-hides the same thing from the other side, and
        # costs the estate a permanent ❌ that the eye then learns to skip.
        case "$code" in
          0)   printf '  ✅ %s exit=0 — a prompt candidate was staged for approval\n' "$label" ;;
          1)   printf '  🟡 %s exit=1 — ran; no candidate beat the baseline (a decision, not a fault)\n' "$label" ;;
          2)   printf '  🟡 %s exit=2 — DECLINED: ruler exhausted, 0.00 non-gameable headroom, no LLM spend. Standing condition: needs graded/behavioural cases in build_rsi_evalset.py\n' "$label" ;;
          3)   printf '  🟡 %s exit=3 — DECLINED: prompt has no authority over recorded failures; tuning the ruler will not fix it\n' "$label" ;;
          124) printf '  ❌ %s exit=124 — prompt tune TIMED OUT; the model route is hung or slow\n' "$label"
               echo "$label" >> "$HERMES/.verify_estate_fail" ;;
          *)   printf '  ❌ %s exit=%s — an outcome rsi-autorun.sh does not classify\n' "$label" "$code"
               echo "$label" >> "$HERMES/.verify_estate_fail" ;;
        esac ;;
      ai.hermes.*|com.prospector.*|com.signalengine.*|com.tie.*|com.haworks.*)
        up="$(_pid_uptime_s "$pid")"
        if [ -n "$up" ] && [ "$up" -ge "$LAUNCHD_SETTLED_S" ]; then
          printf '  ✅ %s running %ss (pid %s) — last exit=%s is history, not a loop\n' \
            "$label" "$up" "$pid" "$code"
        elif [ -n "$up" ]; then
          printf '  ❌ %s last exit=%s and respawned %ss ago — flapping\n' "$label" "$code" "$up"
          echo "$label" >> "$HERMES/.verify_estate_fail"
        elif _is_periodic "$label"; then
          # Still a FAIL — the awk filter upstream only passes NONZERO codes, and a
          # scheduled run that exited nonzero failed. What changes is the claim: "not
          # running" is not evidence for a calendar job, and one datum cannot support
          # "every run". Say what was actually observed.
          printf '  ❌ %s last SCHEDULED run exited %s (periodic job; idle is expected, the exit code is not)\n' "$label" "$code"
          echo "$label" >> "$HERMES/.verify_estate_fail"
        else
          printf '  ❌ %s last exit=%s and not running — job is failing every run\n' "$label" "$code"
          echo "$label" >> "$HERMES/.verify_estate_fail"
        fi ;;
      *)
        printf '  🟡 %s last exit=%s (third-party, not estate-owned)\n' "$label" "$code" ;;
    esac
  done
# The `while read` above runs in a pipeline subshell, so a FAIL=1 set inside it
# would be discarded on exit. The marker file is how the verdict gets back out.
[ -f "$HERMES/.verify_estate_fail" ] && FAIL=1 && rm -f "$HERMES/.verify_estate_fail"
echo

# ── ALERTS: escalation still reaches the founder ──
#
# Added 2026-08-06. Every other check on this estate measures PRODUCTION — did a job
# make a file, did a capability emit a receipt. None measured DELIVERY, which is the
# link that actually failed: otto-dispatch sat disabled for 46 days while everything
# upstream kept producing perfectly, and 1,519 alerts went nowhere.
#
# This is deliberately a PULL check. An alarm about a broken alert channel cannot be
# delivered over the broken alert channel, so the proof has to be readable by a human
# running this script by hand, with no delivery involved. scripts/delivery_canary.py
# rides the real relay weekly and writes state/delivery_proof.json; this only reads
# its age and its verdict.
echo "ALERTS  escalation reaches you"
DELIVERY_PROOF="$HERMES/state/delivery_proof.json"
# Two canary periods plus a day of slack: one missed week is a late run, two is a
# relay that has stopped. Below that a single skipped Monday would cry wolf.
DELIVERY_MAX_AGE_S=$((15 * 86400))
if [ ! -f "$DELIVERY_PROOF" ]; then
  bad "no delivery proof at all — scripts/delivery_canary.py has never run"
else
  DP="$(python3 - "$DELIVERY_PROOF" "$DELIVERY_MAX_AGE_S" <<'PY' 2>/dev/null
import json, sys, time
try:
    rec = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"bad|delivery proof unreadable ({exc})"); raise SystemExit(0)
age = time.time() - float(rec.get("checked_at") or 0)
days = age / 86400.0
if age > float(sys.argv[2]):
    print(f"bad|delivery last checked {days:.1f}d ago — the canary itself has stopped running")
elif rec.get("verified"):
    print(f"ok|escalation delivery proven {days:.1f}d ago ({rec.get('detail','')})")
elif rec.get("reason") == "first-run":
    print(f"warn|delivery canary installed {days:.1f}d ago; first arrival confirms on its next run")
else:
    print(f"bad|escalation NOT reaching you [{rec.get('reason')}] — {rec.get('detail','')}")
for p in rec.get("peer_failures", []):
    print(f"bad|{p.get('job')} failed to deliver at {p.get('at')}: {p.get('error')}")
PY
)"
  if [ -z "$DP" ]; then
    bad "delivery proof could not be evaluated"
  else
    while IFS='|' read -r verdict msg; do
      [ -z "$verdict" ] && continue
      case "$verdict" in
        ok)   ok "$msg" ;;
        warn) warn "$msg" ;;
        *)    bad "$msg" ;;
      esac
    done <<EOF
$DP
EOF
  fi
fi
echo

# ── FENCES: money/identity never auto-execute ──
echo "FENCES  money/identity"
if grep -qE 'risk_class.*money|awaiting_approval|identity' "$HERMES/scripts/coordinator.py" 2>/dev/null; then
  ok "coordinator fence code present in coordinator.py"
else
  bad "money/identity fence not found in coordinator"
fi
# The grep above only proves the WORDS exist in the source. It stayed green through
# both live fence bypasses. This is the invariant that actually holds the line
# (PR-1, REMEDIATION_PLAN_2026-08-05.md:207): no money/identity/contract task may sit
# at status='done' without an 'approved' event. Backfilled to 0 on 2026-08-05; any
# non-zero from here is a real bypass, not history.
if [ -f "$HERMES/coordinator.db" ]; then
  FENCE_VIOL=$(sqlite3 "$HERMES/coordinator.db" "SELECT COUNT(*) FROM tasks t
      WHERE lower(COALESCE(t.risk_class,'')) IN ('money','identity','contract')
        AND t.status='done'
        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='approved');" 2>/dev/null)
  if [ "$FENCE_VIOL" = "0" ]; then
    ok "fence invariant: 0 money/identity/contract tasks done without approval"
  elif [ -z "$FENCE_VIOL" ]; then
    warn "fence invariant not evaluated (sqlite3 query failed on coordinator.db)"
  else
    bad "fence invariant BREACHED: $FENCE_VIOL money/identity/contract task(s) done with no approved event"
  fi
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
