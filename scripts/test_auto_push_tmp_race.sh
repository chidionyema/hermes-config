#!/bin/bash
# Repro + regression test for the 2026-08-14 21:01 auto-push failure:
#
#   git add -A failed: fatal: unable to stat 'cron/.jobs_119c4ssq.tmp': No such file or directory
#
# Mechanism: hermes-agent/cron/jobs.py:557 writes jobs.json via
# mkstemp(dir=cron/, prefix='.jobs_', suffix='.tmp') -> fsync -> atomic_replace(:563).
# The temp file exists for the few ms between mkstemp and rename. `git add -A` enumerates
# the directory and then stats each entry to stage it; when the rename lands in between,
# git aborts the ENTIRE sync with a fatal. The scheduler writes jobs.json to record
# last_run_at for the very job running auto-push.sh, so the overlap is structural, not bad luck.
#
# Three scenarios, each in a throwaway repo (never touches ~/.hermes):
#   1. baseline  — no ignore, no retry  -> the fatal MUST reproduce (else the test proves nothing)
#   2. gitignore — temp names ignored   -> zero fatals under the same load
#   3. retry     — no ignore, bounded retry on "unable to stat" -> recovers
#
# Exit 0 = all three behaved as specified.

set -uo pipefail

PASS=0
FAIL=0
ok()   { printf '  PASS  %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  FAIL  %s\n' "$*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Faithful reproduction of _save_jobs_unlocked (jobs.py:557-563): same prefix, same
# suffix, same directory, same fsync-then-replace ordering.
cat >"$WORK/writer.py" <<'PY'
import json, os, sys, tempfile, time
cron_dir, jobs_file, deadline = sys.argv[1], sys.argv[2], float(sys.argv[3])
payload = {"jobs": [{"id": "6c9522460ed5", "name": "hermes-config-auto-push"}] * 60}
n = 0
while time.time() < deadline:
    fd, tmp_path = tempfile.mkstemp(dir=cron_dir, suffix='.tmp', prefix='.jobs_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, jobs_file)
        n += 1
    except BaseException:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise
print(n)
PY

# Build a repo shaped like ~/.hermes: enough tracked files that `git add -A`'s directory
# traversal takes long enough to overlap a concurrent atomic write.
make_repo() {
  local dir="$1" ignore="$2"
  rm -rf "$dir"; mkdir -p "$dir/cron" "$dir/policies" "$dir/scripts" "$dir/reports"
  git -C "$dir" init -q -b main
  git -C "$dir" config user.email t@t; git -C "$dir" config user.name t
  for d in policies scripts reports; do
    for i in $(seq 1 120); do echo "content $i" >"$dir/$d/file_$i.json"; done
  done
  echo '{"jobs":[]}' >"$dir/cron/jobs.json"
  [ -n "$ignore" ] && printf '%s\n' "$ignore" >"$dir/.gitignore"
  git -C "$dir" add -A >/dev/null 2>&1
  git -C "$dir" commit -qm init >/dev/null 2>&1
}

# Runs `git add -A` in a loop against a live atomic-writer. Echoes "<fatals> <attempts>".
# add_cmd: "plain" (bare git add -A) or "retry" (bounded retry on a transient stat race).
race() {
  local dir="$1" add_cmd="$2" secs="${3:-6}"
  local deadline; deadline=$(python3 -c "import time,sys; print(time.time()+float(sys.argv[1]))" "$secs")
  python3 "$WORK/writer.py" "$dir/cron" "$dir/cron/jobs.json" "$deadline" >/dev/null 2>&1 &
  local wpid=$!
  local fatals=0 attempts=0
  while kill -0 "$wpid" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [ "$add_cmd" = plain ]; then
      out=$(git -C "$dir" add -A 2>&1) || {
        printf '%s' "$out" | grep -q "unable to stat" && fatals=$((fatals + 1))
      }
    else
      # The fix under test, mirroring auto-push.sh.
      local tries=0
      while :; do
        if out=$(git -C "$dir" add -A 2>&1); then break; fi
        tries=$((tries + 1))
        if [ "$tries" -lt 3 ] && printf '%s' "$out" | grep -q "unable to stat"; then
          continue
        fi
        printf '%s' "$out" | grep -q "unable to stat" && fatals=$((fatals + 1))
        break
      done
    fi
    git -C "$dir" reset -q >/dev/null 2>&1
  done
  wait "$wpid" 2>/dev/null
  echo "$fatals $attempts"
}

echo "=== 1. BASELINE: no ignore, no retry — the fatal must reproduce ==="
make_repo "$WORK/base" ""
read -r f1 a1 <<<"$(race "$WORK/base" plain 8)"
echo "  git add -A attempts=$a1  fatal 'unable to stat'=$f1"
if [ "$f1" -gt 0 ]; then
  ok "reproduced the production failure ($f1/$a1 runs died)"
else
  bad "did NOT reproduce — this test cannot validate the fix"
fi

echo "=== 2. FIX A: cron/.jobs_*.tmp ignored — same load, expect zero fatals ==="
make_repo "$WORK/ign" 'cron/.jobs_*.tmp
cron/.sugg_*.tmp'
read -r f2 a2 <<<"$(race "$WORK/ign" plain 8)"
echo "  git add -A attempts=$a2  fatal 'unable to stat'=$f2"
if [ "$f2" -eq 0 ] && [ "$a2" -gt 0 ]; then
  ok "gitignore closed the race ($a2 runs, 0 fatal)"
else
  bad "still failing with gitignore: $f2/$a2"
fi

echo "=== 3. FIX B: no ignore, bounded retry — expect zero surfaced fatals ==="
make_repo "$WORK/rty" ""
read -r f3 a3 <<<"$(race "$WORK/rty" retry 8)"
echo "  git add -A attempts=$a3  fatal surfaced after retry=$f3"
if [ "$f3" -eq 0 ] && [ "$a3" -gt 0 ]; then
  ok "retry absorbed the transient race ($a3 runs, 0 surfaced)"
else
  bad "retry did not absorb the race: $f3/$a3"
fi

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
