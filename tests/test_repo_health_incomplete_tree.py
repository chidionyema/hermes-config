"""Proof for the repo-health incomplete-tree fix (2026-08-18).

The failure this pins: signalengine paged 'crit' as
"signalengine: FAIL — no tests collected in 0.02s". Since pytest 8, a testpaths
entry that matches nothing is not an error — pytest collects zero tests and exits
5 in ~0.02s. The tests/ directory was gone (the working tree had been re-cloned),
so repo-health-check.py graded a wiped tree as a broken test suite.

These tests prove the fix has teeth in BOTH directions:
  - incomplete tree  -> 'skip' (no false crit), and it names what is missing
  - complete tree + genuinely failing command -> still 'fail' (no false pass)
"""

from __future__ import annotations

import importlib.util
import pathlib
from pathlib import Path

import pytest

_SRC = Path.home() / ".hermes" / "scripts" / "repo-health-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rhc = _load()


def test_missing_test_dir_is_skip_not_fail(tmp_path):
    """A tree missing tests/ must not be graded as a failing test suite."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    # tests/ deliberately absent — this is the wiped-tree state
    marker = tmp_path / "RAN"
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        # would exit 5 exactly like the real run; must never be reached
        "test_cmd": f"touch {marker}; exit 5",
    })
    assert res["state"] == "skip", res
    assert "tests" in res["summary"], res
    assert "FAIL" not in res["summary"], res
    # The guard decides from the tree, so the command must never run at all.
    assert not marker.exists(), "test_cmd ran despite an incomplete tree"


def test_empty_test_dir_is_skip_not_fail(tmp_path):
    """A tests/ that exists but is EMPTY is the same wiped tree, not a broken suite.

    Existence-only checking let this through and reproduced the original page
    verbatim: pytest collects nothing and exits 5 in ~0.02s.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__pycache__").mkdir()   # wipe leftovers don't count
    marker = tmp_path / "RAN"
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": f"touch {marker}; echo 'no tests collected in 0.02s'; exit 5",
    })
    assert res["state"] == "skip", res
    assert "tests" in res["summary"], res
    assert "FAIL" not in res["summary"], res
    assert not marker.exists(), "test_cmd ran despite an incomplete tree"


def test_complete_tree_still_fails_on_real_test_failure(tmp_path):
    """Teeth: with every prerequisite present, a failing command still pages."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": "echo '1 failed'; exit 1",
    })
    assert res["state"] == "fail", res
    assert "1 failed" in res["summary"], res


def test_populated_tree_with_empty_selection_still_fails(tmp_path):
    """Teeth: real test files present but zero collected is still a genuine 'fail'.

    The skip path is only for a tree that cannot answer the question at all.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": "echo 'no tests collected in 0.02s'; exit 5",
    })
    assert res["state"] == "fail", res
    assert "no tests collected" in res["summary"], res


def test_present_is_false_when_iterdir_raises_eperm(tmp_path, monkeypatch):
    """A directory we cannot LIST is as unusable as a missing one.

    Path.exists() swallows OSError, so it returned True while iterdir() raised
    PermissionError — that exception escaped check_repo and main() minted
    "signalengine: runner error [Errno 1] Operation not permitted".
    """
    d = tmp_path / "tests"
    d.mkdir()
    (d / "test_x.py").write_text("def test_x():\n    assert True\n")
    assert rhc._present(d) is True, "precondition: readable dir is present"

    def _denied(self):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "iterdir", _denied)
    assert rhc._present(d) is False


def test_check_repo_skips_when_required_dir_is_unreadable(tmp_path, monkeypatch):
    """EPERM on a prerequisite grades 'skip' — never 'fail', never 'runner error'."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    marker = tmp_path / "RAN"

    def _denied(self):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "iterdir", _denied)

    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": f"touch {marker}; exit 5",
    })
    assert res["state"] == "skip", res
    assert "runner error" not in res["summary"], res
    assert "FAIL" not in res["summary"], res
    assert not marker.exists(), "test_cmd ran despite an unreadable tree"


def test_real_signalengine_tree_is_complete():
    """The live repo must satisfy its own declared prerequisites."""
    info = rhc.REPOS["signalengine"]
    root = Path(info["path"])
    if not root.exists():
        pytest.skip("signalengine not present on this host")
    missing = [r for r in info["requires"] if not rhc._present(root / r)]
    assert missing == [], f"missing: {missing}"
