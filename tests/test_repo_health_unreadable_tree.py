"""Proof for the repo-health unreadable-tree fix (2026-08-18).

The failure this pins: signalengine paged pass -> fail as
"signalengine: runner error [Errno 1] Operation not permitted:
'/Users/chidionyema/Documents/code/signalengine/tests'".

_present() called p.iterdir() with no OSError guard. Path.exists() swallows
OSError and returned True, so the listing ran and raised PermissionError under a
sandboxed/TCC-denied ad-hoc run. The exception escaped check_repo, hit the
blanket `except Exception` in main(), and was graded 'fail'. A filesystem access
error says nothing about the test suite.

These tests prove the fix has teeth in BOTH directions:
  - unreadable prerequisite -> 'skip' (no false fail), and test_cmd never runs
  - readable complete tree + genuinely failing command -> still 'fail'
"""

from __future__ import annotations

import importlib.util
import pathlib
from pathlib import Path

_SRC = Path.home() / ".hermes" / "scripts" / "repo-health-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rhc = _load()


def test_unreadable_test_dir_is_skip_not_fail(tmp_path, monkeypatch):
    """EPERM listing a COMPLETE tree must grade 'skip', not page a fail."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    marker = tmp_path / "MARKER"

    def _denied(self):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "iterdir", _denied)

    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        # exits non-zero exactly like the real run; must never be reached
        "test_cmd": f"touch {marker}; exit 5",
    })
    assert res["state"] == "skip", res
    assert "tests" in res["summary"], res
    assert "FAIL" not in res["summary"], res
    assert not marker.exists(), "test_cmd ran despite an unreadable tree"


def test_readable_complete_tree_still_fails(tmp_path):
    """Teeth: with iterdir working and every prerequisite present, a failing
    command still pages 'fail'. The guard must not swallow real failures."""
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
