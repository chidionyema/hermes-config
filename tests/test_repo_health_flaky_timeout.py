"""Proof for the repo-health flaky-timeout fix (2026-08-18).

The failure this pins: at 2026-08-18T12:49:03Z lux timed out once and paged twice
("lux: pass -> fail: lux: TIMEOUT (> 60s)" plus a bare "lux: TIMEOUT (> 60s)").
repo-health.jsonl shows 8 'pass' ticks before it and 5 after it, and two clean
runs of the same suite measured 8.78s and 9.77s against a 60s budget. So the tick
was a slow one under concurrent-CPU load, not a regression.

check_repo already documented the intent — a transient timeout "self-heals on the
next run" — but nothing acted on it. These tests prove the fix has teeth in BOTH
directions:
  - first consecutive timeout   -> silent (no submit, any_fail False)
  - second consecutive timeout  -> pages once, severity 'warn'
  - real (non-timeout) failure  -> still pages 'crit', never suppressed
"""

from __future__ import annotations

import importlib.util
import json
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
    """A fresh module whose history + queue are confined to tmp_path.

    HERMES_HOME is redirected too, so nothing can reach the real relay queue.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    mod = _load()
    log_dir = tmp_path / "health"
    monkeypatch.setattr(mod, "LOG_DIR", log_dir)
    monkeypatch.setattr(mod, "HISTORY_FILE", log_dir / "repo-health.jsonl")
    monkeypatch.setattr(mod, "QUEUE", tmp_path / "no-such-queue.py")
    return mod


def _arrange(mod, monkeypatch, prev_lux, new_lux):
    """Seed one previous tick, stub this tick's result, capture submits."""
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T12:47:00Z",
                    "results": {"lux": prev_lux}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"lux": {"path": "/unused"}})
    monkeypatch.setattr(mod, "check_repo", lambda n, i: (n, dict(new_lux)))
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))
    return sent


PASS = {"state": "pass", "summary": "lux: tests pass"}
TIMEOUT = {"state": "fail", "timeout": True, "summary": "lux: TIMEOUT (> 60s)"}
REAL_FAIL = {"state": "fail", "summary": "lux: FAIL — 3 failed"}


def test_first_consecutive_timeout_is_silent(rhc, monkeypatch, capsys):
    """The exact tick that produced this task must page zero times."""
    sent = _arrange(rhc, monkeypatch, PASS, TIMEOUT)
    assert rhc.main() == 0
    assert sent == [], sent
    out = capsys.readouterr().out
    # any_fail must be False: the count line grades the suppressed repo as 0 fail.
    assert "0 pass, 0 fail" in out, out
    # Suppressed, not hidden — the cron log still shows it.
    assert "~ lux: host fault, not paged (grace or estate-wide tick)" in out, out


def test_timeout_is_still_recorded_in_history(rhc, monkeypatch):
    """Suppression is about paging only. The tick must persist, or a second
    consecutive timeout could never be detected."""
    _arrange(rhc, monkeypatch, PASS, TIMEOUT)
    rhc.main()
    last = json.loads(rhc.HISTORY_FILE.read_text().splitlines()[-1])
    assert last["results"]["lux"]["state"] == "fail", last
    assert last["results"]["lux"]["timeout"] is True, last


def test_second_consecutive_timeout_pages_warn(rhc, monkeypatch):
    """Teeth: a repeat timeout is a real regression and still escalates."""
    sent = _arrange(rhc, monkeypatch, TIMEOUT, TIMEOUT)
    assert rhc.main() == 0
    assert len(sent) == 1, sent
    msg, severity = sent[0]
    assert severity == "warn", sent
    assert "TIMEOUT" in msg, sent


def test_real_failure_is_never_suppressed(rhc, monkeypatch):
    """Teeth: a non-timeout test failure after a pass still pages 'crit'."""
    sent = _arrange(rhc, monkeypatch, PASS, REAL_FAIL)
    assert rhc.main() == 0
    severities = sorted(s for _, s in sent)
    assert "crit" in severities, sent
    assert any("3 failed" in m for m, _ in sent), sent


def test_flake_suppression_does_not_leak_into_any_fail(rhc, monkeypatch, capsys):
    """A flaky timeout with NO state change must not set any_fail.

    prev is a real (non-timeout) fail, so the state is unchanged and `changes` is
    empty — this isolates any_fail from the changes gate.
    """
    sent = _arrange(rhc, monkeypatch, REAL_FAIL, TIMEOUT)
    assert rhc.main() == 0
    assert sent == [], sent
    out = capsys.readouterr().out
    assert "0 pass, 0 fail" in out, out
    assert "Δ" not in out, out


def test_is_flake_unit():
    """The predicate itself: only a timeout, and only the first in a row."""
    mod = _load()
    assert mod._is_flake("lux", TIMEOUT, {"lux": PASS}) is True
    assert mod._is_flake("lux", TIMEOUT, {}) is True            # no history yet
    assert mod._is_flake("lux", TIMEOUT, {"lux": TIMEOUT}) is False
    assert mod._is_flake("lux", REAL_FAIL, {"lux": PASS}) is False
    assert mod._is_flake("lux", PASS, {"lux": TIMEOUT}) is False
