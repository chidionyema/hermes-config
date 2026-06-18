#!/bin/bash
# alert-resolver-probe — receipt for the Fire 4-LF false-clear fix.
# Proves resolution is PROBE-VERIFIED, not message-absence:
#   1. a still-active condition is NOT resolved (even as the message PID varies)
#   2. PID/timestamp-varying messages collapse to ONE fingerprint (anti-false-clear)
#   3. resolution happens ONLY after a re-probe confirms the condition cleared
# Runs in an isolated HERMES_HOME so it never touches the real alert log.
set -u
SC="$HOME/.hermes/scripts"
R="$SC/alert-resolver.py"
TMP=$(mktemp -d); export HERMES_HOME="$TMP"
mkdir -p "$TMP/cron" "$TMP/logs/alerts"
LOG="$TMP/logs/alerts/watchdog.jsonl"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

write_jobs() {  # $1 = last_status for the watched job
  cat > "$TMP/cron/jobs.json" <<JSON
{"jobs":[{"id":"x","name":"idle-continuous-learning","enabled":true,
  "last_status":"$1","last_run_at":"2026-06-18T20:00:00Z","last_error":"boom"}]}
JSON
}

count_resolved() { grep -c '"status": "resolved"' "$LOG" 2>/dev/null | head -1; }

# ── condition is ACTIVE: job errored ────────────────────────────────────────
write_jobs error
# two OPEN alerts for the SAME condition, differing only by PID + timestamp
printf '%s\n' '{"timestamp":"2026-06-18T19:24:00Z","type":"CRON_ERROR","message":"CRON_ERROR: idle-continuous-learning errored: code 1 PID 111","status":"open","healthy":false}' >> "$LOG"
printf '%s\n' '{"timestamp":"2026-06-18T19:39:00Z","type":"CRON_ERROR","message":"CRON_ERROR: idle-continuous-learning errored: code 1 PID 222","status":"open","healthy":false}' >> "$LOG"

python3 "$R" --check '[]' --verbose
N=$(count_resolved)
[ "$N" -eq 0 ] && ok "active condition NOT false-cleared (0 resolutions across PID-varying messages)" \
              || bad "FALSE-CLEAR: resolved $N alert(s) while job still errored"

# fingerprint collapse: the two open messages must be ONE open fingerprint
NFP=$(HERMES_HOME="$TMP" python3 - <<'PY'
import os,sys,json
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import importlib.util
spec=importlib.util.spec_from_file_location("ar", os.path.expanduser("~/.hermes/scripts/alert-resolver.py"))
ar=importlib.util.module_from_spec(spec); spec.loader.exec_module(ar)
print(len(ar.open_fingerprints(ar.read_alerts())))
PY
)
[ "${NFP:-9}" -eq 1 ] && ok "PID/timestamp variants collapsed to ONE open fingerprint" \
                      || bad "expected 1 open fingerprint, got $NFP"

# ── condition CLEARS: job now ok -> re-probe should resolve ──────────────────
write_jobs ok
python3 "$R" --check '[]' --verbose
N=$(count_resolved)
[ "$N" -ge 1 ] && ok "probe-verified clearing resolved the alert after condition cleared ($N)" \
              || bad "resolution did not fire after the condition genuinely cleared"

# ── offline invariant self-test ─────────────────────────────────────────────
python3 "$R" --self-test && ok "resolver self-test passed" || bad "resolver self-test failed"

rm -rf "$TMP"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — resolution is probe-verified; recurring alerts never false-clear."
  exit 0
else
  echo "PROBE: FAIL"
  exit 1
fi
