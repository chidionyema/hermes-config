"""Proof for the estate-wide host-fault fix (2026-08-18T17:22:48Z).

The failure this pins: the page read "prospector: fail -> skip: prospector: tree
unreadable (host/transient) — tests/unit". Prospector was not broken. In
logs/health/repo-health.jsonl the 17:22:48Z tick flagged ALL THREE repos in the
same tick (signalengine skip/transient, lux fail/transient, prospector
skip/transient), and prospector's tests/unit is readable now, so the verdict was
momentary.

Only prospector paged, for two reasons:
  1. _is_flake granted grace only when the PREVIOUS tick carried no host-fault
     flag, and ignored WHICH fault it was. Prospector's previous tick (15:38:07Z)
     was a TIMEOUT, 1h44m earlier — a different fault — so it ate the grace.
  2. TRANSIENT_PATTERNS' own comment says a host fault "hits every repo in the
     same tick", but nothing acted on that, so an estate-wide event was still
     graded per repo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SRC = Path.home() / ".hermes" / "scripts" / "repo-health-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def rhc(tmp_path, monkeypatch):
    """A fresh module whose history + queue are confined to tmp_path."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    mod = _load()
    mod.LOG_DIR = tmp_path / "health"
    mod.HISTORY_FILE = mod.LOG_DIR / "repo-health.jsonl"
    mod.QUEUE = tmp_path / "no-such-queue.py"
    return mod


# (a) the exact 17:22:48Z tick — three repos flagged at once, none page.
def test_estate_wide_tick_pages_nothing(rhc):
    results = {
        "signalengine": {"state": "skip", "transient": True, "summary": "s"},
        "lux": {"state": "fail", "transient": True, "summary": "l"},
        "prospector": {"state": "skip", "transient": True, "summary": "p"},
    }
    prev = {
        "signalengine": {"state": "pass"},
        "lux": {"state": "pass"},
        "prospector": {"state": "fail", "timeout": True},
    }
    assert rhc._flaky_set(results, prev) == {"signalengine", "lux", "prospector"}


# (b) grace is per KIND: a previous timeout does not consume the grace for a
# current unreadable-tree fault.
def test_previous_timeout_does_not_eat_transient_grace(rhc):
    assert rhc._is_flake(
        "prospector",
        {"state": "skip", "transient": True},
        {"prospector": {"state": "fail", "timeout": True}},
    ) is True


# (c) a LONE repo repeating the SAME fault still pages — suppression is not blanket.
def test_lone_repeating_fault_still_pages(rhc):
    results = {
        "prospector": {"state": "skip", "transient": True, "summary": "p"},
        "lux": {"state": "pass"},
        "signalengine": {"state": "pass"},
    }
    prev = {"prospector": {"state": "skip", "transient": True}}
    assert rhc._flaky_set(results, prev) == set()
