#!/bin/bash
# proving-ground-probe — receipt for the existence-aware audit (Ball 19).
# Asserts the audit never false-passes on missing paths: with required paths absent
# it must exit 1, report them as MISSING, and never grade a missing path as "pass".
set -u
SC="$HOME/.hermes/scripts"; fail=0
ok(){ printf 'OK   %s\n' "$*"; }; bad(){ printf 'FAIL %s\n' "$*"; fail=1; }
EMPTY=$(mktemp -d)   # CODE dir with none of the required projects

OUT=$(HERMES_CODE_DIR="$EMPTY" python3 "$SC/proving-ground.py" 2>&1); rc=$?
[ "$rc" = 1 ] && ok "missing required paths -> exit 1 (no false-pass)" || bad "expected exit 1, got $rc"
echo "$OUT" | grep -q "VERDICT: FAIL" && ok "verdict FAIL on missing required" || bad "verdict not FAIL"
echo "$OUT" | grep -q "MISSING" && ok "missing paths reported as MISSING" || bad "MISSING not reported"

# Invariant C: no result is both missing and graded pass.
BAD=$(python3 - "$EMPTY" <<'PY'
import json,sys,os,datetime
r=os.path.expanduser(f"~/.lux/proving-ground/{datetime.date.today().isoformat()}.jsonl")
bad=0
for line in open(r):
    o=json.loads(line)
    if o.get("state")=="missing" and o.get("required") and o.get("state")=="pass": bad+=1
    # also: a missing entry must never carry state 'pass'
    if o.get("path") and not os.path.exists(o["path"]) and o.get("state")=="pass": bad+=1
print(bad)
PY
)
[ "${BAD:-1}" = 0 ] && ok "no missing path is graded pass (no silent false-pass)" || bad "found $BAD false-pass entries"

rm -rf "$EMPTY"
echo "---"
[ "$fail" = 0 ] && { echo "PROBE: PASS — audit is existence-aware; missing != pass."; exit 0; } || { echo "PROBE: FAIL"; exit 1; }
