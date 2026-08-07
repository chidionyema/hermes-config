#!/bin/bash
# no-agent config auto-push — hourly sync of the hermes config repo to its private remote.
# Replaces the LLM-driven cron job that kept hitting Broken pipe errors.
#
# Two defects this script used to have, both fixed here (2026-07-31):
#
#   1. It could not fail. `set -e` was on, but every git call ended in `2>/dev/null || true`,
#      so a failed commit or push still exited 0 and still printed "Pushed N files".
#      `cron/jobs.json` recorded last_status "ok" for all 344 runs. Errors are now surfaced
#      and the exit code is honest — a push that did not happen means the off-machine copy
#      did not happen, which is the entire point of the job.
#
#   2. `git add -A` swept live SQLite databases. coordinator.db (29MB) landed in 75 commits
#      and coordinator.db-wal in 121 — most of the 47MB pack. Worse, a WAL-mode database
#      copied mid-write is a torn snapshot that may not restore, so the bloat did not even
#      buy a usable backup. Those files are untracked and ignored now; a consistent
#      sqlite3 .backup, gzipped to ~2MB, is versioned in their place.

set -euo pipefail
cd "$HOME/.hermes" || exit 1

# Durable diagnosis (added 2026-08-07). This job is registered deliver="local", and a
# local target resolves to NO delivery destination (cron/scheduler.py:570) — so on a
# failing run the composed "Script exited with code N / stderr: ..." text is built and
# then dropped on the floor. The capability audit still noticed the symptom
# ("config_auto_push DARK: 20/29 run(s) of auto-push.sh met [exit0]") but a verdict with
# no cause is one nobody can act on: this script failed 10 of its last 24 runs and the
# reason was unrecoverable after the fact. Everything below appends here instead.
LOG="$HOME/.hermes/logs/auto-push.log"
mkdir -p "$(dirname "$LOG")"
log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >>"$LOG" 2>/dev/null || true; }

# `set -e` turns ANY unguarded git failure into a bare exit 128 with no message — which is
# precisely what 6 of the last 24 runs recorded (git's fatal code, surfaced with no text).
# The ERR trap names the command that died, so the next 128 explains itself.
trap 'rc=$?; log "FAIL rc=$rc line=$LINENO cmd: $BASH_COMMAND"; echo "auto-push failed (rc=$rc) at line $LINENO: $BASH_COMMAND" >&2' ERR

log "--- run start (pid $$) ---"

problems=0
warn() {
  echo "WARN: $*" >&2
  log "WARN: $*"
  problems=1
}

# Network ops are bounded well inside the cron layer's 120s script cap
# (scheduler.py:855, _DEFAULT_SCRIPT_TIMEOUT). Before this, one slow remote consumed the
# whole budget and the run was killed as exit 124 having produced no output at all — 4 of
# the last 24 runs, including 07:02 today at 121s. A bounded op that reports "the remote
# was slow" is worth strictly more than a kill with no message.
NET_TIMEOUT="${AUTO_PUSH_NET_TIMEOUT:-40}"

# The hermes-agent submodule snapshot USED to run here, hourly. It has been moved to its
# own daily launchd job (ai.hermes.submodule-backup) because it cannot fit in this job's
# budget and never could:
#
#   backup-submodule.sh pushes a PARENTLESS commit (recovery/backup-submodule.sh:10) to a
#   shallow clone's private remote. Parentless is deliberate — a shallow clone has no
#   ancestors, so an ordinary push fails — but it also means git cannot negotiate a common
#   base with the remote, so EVERY run re-uploads the whole tree rather than a delta.
#   Measured 2026-08-07: still running at 75s under `bash -x`, stalled on exactly that
#   push, against this job's 120s total cap.
#
# So the hourly result was structurally guaranteed: the snapshot never completed, it ate
# the parent sync's budget, and (once the timeout was bounded at 40s) it set problems=1 on
# every single run — which is why config_auto_push reads "DARK: 20/31 met [exit0]" while
# the parent sync itself works fine. A backup that cannot finish inside its window is not
# a slow backup, it is an absent one, and it was masking the health of the job it rode on.

# Consistent, compressed snapshot of the coordinator DB. .backup takes SQLite's own
# read lock, so unlike a file copy it cannot capture a half-written page.
if command -v sqlite3 >/dev/null 2>&1 && [ -f coordinator.db ]; then
  mkdir -p backups
  if sqlite3 coordinator.db ".backup 'backups/coordinator.db.latest'"; then
    gzip -9f backups/coordinator.db.latest
  else
    warn "coordinator.db snapshot failed"
  fi
fi

# Self-heal a stale index.lock instead of paging (added 2026-08-07, root cause: a run at
# 13:17 was interrupted/killed and left a 0-byte lock with no owning git process; every
# `git add -A` since then hard-failed with "Unable to create index.lock: File exists" while
# `git status` kept succeeding, which is why the symptom looked add-specific). Only remove
# it if it's older than 5 minutes AND no live process holds it — a fresh lock or one a
# concurrent git invocation is actively using must be left alone.
LOCK_FILE=".git/index.lock"
if [ -f "$LOCK_FILE" ]; then
  lock_age=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$lock_age" -gt 300 ] && ! pgrep -x git >/dev/null 2>&1; then
    warn "removing stale index.lock (${lock_age}s old, no git process running)"
    rm -f "$LOCK_FILE"
  else
    echo "git lock present (${lock_age}s old) and a git process may hold it — skipping this run" >&2
    log "skip: index.lock present, age=${lock_age}s"
    exit 0
  fi
fi

# Both of these were unguarded. Under `set -e` a git failure here (an index.lock held by a
# concurrent process is the common one in this repo) exits 128 with an empty message and
# takes the whole sync down silently. Guarded, they say which call failed and why.
if ! CHANGES=$(timeout 30 git status --porcelain 2>&1); then
  echo "git status failed: $CHANGES" >&2
  log "git status failed: $CHANGES"
  exit 1
fi
if [ -z "$CHANGES" ]; then
  log "nothing to sync (clean tree); rc=$problems"
  exit $problems
fi

if ! add_out=$(git add -A 2>&1); then
  echo "git add -A failed: $add_out" >&2
  log "git add -A failed: $add_out"
  exit 1
fi

# Lane-guarded files have a single designated writer; unstaging them keeps the pre-commit
# hook from blocking this sync.
git restore --staged config.yaml plugins/otto-inbound/__init__.py scripts/coordinator.py \
  2>/dev/null || true

# Backstop against the next large binary someone drops in the tree. This repo is text and
# config; anything over 5MB is staged by accident and gets dropped with a warning rather
# than silently committed forever.
# Secret backstop. This is the control that matters: .gitignore patterns are
# name-based and this repo has now missed the same class of file three times —
# `*.env` never matched `.env.bak-20260805-222102`, and neither `*.bak-*` nor
# `*.bak.*` matched `config.yaml.corrupt.20260617-135424.bak`. The first pair was
# committed in 6ed5d40 and PUSHED with 26 live values (Anthropic/OpenAI/DeepSeek/
# Gemini/Exa/MiniMax keys, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET,
# RSI_SIGNING_KEY); the third was still tracked on 2026-08-06 holding the DeepSeek
# key that is live in .env today. A bare `git commit` of everything staged means
# one missed glob is a pushed secret, so the guard reads CONTENT, not names.
#
# -I skips binaries deliberately: bin/tirith is a Mach-O whose compiled-in secret
# DETECTION patterns match these same regexes and are not keys.
# Failure mode is safe-by-design — a false positive unstages one file and warns,
# so that file is not backed up until a human looks. It never blocks the sync.
SECRET_RE='sk-ant-api[0-9]{2}-|sk-proj-[A-Za-z0-9_-]{20}|sk-[a-f0-9]{32}|AIza[0-9A-Za-z_-]{35}|[0-9]{9,10}:AA[A-Za-z0-9_-]{33}|(API_KEY|_SECRET|_TOKEN|PASSWORD)[[:space:]]*[=:][[:space:]]*.?[A-Za-z0-9_-]{24}'

while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt 5242880 ]; then
    git restore --staged -- "$f" 2>/dev/null || true
    warn "refused to commit $f ($((size / 1048576))MB) — add it to .gitignore or store it elsewhere"
    continue
  fi
  if grep -IqE "$SECRET_RE" -- "$f" 2>/dev/null; then
    git restore --staged -- "$f" 2>/dev/null || true
    warn "REFUSED TO COMMIT $f — it contains a credential-shaped string. NOT backed up. Move the value to .env (ignored) and delete it from this file."
    problems=$((problems + 1))
  fi
done < <(git diff --cached --name-only --diff-filter=ACM)

if git diff --cached --quiet; then
  echo "Nothing to commit after filtering"
  exit $problems
fi

staged=$(git diff --cached --name-only | wc -l | tr -d ' ')

if ! out=$(git commit -m "auto: sync $(date '+%Y-%m-%d %H:%M:%S')" 2>&1); then
  echo "Commit failed: $out" >&2
  exit 1
fi

if ! out=$(timeout "$NET_TIMEOUT" git push origin main 2>&1); then
  echo "Push failed (retry next cycle): $out" >&2
  log "push failed: $out"
  exit 1
fi

echo "Pushed $staged file(s)"
log "OK pushed $staged file(s); rc=$problems"
exit $problems
