"""Proof for the repo-health HOST-FAULT fix (2026-08-18T13:22:06Z).

The failure this pins: the page read "lux: pass -> fail: lux: FAIL — Node.js v26.3.0".
That line carries no information, and lux was not broken. In
logs/health/repo-health.jsonl the 13:22:06Z tick broke ALL THREE repos at once;
signalengine and prospector both said "runner error [Errno 1] Operation not
permitted" on ~/Documents/code. Nine seconds later, at 13:22:15Z, the next tick
said "lux: tests pass". So the host broke, not the repo. Under that same EPERM
vitest's Node process died on its fatal-uncaught-exception path, whose last line
is the version footer — and the old summary took the last line blindly.

These tests prove the fix in both directions:
  - the summary names the FAULT (EPERM), never the Node footer
  - a host fault grades transient -> first occurrence silent, pages 'warn' after
  - a genuine assertion failure is untouched: no transient flag, pages 'crit' first time
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
    """A fresh module whose history + queue are confined to tmp_path."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    mod = _load()
    log_dir = tmp_path / "health"
    monkeypatch.setattr(mod, "LOG_DIR", log_dir)
    monkeypatch.setattr(mod, "HISTORY_FILE", log_dir / "repo-health.jsonl")
    monkeypatch.setattr(mod, "QUEUE", tmp_path / "no-such-queue.py")
    return mod


# The real shape of the 13:22:06Z output: vitest under an EPERM on ~/Documents/code.
# tail keeps the crash dump; the informative line is buried above the stack frames.
NODE_CRASH_OUT = """\
node:internal/fs/utils:355
    throw err;
    ^

Error: EPERM: operation not permitted, open '/Users/x/Documents/code/lux/node_modules/.vite/deps'
    at Object.openSync (node:fs:596:3)
    at readFileSync (node:fs:464:35)
    at loadConfigFromFile (file:///Users/x/Documents/code/lux/node_modules/vite/dist/node/chunks/dep.js:1)
  {
  errno: -1,
  code: 'EPERM',
  syscall: 'open'
}

Node.js v26.3.0"""

REAL_FAIL_OUT = """\
 FAIL  src/score.test.ts > composite score keeps KILL documents
AssertionError: expected 0 to be 42

 Test Files  1 failed (8)
      Tests  3 failed | 78 passed (81)"""

PASS = {"state": "pass", "summary": "lux: tests pass"}
TRANSIENT = {"state": "fail", "transient": True,
             "summary": "lux: FAIL (host/transient) — Error: EPERM: operation not permitted"}
REAL_FAIL = {"state": "fail", "summary": "lux: FAIL — Tests  3 failed | 78 passed (81)"}


def _arrange(mod, monkeypatch, prev_lux, new_lux):
    """Seed one previous tick, stub this tick's result, capture submits."""
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:06Z",
                    "results": {"lux": prev_lux}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"lux": {"path": "/unused"}})
    monkeypatch.setattr(mod, "check_repo", lambda n, i: (n, dict(new_lux)))
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))
    return sent


def _grade(mod, monkeypatch, tmp_path, out, code):
    """Grade one repo whose test command produced `out` and exited `code`."""
    repo = tmp_path / "lux"
    repo.mkdir(parents=True, exist_ok=True)
    def fake_run(cmd, cwd, timeout):
        if cmd.startswith("git status"):
            return "", 0
        return out, code
    monkeypatch.setattr(mod, "run", fake_run)
    return mod.check_repo("lux", {"path": str(repo), "requires": [],
                                  "test_cmd": "(stubbed)"})[1]


# (a) the summary must name the fault, not the version footer


def test_summary_line_skips_the_node_footer(rhc):
    """The exact regression: 'Node.js v26.3.0' must never be the summary."""
    line = rhc._summary_line(NODE_CRASH_OUT)
    assert "Node.js v" not in line, line
    assert "EPERM: operation not permitted" in line, line
    assert len(line) <= 80, line


def test_summary_line_skips_stack_frames_and_punctuation(rhc):
    """Frames ('    at ...') and brace-only lines carry no verdict either."""
    assert not rhc._summary_line(NODE_CRASH_OUT).lstrip().startswith("at ")
    assert rhc._summary_line("real line\n}\n\n   \n") == "real line"


def test_summary_line_falls_back_when_nothing_is_informative(rhc):
    assert rhc._summary_line("Node.js v26.3.0") == "Node.js v26.3.0"
    assert rhc._summary_line("") == "test failed"
    assert rhc._summary_line("   \n\n") == "test failed"


def test_summary_line_keeps_a_normal_failure_line(rhc):
    assert rhc._summary_line(REAL_FAIL_OUT) == "Tests  3 failed | 78 passed (81)"


# (b) a host fault grades fail+transient with an informative summary


def test_host_fault_grades_transient(rhc, monkeypatch, tmp_path):
    res = _grade(rhc, monkeypatch, tmp_path, NODE_CRASH_OUT, 1)
    assert res["state"] == "fail", res
    assert res["transient"] is True, res
    assert "host/transient" in res["summary"], res
    assert "EPERM" in res["summary"], res
    assert "Node.js v" not in res["summary"], res


def test_genuine_failure_is_not_transient(rhc, monkeypatch, tmp_path):
    res = _grade(rhc, monkeypatch, tmp_path, REAL_FAIL_OUT, 1)
    assert res["state"] == "fail", res
    assert "transient" not in res, res
    assert "3 failed" in res["summary"], res


# (c) _is_flake grants exactly one tick of grace


def test_is_flake_first_transient_true_second_false(rhc):
    assert rhc._is_flake("lux", TRANSIENT, {"lux": PASS}) is True
    assert rhc._is_flake("lux", TRANSIENT, {}) is True
    assert rhc._is_flake("lux", TRANSIENT, {"lux": TRANSIENT}) is False
    assert rhc._is_flake("lux", REAL_FAIL, {"lux": PASS}) is False


def test_first_host_fault_is_silent(rhc, monkeypatch, capsys):
    """The 13:22:06Z tick itself: zero pages."""
    sent = _arrange(rhc, monkeypatch, PASS, TRANSIENT)
    assert rhc.main() == 0
    assert sent == [], sent
    out = capsys.readouterr().out
    assert "0 pass, 0 fail" in out, out


def test_second_consecutive_host_fault_pages_warn(rhc, monkeypatch):
    """Teeth: it is only ONE tick of grace, and it pages 'warn', not 'crit'."""
    sent = _arrange(rhc, monkeypatch, TRANSIENT, TRANSIENT)
    assert rhc.main() == 0
    assert len(sent) == 1, sent
    msg, severity = sent[0]
    assert severity == "warn", sent
    assert "host/transient" in msg, sent


# (d) a genuine assertion failure still pages 'crit' on the FIRST occurrence


def test_real_failure_still_pages_crit_first_time(rhc, monkeypatch):
    sent = _arrange(rhc, monkeypatch, PASS, REAL_FAIL)
    assert rhc.main() == 0
    assert "crit" in [s for _, s in sent], sent
    assert any("3 failed" in m for m, _ in sent), sent


def test_runner_oserror_is_marked_transient(rhc, monkeypatch, capsys):
    """An OSError escaping check_repo is the filesystem failing, not the repo."""
    mod = rhc
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:06Z",
                    "results": {"lux": PASS}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"lux": {"path": "/unused"}})

    def boom(n, i):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(mod, "check_repo", boom)
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, sev: sent.append((msg, sev)))
    assert mod.main() == 0
    assert sent == [], sent
    last = json.loads(mod.HISTORY_FILE.read_text().splitlines()[-1])
    assert last["results"]["lux"]["transient"] is True, last
