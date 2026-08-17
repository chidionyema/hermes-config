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

# Snapshot commit of the current tracked tree, parented on the PREVIOUS snapshot when
# one can be fetched. The parent is what makes the push a delta.
#
# Measured 2026-08-07, pushing the same tree both ways to the same remote:
#   parentless: 235s, then `error: RPC failed; HTTP 408 curl 22` — the server gave up
#               mid-pack, because a parentless commit shares no ancestry with the remote
#               branch, so git can negotiate nothing and re-uploads the ENTIRE tree.
#   parented:   2s, "04bfbe5335..f2ce8ef552 -> estate-snapshot".
#
# Parentless was the original design for a good reason — this is a SHALLOW clone, so an
# ordinary push of HEAD fails for want of ancestors. Fetching just the previous snapshot
# (--depth=1) keeps that property: the parent is one complete object, not a history.
# If the fetch fails for any reason we fall back to the old parentless behaviour, which
# is slow and flaky but still correct.
stamp="$(date '+%Y-%m-%d %H:%M:%S')"
parent_args=()
if git fetch --depth=1 "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  prev="$(git rev-parse FETCH_HEAD 2>/dev/null || true)"
  [ -n "$prev" ] && parent_args=(-p "$prev")
fi
commit="$(git commit-tree "$tree" "${parent_args[@]+"${parent_args[@]}"}" -m "estate snapshot $stamp (from $head_sha: $head_msg)")" \
  || { echo "backup-submodule: commit-tree failed"; exit 1; }

# Retry the push before calling it a failure. Measured 2026-08-17: the last 11 daily
# receipts were 6 exit-0 and 5 exit-1, alternating with no pattern, and running this same
# script by hand seconds after a recorded failure pushed cleanly in one attempt
# (52200eda75 -> backup/estate-snapshot). So the failures were transient network trouble
# on a single attempt, not a broken backup — and one bad attempt a day was enough to
# score the capability BROKEN. Three attempts with backoff; a real outage still fails,
# because the loop reports the LAST attempt's stderr and exits 1.
pushed=0
for attempt in 1 2 3; do
  if git push -f "$REMOTE" "$commit:refs/heads/$BRANCH" 2>/tmp/_bk_sub.err; then
    pushed=1
    break
  fi
  [ "$attempt" -lt 3 ] && {
    echo "backup-submodule: push attempt $attempt failed, retrying in $((attempt * 15))s"
    sleep $((attempt * 15))
  }
done

if [ "$pushed" = 1 ]; then
  echo "backup-submodule: pushed snapshot $head_sha -> $REMOTE/$BRANCH ($commit) on attempt $attempt"
else
  # NOT tail -1. git's last stderr line here is "Everything up-to-date", which is emitted
  # after the real error and reads like success — so for as long as this used tail -1, a
  # genuine "RPC failed; HTTP 408" outage was reported as a reassuring no-op and went
  # undiagnosed. Show the first error line, and keep the rest for the log.
  echo "backup-submodule: push failed after 3 attempts: $(grep -m1 -E '^(error|fatal):' /tmp/_bk_sub.err || tail -1 /tmp/_bk_sub.err)"
  sed 's/^/backup-submodule:   /' /tmp/_bk_sub.err
  # Was `exit 0` to protect scripts/auto-push.sh, which used to call this hourly.
  # It is now a standalone daily job (ai.hermes.submodule-backup) scored on its own
  # receipt, so swallowing a failed push would launder "the off-machine copy of all
  # agent code did not happen" into a clean exit — the one thing this script exists
  # to prevent. Nothing downstream depends on this exit code any more.
  exit 1
fi
