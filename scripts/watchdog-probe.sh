#!/bin/bash
# watchdog-probe — receipt for exit-code grading (hidden-restart-loop fix).
# Proves watchdog.py grades on real invariants instead of exiting 0 unconditionally:
#   A healthy + daemon sustained-alive            -> exit 0
#   B daemon down (restart loop / flapping)       -> exit 2  + relay event
#   C alert open >= K runs (unhealed SLA breach)  -> exit 1
#   D alert absent K runs                          -> resolved (dropped from open set)
# Each scenario runs in its own isolated HERMES_HOME.
set -u
SC="$HOME/.hermes/scripts"
WD="$SC/watchdog.py"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

# fresh_env <last_status> -> echoes a tmp HERMES_HOME with a 1-job cron file
fresh_env() {
  local st="$1" t; t=$(mktemp -d)
  mkdir -p "$t/cron" "$t/logs/alerts"
  ln -s "$SC" "$t/scripts"   # so watchdog finds hermes_queue.py / alert-resolver.py
  git -C "$t" init -q        # real repo so check_git_health is clean (no GIT_ERROR noise)
  cat > "$t/cron/jobs.json" <<JSON
{"jobs":[{"id":"x","name":"demo-job","enabled":true,"state":"scheduled",
  "last_status":"$st","last_run_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","last_error":"boom"}]}
JSON
  echo "$t"
}
open_fps() { python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['fingerprints']))" "$1/logs/alerts/watchdog-state.json" 2>/dev/null || echo -1; }

export HERMES_WD_RESOLVE_K=2 HERMES_WD_SUSTAIN_N=2 HERMES_WD_BREACH_K=2

# ── A: healthy + daemon up -> exit 0 ─────────────────────────────────────────
A=$(fresh_env ok)
HERMES_HOME="$A" HERMES_FAKE_GATEWAY=up python3 "$WD" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "healthy + daemon up -> exit 0" || bad "healthy expected exit 0, got $rc"

# ── B: daemon down -> exit 2 (restart loop) + relay event ────────────────────
B=$(fresh_env ok)
HERMES_HOME="$B" HERMES_FAKE_GATEWAY=down python3 "$WD" >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && ok "daemon down -> exit 2 (restart loop detected)" || bad "restart loop expected exit 2, got $rc"
HERMES_HOME="$B" python3 "$SC/hermes_queue.py" drain >/dev/null 2>&1
NLOOP=$(HERMES_HOME="$B" python3 "$SC/hermes_queue.py" status 2>/dev/null | python3 -c \
  'import json,sys;d=json.load(sys.stdin);print(sum(1 for i in d["items"] if "RESTART_LOOP" in (i.get("source","")+i.get("fingerprint",""))) or sum(1 for i in d["items"]))' 2>/dev/null || echo 0)
[ "${NLOOP:-0}" -ge 1 ] && ok "restart loop escalated to relay queue" || bad "no restart-loop event reached the queue"

# ── C: alert open >= K runs -> exit 1 ────────────────────────────────────────
# Use DISK_HIGH (threshold 0%, always fires) — a condition the self-healer cannot
# erase, so it genuinely persists K runs and exercises the open-breach invariant.
C=$(fresh_env ok)
HERMES_HOME="$C" HERMES_FAKE_GATEWAY=up HERMES_DISK_PCT_MAX=0 python3 "$WD" >/dev/null 2>&1; rc1=$?
HERMES_HOME="$C" HERMES_FAKE_GATEWAY=up HERMES_DISK_PCT_MAX=0 python3 "$WD" >/dev/null 2>&1; rc2=$?
{ [ "$rc1" = 0 ] && [ "$rc2" = 1 ]; } \
  && ok "alert open 1 run -> exit 0 (tracking); open K=2 runs -> exit 1 (breach)" \
  || bad "open-breach grading wrong: run1=$rc1 (want 0) run2=$rc2 (want 1)"

# ── D: alert absent K runs -> resolved (dropped from open set) ────────────────
D=$(fresh_env error)
HERMES_HOME="$D" HERMES_FAKE_GATEWAY=up python3 "$WD" >/dev/null 2>&1   # open
O1=$(open_fps "$D")
# clear the condition: job now ok
sed -i '' 's/"last_status":"error"/"last_status":"ok"/' "$D/cron/jobs.json"
HERMES_HOME="$D" HERMES_FAKE_GATEWAY=up python3 "$WD" >/dev/null 2>&1   # absent 1
HERMES_HOME="$D" HERMES_FAKE_GATEWAY=up python3 "$WD" >/dev/null 2>&1   # absent 2 -> resolved
O2=$(open_fps "$D")
{ [ "$O1" -ge 1 ] && [ "$O2" -eq 0 ]; } \
  && ok "alert resolved after absent K=2 runs (open fps $O1 -> $O2)" \
  || bad "resolution-after-K-absent wrong: open before=$O1 after=$O2"

rm -rf "$A" "$B" "$C" "$D"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — watchdog grades daemon liveness + alert SLA on real invariants."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
