#!/bin/bash
# backup-submodule.sh — push an off-machine snapshot of the hermes-agent submodule.
#
# WHY: scripts/auto-push.sh backs up the PARENT repo hourly, but only records the
# submodule POINTER (a gitlink SHA) — the submodule's own commits/objects never leave
# this disk. The submodule is also a SHALLOW clone (missing ancestors), so a normal
# `git push` fails (index-pack / missing object). If the disk dies, all agent-code
# changes would be lost.
#
# HOW: snapshot HEAD's tree as a PARENTLESS commit (git commit-tree) and force-push it
# to a single rolling branch on the PRIVATE backup remote. Parentless => no ancestors
# needed => works on a shallow clone. No branch switch, no index touch => safe to run
# while the gateway/daemon are live. NEVER pushes to origin (NousResearch is a PUBLIC
# upstream; pushing estate code there would be a disclosure).
set -u

SUB="$HOME/.hermes/hermes-agent"
BRANCH="estate-snapshot"          # rolling, force-updated each run
REMOTE="backup"                   # private: github.com/chidionyema/hermes-agent
ORIGIN_FORBIDDEN="NousResearch"   # guard: never push estate code to the public upstream

cd "$SUB" 2>/dev/null || { echo "backup-submodule: $SUB missing"; exit 1; }

# Ensure the private backup remote exists and is NOT the public upstream.
url="$(git remote get-url "$REMOTE" 2>/dev/null || true)"
if [ -z "$url" ]; then
  echo "backup-submodule: remote '$REMOTE' not configured — skipping (run recovery/restore.sh setup)"; exit 0
fi
case "$url" in
  *"$ORIGIN_FORBIDDEN"*) echo "backup-submodule: REFUSING — '$REMOTE' points at public upstream ($url)"; exit 1;;
esac

# Identity for commit-tree (cron has no tty; be explicit).
name="$(git config user.name || echo estate-backup)"
email="$(git config user.email || echo estate-backup@localhost)"
export GIT_AUTHOR_NAME="$name" GIT_AUTHOR_EMAIL="$email"
export GIT_COMMITTER_NAME="$name" GIT_COMMITTER_EMAIL="$email"

head_sha="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
head_msg="$(git log -1 --pretty=%s 2>/dev/null || echo '?')"
tree="$(git rev-parse 'HEAD^{tree}' 2>/dev/null)" || { echo "backup-submodule: cannot resolve HEAD tree"; exit 1; }

# Parentless snapshot commit of the current tracked tree.
stamp="$(date '+%Y-%m-%d %H:%M:%S')"
commit="$(git commit-tree "$tree" -m "estate snapshot $stamp (from $head_sha: $head_msg)")" \
  || { echo "backup-submodule: commit-tree failed"; exit 1; }

if git push -f "$REMOTE" "$commit:refs/heads/$BRANCH" 2>/tmp/_bk_sub.err; then
  echo "backup-submodule: pushed snapshot $head_sha -> $REMOTE/$BRANCH ($commit)"
else
  echo "backup-submodule: push failed (will retry next cycle): $(tail -1 /tmp/_bk_sub.err)"
  exit 0   # never break the caller's hourly parent sync
fi
