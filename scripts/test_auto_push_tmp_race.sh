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
# gap=0 is the pathological continuous writer; gap>0 models the real scheduler, which
# rewrites jobs.json a few times per tick (last_run_at, status) and is idle in between.
gap = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
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
    if gap:
        time.sleep(gap)
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
  local dir="$1" add_cmd="$2" secs="${3:-6}" gap="${4:-0}"
  local deadline; deadline=$(python3 -c "import time,sys; print(time.time()+float(sys.argv[1]))" "$secs")
  python3 "$WORK/writer.py" "$dir/cron" "$dir/cron/jobs.json" "$deadline" "$gap" >/dev/null 2>&1 &
  local wpid=$!
  local fatals=0 attempts=0
  while kill -0 "$wpid" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [ "$add_cmd" = plain ]; then
      out=$(git -C "$dir" add -A 2>&1) || {
        printf '%s' "$out" | grep -q "unable to stat" && fatals=$((fatals + 1))
      }
    else
      # The fix under test. Must mirror auto-push.sh EXACTLY, including the sleep — an
      # earlier version of this harness omitted it, reported a pass at 3 iterations, and
      # then failed 6/12 on a longer run. A retry harness that does not match the shipped
      # retry is measuring something nobody runs.
      local tries=0
      while :; do
        if out=$(git -C "$dir" add -A 2>&1); then break; fi
        tries=$((tries + 1))
        if [ "$tries" -lt 3 ] && printf '%s' "$out" | grep -q "unable to stat"; then
          sleep 1
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

# Scenario 3 is the BACKSTOP, not the fix. It covers a future atomic-writer whose temp
# name no glob in .gitignore matches. The writer here is bursty (gap 1.5s) because that is
# what the scheduler actually does — a few writes per tick, idle in between.
echo "=== 3. FIX B (backstop): no ignore, bounded retry, realistic bursty writer ==="
make_repo "$WORK/rty" ""
read -r f3 a3 <<<"$(race "$WORK/rty" retry 14 1.5)"
echo "  git add -A attempts=$a3  fatal surfaced after retry=$f3"
if [ "$f3" -eq 0 ] && [ "$a3" -gt 0 ]; then
  ok "retry absorbed the bursty race ($a3 runs, 0 surfaced)"
else
  bad "retry did not absorb the bursty race: $f3/$a3"
fi

# Documents a real LIMIT rather than asserting a win. Measured 6/12 surfaced fatals: three
# bounded tries cannot outrun a writer that never stops, so the retry is explicitly NOT a
# substitute for Fix A — it only buys a margin for names Fix A does not know about. This
# case is reported, not failed, because no such writer exists in this tree today.
echo "=== 4. KNOWN LIMIT: retry alone vs a pathological continuous writer ==="
make_repo "$WORK/cont" ""
read -r f4 a4 <<<"$(race "$WORK/cont" retry 10 0)"
echo "  git add -A attempts=$a4  fatal surfaced after retry=$f4"
if [ "$f4" -gt 0 ]; then
  echo "  NOTE  retry alone is insufficient here ($f4/$a4) — this is why cron/.jobs_*.tmp"
  echo "        is ignored by name in .gitignore. Documented limit, not a regression."
else
  echo "  NOTE  no fatals this run ($a4 attempts); the limit is load-dependent."
fi

echo
echo "passed=$PASS failed=$FAIL  (scenario 4 is informational)"
[ "$FAIL" -eq 0 ]
