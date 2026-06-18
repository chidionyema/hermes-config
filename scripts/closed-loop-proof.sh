#!/bin/bash
# closed-loop-proof — Item 9. Proves the WHOLE relay loop end-to-end in one isolated
# run, not piece by piece: inject a synthetic failure, show the watchdog catches it,
# show the relay queue RECEIVES the event, then clear the condition and show the loop
# RESOLVES it. A second chain proves dropped-ball telemetry: drop -> tracker -> queue.
#
#   Loop 1  daemon down  -> watchdog exit 2  -> queue gains an event
#   Loop 2  daemon up x K -> watchdog resolves the open alert (exit 0)
#   Loop 3  dropped ball  -> dropped-ball-tracker exit 2 -> queue gains aggregate
#
# Exit 0 only if every link in the chain fires. This is the artifact that answers
# "is the loop actually closed?" with an exit code instead of a story.
set -u
SC="$HOME/.hermes/scripts"
WD="$SC/watchdog.py"; Q="$SC/hermes_queue.py"; DBT="$SC/dropped-ball-tracker.py"
fail=0
ok(){  printf 'OK   %s\n' "$*"; }
bad(){ printf 'FAIL %s\n' "$*"; fail=1; }

fresh_env() {
  local st="$1" t; t=$(mktemp -d)
  mkdir -p "$t/cron" "$t/logs/alerts" "$t/queue"
  ln -s "$SC" "$t/scripts"
  git -C "$t" init -q
  cat > "$t/cron/jobs.json" <<JSON
{"jobs":[{"id":"x","name":"demo-job","enabled":true,"state":"scheduled",
  "last_status":"$st","last_run_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","last_error":"boom"}]}
JSON
  echo "$t"
}
# submissions land in queue/incoming/ and only fold into state.json on drain
queue_events() { python3 "$Q" drain >/dev/null 2>&1; \
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(len(d.get('fingerprints',{})))" \
  "$1/queue/state.json" 2>/dev/null || echo 0; }

export HERMES_WD_RESOLVE_K=2 HERMES_WD_SUSTAIN_N=2 HERMES_WD_BREACH_K=2

T=$(fresh_env ok)
export HERMES_HOME="$T"

# ── Loop 1: inject failure -> watchdog catches -> queue receives ─────────────
before=$(queue_events "$T")
HERMES_FAKE_GATEWAY=down python3 "$WD" >/dev/null 2>&1; rc=$?
after=$(queue_events "$T")
[ "$rc" = 2 ] && ok "fault injected -> watchdog caught it (exit 2)" \
              || bad "watchdog did not catch fault (exit $rc)"
[ "$after" -gt "$before" ] && ok "relay queue RECEIVED the event ($before -> $after)" \
                           || bad "queue did not receive event ($before -> $after)"

# ── Loop 2: clear condition -> loop resolves it ──────────────────────────────
for i in 1 2 3; do HERMES_FAKE_GATEWAY=up python3 "$WD" >/dev/null 2>&1; rc=$?; done
[ "$rc" = 0 ] && ok "condition cleared -> loop resolved (exit 0)" \
              || bad "loop failed to resolve after clear (exit $rc)"

# ── Loop 3: dropped ball -> tracker catches -> queue receives aggregate ──────
python3 "$Q" submit --source otto-dropped-ball --severity error \
  --message "synthetic drop" --fingerprint "dropped-ball-9-synthetic" >/dev/null 2>&1
python3 "$Q" drain >/dev/null 2>&1
HERMES_DB_WINDOW_MIN=60 python3 "$DBT" >/dev/null 2>&1; rc=$?
python3 "$Q" drain >/dev/null 2>&1   # fold the tracker's aggregate submit into state.json
agg=$(python3 -c "import json;d=json.load(open('$T/queue/state.json'));print(int(any(v.get('source')=='dropped-ball-tracker' for v in d['fingerprints'].values())))" 2>/dev/null)
[ "$rc" = 2 ] && ok "dropped ball -> tracker caught it (exit 2)" \
              || bad "tracker missed dropped ball (exit $rc)"
[ "$agg" = 1 ] && ok "relay queue RECEIVED dropped-ball aggregate" \
               || bad "queue missing dropped-ball aggregate"

rm -rf "$T"
[ "$fail" = 0 ] && echo "VERDICT: PASS — closed loop proven end to end" \
                || echo "VERDICT: FAIL — loop is broken"
exit $fail
