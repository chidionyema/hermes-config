#!/bin/bash
# auto-push.sh — Config auto-push for Hermes estate
# Safely commits and pushes hermes config changes.
# Handles git lock collisions, dirty states, and network failures gracefully.

set -e

cd "$HOME/.hermes" || exit 1

# ── Git lock cleanup ──
# Remove stale lock files (older than 5 minutes)
LOCK_FILE=".git/index.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "$LOCK_AGE" -gt 300 ] 2>/dev/null; then
        echo "Removing stale git lock file (${LOCK_AGE}s old)" >&2
        rm -f "$LOCK_FILE"
    else
        echo "Git lock file is recent (${LOCK_AGE}s) — skipping this run" >&2
        exit 0
    fi
fi

# ── Check for changes ──
if ! git diff --quiet 2>/dev/null && ! git diff --cached --quiet 2>/dev/null; then
    echo "No changes to push" >&2
    exit 0
fi

# ── Stage and commit ──
git add -A 2>/dev/null || true

if git diff --cached --quiet 2>/dev/null; then
    exit 0  # Nothing staged
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
git commit -m "estate: auto-push snapshot $TIMESTAMP" 2>&1 || {
    echo "Commit failed (may already be clean)" >&2
    exit 0
}

# ── Push ──
git push origin "$(git branch --show-current)" 2>&1 || {
    echo "Push failed (network or permission)" >&2
    exit 1
}

echo "✅ Config auto-pushed at $TIMESTAMP"
