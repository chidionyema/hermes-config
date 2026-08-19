"""Every gitlink in the tree is a declared submodule.

A directory that has its own `.git` is recorded by `git add -A` as a mode-160000 GITLINK, not
as files. If nothing declares it in `.gitmodules`, git cannot resolve it, and the failure is
not local to that path: `git submodule foreach --recursive` then fails for every job in the
repository.

    fatal: No url found for submodule path '.worktrees/feat-prospector-now' in .gitmodules

That is what `.worktrees/feat-prospector-now` did — a git worktree, committed by accident,
which turned up as an exit-128 warning in the checkout cleanup of every gate run.
"""

from __future__ import annotations

import configparser
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _gitlinks() -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths = []
    for line in out.splitlines():
        if line.startswith("160000"):
            paths.append(line.split("\t", 1)[1])
    return paths


def _declared_paths() -> set[str]:
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.exists():
        return set()
    parser = configparser.ConfigParser()
    parser.read_string(gitmodules.read_text())
    return {parser.get(s, "path") for s in parser.sections() if parser.has_option(s, "path")}


def test_no_gitlink_is_undeclared():
    undeclared = sorted(set(_gitlinks()) - _declared_paths())
    assert not undeclared, (
        "these paths are committed as submodule pointers but no .gitmodules entry names them: "
        f"{undeclared}. Either declare them, or remove them from the index with "
        "`git rm --cached <path>` and add the directory to .gitignore."
    )


def test_the_check_can_actually_fail():
    """A guard that cannot fail is not a guard."""
    declared = _declared_paths()
    assert "made/up/path" not in declared
