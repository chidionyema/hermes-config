"""Proof that an UNREADABLE prerequisite is graded as a host fault (2026-08-18).

The failure this pins: "failure: signalengine: fail -> skip: signalengine:
incomplete tree — missing or unreadable tests". Nothing was wrong with
signalengine. Its tests/ directory held 50+ files the whole time; the host
refused to list it in that one tick (the same tick where lux reported
"getcwd: cannot access parent dir" and prospector flipped identically).

_present() returned False for two different conditions — genuinely absent, and
present but unlistable — and _check_repo collapsed both into one 'skip' with no
`transient` flag. So _is_flake gave it no one-tick grace and main() paged the
fail -> skip transition immediately.

These tests prove the split has teeth in BOTH directions:
  - unreadable prerequisite -> 'skip' + transient=True (host fault, gets grace)
  - genuinely missing prerequisite -> 'skip' with NO transient flag (still pages)
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


def test_unreadable_required_dir_is_transient_skip(tmp_path, monkeypatch):
    """EPERM listing a COMPLETE tree grades 'skip' AND flags it transient."""
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
        # exits non-zero exactly like the real run; must never be reached
        "test_cmd": f"touch {marker}; exit 5",
    })
    assert res["state"] == "skip", res
    assert res.get("transient") is True, res
    assert "tests" in res["summary"], res
    assert "FAIL" not in res["summary"], res
    assert not marker.exists(), "test_cmd ran despite an unreadable tree"


def test_missing_required_dir_is_not_transient(tmp_path):
    """Teeth: a genuinely absent tests/ is a repo defect and must still page."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    # tests/ deliberately absent — the wiped-tree state, not a host fault
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": "exit 5",
    })
    assert res["state"] == "skip", res
    assert "transient" not in res, res
    assert "tests" in res["summary"], res


def test_transient_skip_gets_one_tick_grace_then_pages(tmp_path, monkeypatch):
    """The flag must actually buy grace in _is_flake, and only for one tick."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")

    def _denied(self):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "iterdir", _denied)

    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": "exit 5",
    })
    # First consecutive occurrence: suppressed.
    assert rhc._is_flake(name, res, {name: {"state": "pass"}}) is True
    # Second consecutive occurrence: the previous tick already carried the flag.
    assert rhc._is_flake(name, res, {name: res}) is False


def test_missing_dir_never_gets_grace(tmp_path):
    """A missing prerequisite is never suppressed, on any tick."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": ["pyproject.toml", "tests"],
        "test_cmd": "exit 5",
    })
    assert rhc._is_flake(name, res, {name: {"state": "pass"}}) is False
