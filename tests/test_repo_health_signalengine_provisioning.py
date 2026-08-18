"""Proof for the signalengine provisioning fix (2026-08-18).

The failure this pins: repo-health paged "signalengine: TIMEOUT" at 12:52:06 and
12:53:40 on 2026-08-18 (logs/health/repo-health.jsonl lines 412-413). The working
tree had just been re-cloned (git reflog "branch: Created from origin/main" at
12:54:51) and its .venv was still being built. The test command was
`uv run pytest --collect-only`, and plain `uv run` SYNCS the project — resolve,
download and build the whole dependency tree — before it runs anything. So the
per-repo timeout was timing a dependency install, not the test suite.

Two teeth:
  - the timed command must not provision (no bare `uv run`)
  - an unbuilt environment must grade 'skip', not burn the timeout and page
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SRC = Path.home() / ".hermes" / "scripts" / "repo-health-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rhc = _load()


def test_no_python_repo_provisions_inside_the_timeout():
    """No repo may run its tests through `uv run`, which syncs before it runs."""
    for name, info in rhc.REPOS.items():
        cmd = info["test_cmd"]
        assert "uv run" not in cmd, f"{name} provisions inside the timed path: {cmd}"


def test_signalengine_uses_the_prebuilt_interpreter():
    info = rhc.REPOS["signalengine"]
    assert info["test_cmd"].startswith(".venv/bin/python -m pytest"), info["test_cmd"]
    assert ".venv/bin/python" in info["requires"], info["requires"]


def test_unbuilt_venv_is_skip_not_fail(tmp_path):
    """A repo whose environment is not built yet must skip, never page."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    # .venv deliberately absent — this is the cold / freshly cloned tree
    marker = tmp_path / "RAN"
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": rhc.REPOS["signalengine"]["requires"],
        "test_cmd": f"touch {marker}; exit 1",
    })
    assert res["state"] == "skip", res
    assert ".venv/bin/python" in res["summary"], res
    assert not marker.exists(), "test_cmd ran despite an unbuilt environment"


def test_built_venv_still_fails_on_a_real_test_failure(tmp_path):
    """Teeth: with the environment present, a failing suite still pages."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    name, res = rhc.check_repo("signalengine", {
        "path": str(tmp_path),
        "requires": rhc.REPOS["signalengine"]["requires"],
        "test_cmd": "echo '1 failed'; exit 1",
    })
    assert res["state"] == "fail", res
    assert "1 failed" in res["summary"], res
