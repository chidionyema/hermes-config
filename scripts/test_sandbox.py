"""§7 Phase 3 sabotage test for sandbox.py, against a real throwaway git repo.
Run: python3 test_sandbox.py

Models the spec scenario: a sandbox keeps failing. Strikes 1-2 soft-reset (discard the
mess, keep the worktree); strike 3 hard-cleans (worktree gone). We prove each with real
git operations, plus a teeth check that soft_reset actually discards changes.
"""
import os, sys, subprocess, tempfile, shutil
import sandbox


def make_repo():
    d = tempfile.mkdtemp(prefix="sbx_repo_")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", d], check=True, env=env)
    open(os.path.join(d, "f.txt"), "w").write("base\n")
    subprocess.run(["git", "-C", d, "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", d, "commit", "-qm", "init"], check=True, env=env)
    return d


def test_worktree_and_soft_reset():
    repo = make_repo()
    base = tempfile.mkdtemp(prefix="sbx_wt_")
    wt = sandbox.make_worktree(repo, "T1", base=base)
    assert os.path.isdir(os.path.join(wt, ".git")) or os.path.exists(os.path.join(wt, ".git")), "not a worktree"

    # sabotage: executor dirties the worktree
    open(os.path.join(wt, "junk.txt"), "w").write("garbage")
    open(os.path.join(wt, "f.txt"), "w").write("corrupted")
    sandbox.soft_reset(wt)
    assert not os.path.exists(os.path.join(wt, "junk.txt")), "TEETH: soft_reset left untracked junk"
    assert open(os.path.join(wt, "f.txt")).read() == "base\n", "TEETH: soft_reset did not restore tracked file"

    sandbox.remove_worktree(repo, "T1", base=base)
    assert not os.path.exists(wt), "hard cleanup left the worktree behind"
    shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(base, ignore_errors=True)
    print("PASS  worktree: create -> soft_reset discards mess -> remove cleans up (real git)")


def test_strike_matrix_sequence():
    repo = make_repo()
    base = tempfile.mkdtemp(prefix="sbx_wt_")
    wt = sandbox.make_worktree(repo, "T2", base=base)

    actions = []
    for strike in (1, 2, 3):  # a sandbox that fails three times
        action = sandbox.decide_action(strike)
        actions.append(action)
        if action == "soft_reset":
            open(os.path.join(wt, "f.txt"), "w").write(f"fail{strike}")
            sandbox.soft_reset(wt)
            assert open(os.path.join(wt, "f.txt")).read() == "base\n", f"strike {strike} not reset"
        else:
            sandbox.remove_worktree(repo, "T2", base=base)

    assert actions == ["soft_reset", "soft_reset", "hard_cleanup"], f"wrong matrix: {actions}"
    assert not os.path.exists(wt), "strike 3 did not drop the worktree"
    shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(base, ignore_errors=True)
    print("PASS  strike matrix: 1->soft, 2->soft, 3->hard cleanup; worktree gone after strike 3")


if __name__ == "__main__":
    try:
        test_worktree_and_soft_reset()
        test_strike_matrix_sequence()
    except AssertionError as e:
        print("FAIL ", e); sys.exit(1)
    print("ALL GREEN")
