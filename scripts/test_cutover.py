"""Phase 3 CUTOVER proof: worktree isolation + merge-back wired into agentic_execute.

Proves the claims the cutover rests on, on a real throwaway git repo:
  1. merge-back lands the executor's work on the live repo (ff-only).
  2. teeth: if the live branch moved, merge-back REFUSES (no silent bad merge).
  3. success path: agentic_execute runs the executor in a worktree and the edit
     reaches the LIVE repo (not just the worktree).
  4. crash path: a failing executor leaves the live repo EXACTLY as it was, worktree gone.
  5. read-only task: no changes ⇒ no merge, worktree cleaned, live repo untouched.
"""
import os, subprocess, tempfile, shutil, importlib
import sandbox
import coordinator


def _git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def _new_repo():
    d = tempfile.mkdtemp(prefix="cutover-repo-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    with open(os.path.join(d, "README"), "w") as f:
        f.write("base\n")
    _git(d, "add", "-A"); _git(d, "commit", "-m", "base")
    return d


def _wt_base():
    b = tempfile.mkdtemp(prefix="cutover-wt-")
    return b


def test_merge_back_round_trip():
    repo, wtbase = _new_repo(), _wt_base()
    try:
        wt = sandbox.make_worktree(repo, "t1", base=wtbase)
        with open(os.path.join(wt, "feature.txt"), "w") as f:
            f.write("landed\n")
        assert sandbox.commit_all(wt, "feat") is True
        assert sandbox.merge_back(repo, sandbox.worktree_head(wt)) is True
        # the file is now on the LIVE repo's main branch
        assert os.path.exists(os.path.join(repo, "feature.txt"))
        assert _git(repo, "log", "--oneline").stdout.count("\n") >= 2
    finally:
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(wtbase, ignore_errors=True)


def test_merge_back_refuses_when_branch_moved():
    """Teeth: a competing commit on live main makes the worktree commit non-ff ⇒ REFUSE."""
    repo, wtbase = _new_repo(), _wt_base()
    try:
        wt = sandbox.make_worktree(repo, "t2", base=wtbase)
        with open(os.path.join(wt, "a.txt"), "w") as f:
            f.write("wt\n")
        sandbox.commit_all(wt, "wt-work")
        # live main moves underneath us (founder committed)
        with open(os.path.join(repo, "b.txt"), "w") as f:
            f.write("live\n")
        _git(repo, "add", "-A"); _git(repo, "commit", "-m", "live-work")
        assert sandbox.merge_back(repo, sandbox.worktree_head(wt)) is False   # refused, no clobber
        assert not os.path.exists(os.path.join(repo, "a.txt"))               # wt work NOT forced in
    finally:
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(wtbase, ignore_errors=True)


def _patch_exec(monkeypatch_repo, behavior):
    """Point _task_repo at our temp repo, force worktrees under a temp base, and replace the
    real claude/agy spawn with `behavior(cwd) -> (rc, out)`."""
    coordinator._task_repo = lambda task: monkeypatch_repo
    orig_base = sandbox.WORKTREE_BASE
    coordinator.get_execute_prompt = lambda: "{spec} {title}"

    def fake_run_bounded(argv, timeout=None, input=None, capture_output=False,
                         text=False, env=None, cwd=None, stdin=None):
        rc, out = behavior(cwd)
        return subprocess.CompletedProcess(argv, rc, out, "")
    coordinator.run_bounded = fake_run_bounded
    return orig_base


def test_agentic_execute_success_lands_on_live_repo():
    repo, wtbase = _new_repo(), _wt_base()
    sandbox.WORKTREE_BASE = wtbase
    orig = (coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt)
    try:
        def behavior(cwd):
            assert cwd != repo and cwd.startswith(wtbase)   # ran in the WORKTREE, not live repo
            with open(os.path.join(cwd, "done.txt"), "w") as f:
                f.write("ok\n")
            return 0, "executor did the work"
        _patch_exec(repo, behavior)
        result = coordinator.agentic_execute({"id": "9", "title": "x", "spec": "{}", "source": "project:p"})
        assert "executor did the work" in result
        assert os.path.exists(os.path.join(repo, "done.txt"))               # merged back to LIVE
        assert not os.path.isdir(os.path.join(wtbase, "9"))                 # worktree cleaned
    finally:
        coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt = orig
        sandbox.WORKTREE_BASE = "/Users/chidionyema/.hermes/worktrees"
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(wtbase, ignore_errors=True)


def test_agentic_execute_crash_leaves_live_repo_untouched():
    repo, wtbase = _new_repo(), _wt_base()
    sandbox.WORKTREE_BASE = wtbase
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    orig = (coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt)
    try:
        def behavior(cwd):
            with open(os.path.join(cwd, "junk.txt"), "w") as f:    # executor scribbles then dies
                f.write("partial\n")
            return 1, "boom"                                       # both claude+agy 'fail'
        _patch_exec(repo, behavior)
        raised = False
        try:
            coordinator.agentic_execute({"id": "7", "title": "x", "spec": "{}", "source": "project:p"})
        except RuntimeError:
            raised = True
        assert raised
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before   # live repo UNTOUCHED
        assert not os.path.exists(os.path.join(repo, "junk.txt"))
        assert not os.path.isdir(os.path.join(wtbase, "7"))               # worktree discarded
    finally:
        coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt = orig
        sandbox.WORKTREE_BASE = "/Users/chidionyema/.hermes/worktrees"
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(wtbase, ignore_errors=True)


def test_agentic_execute_readonly_task_no_merge():
    repo, wtbase = _new_repo(), _wt_base()
    sandbox.WORKTREE_BASE = wtbase
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    orig = (coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt)
    try:
        _patch_exec(repo, lambda cwd: (0, "read-only report, no edits"))
        result = coordinator.agentic_execute({"id": "5", "title": "x", "spec": "{}", "source": "project:p"})
        assert "read-only report" in result
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before   # nothing committed
        assert not os.path.isdir(os.path.join(wtbase, "5"))               # worktree cleaned
    finally:
        coordinator._task_repo, coordinator.run_bounded, coordinator.get_execute_prompt = orig
        sandbox.WORKTREE_BASE = "/Users/chidionyema/.hermes/worktrees"
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(wtbase, ignore_errors=True)
