"""Proof for the repo-health host-fault (transient) fix (2026-08-18).

The failure this pins: the page "failure: lux: pass -> fail: lux: FAIL — Node.js
v26.3.0". That is not a lux regression. In ~/.hermes/logs/health/repo-health.jsonl
the 2026-08-18T13:22:06Z tick broke ALL THREE repos at once, and two of them named
the real fault:

  signalengine: runner error [Errno 1] Operation not permitted: '.../signalengine/tests'
  lux:          FAIL — Node.js v26.3.0
  prospector:   runner error [Errno 1] Operation not permitted: '.../prospector/tests/unit'

The very next tick, 9 seconds later at 13:22:15Z, reads "lux: tests pass". So the
host broke, not the repo. Under that same EPERM vitest's Node process died on its
fatal-uncaught-exception path, whose LAST line is the version footer — and
check_repo built its summary from `test_out.split("\\n")[-1]`, so the one line that
named the fault was discarded and the footer was paged instead.

Two defects, two sets of teeth here:
  - _summary_line picks the last INFORMATIVE line, not the last line.
  - a TRANSIENT_PATTERNS hit is graded like a timeout: recorded, silent on the
    first consecutive tick, paged 'warn' on the second — and a genuine assertion
    failure is still paged 'crit' on the very first tick.
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


# The real shape of a Node fatal-uncaught-exception dump under the 13:22:06Z EPERM.
NODE_EPERM_DUMP = """\
node:internal/fs/utils:355
    throw err;
    ^

Error: EPERM: operation not permitted, open '/Users/chidionyema/Documents/code/lux/node_modules/.vite/x'
    at Object.openSync (node:fs:596:3)
    at readFileSync (node:fs:464:35)
    at loadConfigFromFile (file:///.../vite/dist/node/chunks/dep.js:12345:20)

Node.js v26.3.0"""

REAL_ASSERTION_DUMP = """\
 FAIL  src/format.test.ts > formatDate > pads the month
AssertionError: expected '2026-8-18' to be '2026-08-18'

 Test Files  1 failed (8)
      Tests  1 failed | 80 passed (81)"""


# ---------------------------------------------------------------- (a) summary line

def test_summary_line_skips_the_node_version_footer():
    """The exact defect: the footer carries no information, the EPERM line does."""
    mod = _load()
    got = mod._summary_line(NODE_EPERM_DUMP)
    assert "EPERM: operation not permitted" in got, got
    assert not got.startswith("Node.js v"), got


def test_summary_line_skips_stack_frames_and_blanks():
    mod = _load()
    out = "Error: EMFILE: too many open files\n    at Object.openSync (node:fs:596:3)\n\n\nNode.js v26.3.0"
    assert mod._summary_line(out) == "Error: EMFILE: too many open files"


def test_summary_line_still_returns_the_real_last_line_normally():
    """No regression on the ordinary case the old code handled."""
    mod = _load()
    assert mod._summary_line(REAL_ASSERTION_DUMP) == "Tests  1 failed | 80 passed (81)"


def test_summary_line_truncates_to_80_and_degrades_safely():
    mod = _load()
    assert len(mod._summary_line("x" * 500)) == 80
    assert mod._summary_line("") == "test failed"
    assert mod._summary_line("   \n\n") == "test failed"
    # Punctuation-only tail is skipped, not paged.
    assert mod._summary_line("Error: ENFILE hit\n^^^^^\n---") == "Error: ENFILE hit"


# ------------------------------------------------- (b) check_repo flags transient

def _stub_run(mod, monkeypatch, test_out, code):
    """Stub run(): git status is clean, the test command returns the fixture."""
    def fake(cmd, cwd, timeout):
        if cmd.startswith("git status"):
            return "", 0
        return test_out, code
    monkeypatch.setattr(mod, "run", fake)


def _info(tmp_path):
    """Minimal repo config: a real, complete path so check_repo reaches run()."""
    return {"path": str(tmp_path), "test_cmd": "fake-test-command"}


def test_host_fault_yields_transient_true(rhc, monkeypatch, tmp_path):
    """A non-zero run whose output names a host fault is not a repo regression."""
    _stub_run(rhc, monkeypatch, NODE_EPERM_DUMP, 1)
    name, res = rhc.check_repo("lux", _info(tmp_path))
    assert res["state"] == "fail", res
    assert res["transient"] is True, res
    assert "host/transient" in res["summary"], res
    assert "EPERM: operation not permitted" in res["summary"], res
    assert "Node.js v26.3.0" not in res["summary"], res


def test_operation_not_permitted_wording_also_matches(rhc, monkeypatch, tmp_path):
    """The literal string the 13:22:06Z tick logged for the other two repos."""
    _stub_run(rhc, monkeypatch,
              "[Errno 1] Operation not permitted: '/Users/x/Documents/code/prospector/tests/unit'", 1)
    _, res = rhc.check_repo("prospector", _info(tmp_path))
    assert res.get("transient") is True, res


def test_real_failure_is_not_flagged_transient(rhc, monkeypatch, tmp_path):
    """Teeth: an assertion failure must keep the plain fail dict."""
    _stub_run(rhc, monkeypatch, REAL_ASSERTION_DUMP, 1)
    _, res = rhc.check_repo("lux", _info(tmp_path))
    assert res["state"] == "fail", res
    assert "transient" not in res, res
    assert "1 failed | 80 passed" in res["summary"], res


# --------------------------------------------------------------- (c) _is_flake

PASS = {"state": "pass", "summary": "lux: tests pass"}
TRANSIENT = {"state": "fail", "transient": True,
             "summary": "lux: FAIL (host/transient) — Error: EPERM: operation not permitted"}
TIMEOUT = {"state": "fail", "timeout": True, "summary": "lux: TIMEOUT (> 60s)"}
REAL_FAIL = {"state": "fail", "summary": "lux: FAIL — 1 failed | 80 passed (81)"}


def test_is_flake_first_transient_true_second_false():
    mod = _load()
    assert mod._is_flake("lux", TRANSIENT, {"lux": PASS}) is True
    assert mod._is_flake("lux", TRANSIENT, {}) is True              # no history yet
    assert mod._is_flake("lux", TRANSIENT, {"lux": TRANSIENT}) is False
    # The two transient kinds are one class: a timeout then a host fault is still
    # two consecutive bad ticks, and pages.
    assert mod._is_flake("lux", TRANSIENT, {"lux": TIMEOUT}) is False
    assert mod._is_flake("lux", TIMEOUT, {"lux": TRANSIENT}) is False
    # The old timeout contract is untouched.
    assert mod._is_flake("lux", TIMEOUT, {"lux": PASS}) is True
    assert mod._is_flake("lux", REAL_FAIL, {"lux": PASS}) is False


# ------------------------------------------------ end-to-end paging through main()

def _arrange(mod, monkeypatch, prev_lux, new_lux):
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:00Z",
                    "results": {"lux": prev_lux}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"lux": {"path": "/unused"}})
    monkeypatch.setattr(mod, "check_repo", lambda n, i: (n, dict(new_lux)))
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))
    return sent


def test_first_host_fault_pages_nothing(rhc, monkeypatch, capsys):
    """The exact 13:22:06Z tick: pass -> host fault must page zero times."""
    sent = _arrange(rhc, monkeypatch, PASS, TRANSIENT)
    assert rhc.main() == 0
    assert sent == [], sent
    assert "0 pass, 0 fail" in capsys.readouterr().out


def test_host_fault_is_still_recorded_in_history(rhc, monkeypatch):
    """Suppression is paging only — a second consecutive tick needs this line."""
    _arrange(rhc, monkeypatch, PASS, TRANSIENT)
    rhc.main()
    last = json.loads(rhc.HISTORY_FILE.read_text().splitlines()[-1])
    assert last["results"]["lux"]["transient"] is True, last


def test_second_consecutive_host_fault_pages_warn(rhc, monkeypatch):
    """Teeth: a repeat is a real problem — paged, but 'warn', not 'crit'."""
    sent = _arrange(rhc, monkeypatch, TRANSIENT, TRANSIENT)
    assert rhc.main() == 0
    assert len(sent) == 1, sent
    assert sent[0][1] == "warn", sent


# ------------------------------------------------------------------- (d) teeth

def test_genuine_failure_still_pages_crit_on_first_occurrence(rhc, monkeypatch):
    """The whole point of the fix is that it does NOT mute real regressions."""
    sent = _arrange(rhc, monkeypatch, PASS, REAL_FAIL)
    assert rhc.main() == 0
    severities = sorted(s for _, s in sent)
    assert "crit" in severities, sent
    assert any("1 failed | 80 passed" in m for m, _ in sent), sent


def test_oserror_from_the_runner_is_marked_transient(rhc, monkeypatch, capsys):
    """The 'runner error [Errno 1] Operation not permitted' path in main()."""
    mod = rhc
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:00Z",
                    "results": {"signalengine": PASS}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"signalengine": {"path": "/unused"}})

    def boom(n, i):
        raise PermissionError(1, "Operation not permitted",
                              "/Users/x/Documents/code/signalengine/tests")
    monkeypatch.setattr(mod, "check_repo", boom)
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))

    assert mod.main() == 0
    assert sent == [], sent
    last = json.loads(mod.HISTORY_FILE.read_text().splitlines()[-1])
    assert last["results"]["signalengine"]["transient"] is True, last
    assert "0 pass, 0 fail" in capsys.readouterr().out


def test_two_ticks_through_a_real_failing_subprocess(rhc, monkeypatch, tmp_path):
    """No stubs on run(): a REAL process emits the 13:22:06Z dump and exits 1.

    This is the end-to-end shape of the incident — pipefail, `| tail -25`, the
    Node fatal-exception dump, the pass->fail transition — proving tick 1 is
    silent and tick 2 pages 'warn'.
    """
    mod = rhc
    boom = tmp_path / "boom.sh"
    boom.write_text(
        "#!/bin/bash\ncat <<'EOF'\n" + NODE_EPERM_DUMP + "\nEOF\nexit 1\n")
    boom.chmod(0o755)

    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:00Z",
                    "results": {"lux": PASS}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {
        "lux": {"path": str(tmp_path), "test_cmd": f"{boom} 2>&1 | tail -25"}})
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))

    assert mod.main() == 0
    tick1 = json.loads(mod.HISTORY_FILE.read_text().splitlines()[-1])["results"]["lux"]
    assert sent == [], f"first host-fault tick must not page, got {sent}"
    assert tick1["state"] == "fail" and tick1["transient"] is True, tick1
    assert "EPERM: operation not permitted" in tick1["summary"], tick1
    assert "Node.js v26.3.0" not in tick1["summary"], tick1

    # Tick 2: state is fail->fail, so there is no transition line — the repeat
    # host fault pages exactly once, and as 'warn' rather than 'crit'.
    assert mod.main() == 0
    assert len(sent) == 1, sent
    assert sent[0][1] == "warn", sent
    assert "host/transient" in sent[0][0], sent


def test_non_oserror_runner_error_still_pages(rhc, monkeypatch):
    """Teeth: a real bug in check_repo must not be laundered as a host fault."""
    mod = rhc
    mod.LOG_DIR.mkdir(parents=True, exist_ok=True)
    mod.HISTORY_FILE.write_text(
        json.dumps({"timestamp": "2026-08-18T13:20:00Z",
                    "results": {"lux": PASS}}) + "\n")
    monkeypatch.setattr(mod, "REPOS", {"lux": {"path": "/unused"}})

    def boom(n, i):
        raise ValueError("bad config")
    monkeypatch.setattr(mod, "check_repo", boom)
    sent = []
    monkeypatch.setattr(mod, "submit", lambda msg, severity: sent.append((msg, severity)))

    assert mod.main() == 0
    assert any(s == "crit" for _, s in sent), sent
