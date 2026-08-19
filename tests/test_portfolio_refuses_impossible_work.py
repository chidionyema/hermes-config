"""The coordinator must not file work that cannot run on this machine.

Measured on prospector-hermes 2026-08-19: four project tasks were escalating, every one of
them "inspect the repo at ~/Documents/code" against a repo that exists only on the laptop, on
a container with no `claude` and therefore no tool-capable executor. Each cost a strategist
call, an executor call, an acceptance run and a push to the founder's phone to arrive at "I
have no filesystem access". Refuse once at intake instead of rediscovering it every six hours.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))

import coordinator as C  # noqa: E402


def test_a_repo_that_is_not_here_blocks_the_project():
    assert C._project_is_unworkable({"key": "x", "repo": "/definitely/not/here"}) \
        == "repo not on this machine: /definitely/not/here"


def test_no_tool_capable_executor_blocks_the_project(monkeypatch):
    monkeypatch.setattr(C.shutil, "which", lambda b: None)
    reason = C._project_is_unworkable({"key": "x", "repo": str(Path.home())})
    assert reason and "no tool-capable executor" in reason


def test_the_block_can_be_overridden_deliberately(monkeypatch):
    monkeypatch.setattr(C.shutil, "which", lambda b: None)
    monkeypatch.setenv("COORD_REQUIRE_EXECUTOR", "0")
    assert C._project_is_unworkable({"key": "x", "repo": str(Path.home())}) is None


def test_a_workable_project_is_not_blocked(monkeypatch):
    monkeypatch.setattr(C.shutil, "which", lambda b: "/usr/bin/" + b)
    assert C._project_is_unworkable({"key": "x", "repo": str(Path.home())}) is None


def test_the_refusal_is_logged_once_not_every_tick():
    C._UNWORKABLE_SEEN.clear()
    assert C._note_unworkable(None, "k", "reason one") is True
    assert C._note_unworkable(None, "k", "reason one") is False
    assert C._note_unworkable(None, "k", "reason two") is True


def test_both_live_projects_declare_a_repo_path():
    """A project with no `repo` cannot be checked at all, so the guard would wave it through."""
    for p in C.load_projects():
        if p.get("status") == "active" or p.get("active"):
            assert C._project_repo_root(p), f"{p.get('key')} declares no repo"
