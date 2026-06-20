#!/bin/bash
# no-agent config auto-push
# Replaces the LLM-driven cron job that kept hitting Broken pipe errors.
# No LLM needed — just git add, commit, push.

set -e
cd "$HOME/.hermes" || exit 1

# Back up the hermes-agent submodule off-machine (parent only stores its pointer).
# Runs every cycle regardless of parent changes; never breaks this sync if it fails.
bash "$HOME/.hermes/recovery/backup-submodule.sh" || true

# Check for uncommitted changes
CHANGES=$(git status --porcelain 2>/dev/null)
if [ -z "$CHANGES" ]; then
  # No changes — silent exit
  exit 0
fi

# Stage everything
git add -A 2>/dev/null || true

# Commit
COMMIT_MSG="auto: sync $(date '+%Y-%m-%d %H:%M:%S')"
git commit -m "$COMMIT_MSG" 2>/dev/null || true

# Push
git push origin main 2>/dev/null || echo "Push failed (network issue — will retry next cycle)"

# Report what was committed
echo "Pushed $(echo "$CHANGES" | wc -l | tr -d ' ') uncommitted files"