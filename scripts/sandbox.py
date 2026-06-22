"""Disposable git-worktree sandboxes + strike matrix (spec §7 Phase 3 primitives).

Worktrees live under ~/.hermes/worktrees, NOT ~/Documents/code: the launchd coordinator's
ability to write under TCC-protected ~/Documents is UNPROVEN (coordinator logs are empty),
and ~/.hermes is the relocation already proven to fix the TCC EPERM class in §4.1. The
source repos stay in ~/Documents/code; `git worktree add` checks them out into ~/.hermes.

These are pure primitives — they do NOT rewire the live execution path. Wiring the
substrate swap into agentic_execute() is a separate cutover (changes where every task runs).
"""
import os, shutil, subprocess

WORKTREE_BASE = os.path.expanduser("~/.hermes/worktrees")


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)


def make_worktree(repo: str, task_id: str, base: str = None) -> str:
    """Detached worktree for `task_id` at base/task_id, checked out from `repo`."""
    base = base or WORKTREE_BASE          # resolve at call time so WORKTREE_BASE stays overridable
    os.makedirs(base, exist_ok=True)
    wt = os.path.join(base, task_id)
    if os.path.exists(wt):
        remove_worktree(repo, task_id, base)
    r = _git(repo, "worktree", "add", "--detach", wt)
    if r.returncode != 0:
        raise RuntimeError(f"worktree add failed: {(r.stderr or '').strip()[:200]}")
    return wt


def soft_reset(worktree: str) -> None:
    """Strike 1-2 recovery: discard all changes in the worktree, keep it."""
    _git(worktree, "reset", "--hard")
    _git(worktree, "clean", "-fd")


def remove_worktree(repo: str, task_id: str, base: str = None) -> None:
    """Strike 3 recovery: drop the worktree entirely (git metadata + dir)."""
    base = base or WORKTREE_BASE
    wt = os.path.join(base, task_id)
    _git(repo, "worktree", "remove", "--force", wt)
    if os.path.exists(wt):
        shutil.rmtree(wt, ignore_errors=True)


def decide_action(strike: int) -> str:
    """Strike matrix: strikes 1-2 soft-reset; strike 3+ hard-cleanup (+ split + alert)."""
    return "soft_reset" if strike <= 2 else "hard_cleanup"


# ── Merge-back: land worktree work on the live repo, or lose nothing ──────────────
# The cutover runs the executor in a detached worktree (created at the repo's current
# HEAD). To make the work real it must come back to the live repo. We commit everything
# the executor produced in the worktree, then FAST-FORWARD-ONLY merge it onto the live
# branch. ff-only is the safety: it succeeds iff the live branch is still exactly the
# commit the worktree branched from — i.e. nobody else moved it. If anyone did (founder
# committed, a rebase is in flight), ff-only REFUSES rather than risk a bad merge, and
# the caller keeps the worktree so the work is recoverable, never silently shredded.

def commit_all(worktree: str, message: str) -> bool:
    """Stage & commit every change the executor made in the worktree. Returns True iff a
    new commit was created (False when the task touched nothing — e.g. a read-only report)."""
    _git(worktree, "add", "-A")
    # `diff --cached --quiet` exits 0 when nothing is staged, 1 when there are changes.
    if _git(worktree, "diff", "--cached", "--quiet").returncode == 0:
        return False
    r = _git(worktree, "-c", "user.name=hermes-estate",
             "-c", "user.email=estate@hermes.local", "commit", "-m", message)
    if r.returncode != 0:
        raise RuntimeError(f"worktree commit failed: {(r.stderr or '').strip()[:200]}")
    return True


def worktree_head(worktree: str) -> str:
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()


def merge_back(repo: str, commit: str) -> bool:
    """Fast-forward the live repo to `commit`. True iff it landed cleanly; False means the
    live branch moved underneath us (caller must preserve the worktree — work is at `commit`)."""
    return _git(repo, "merge", "--ff-only", commit).returncode == 0
