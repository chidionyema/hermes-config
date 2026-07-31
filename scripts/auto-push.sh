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

problems=0
warn() {
  echo "WARN: $*" >&2
  problems=1
}

# Back up the hermes-agent submodule off-machine (parent only stores its pointer).
bash "$HOME/.hermes/recovery/backup-submodule.sh" || warn "submodule backup failed"

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

CHANGES=$(git status --porcelain)
if [ -z "$CHANGES" ]; then
  exit $problems
fi

git add -A

# Lane-guarded files have a single designated writer; unstaging them keeps the pre-commit
# hook from blocking this sync.
git restore --staged config.yaml plugins/otto-inbound/__init__.py scripts/coordinator.py \
  2>/dev/null || true

# Backstop against the next large binary someone drops in the tree. This repo is text and
# config; anything over 5MB is staged by accident and gets dropped with a warning rather
# than silently committed forever.
while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt 5242880 ]; then
    git restore --staged -- "$f" 2>/dev/null || true
    warn "refused to commit $f ($((size / 1048576))MB) — add it to .gitignore or store it elsewhere"
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

if ! out=$(git push origin main 2>&1); then
  echo "Push failed (retry next cycle): $out" >&2
  exit 1
fi

echo "Pushed $staged file(s)"
exit $problems
