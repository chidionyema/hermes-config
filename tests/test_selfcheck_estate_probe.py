"""The estate probe's route into the hourly self-check.

`scripts/verify_estate.sh` is the estate's live state. Until 2026-08-19 nothing ran it on a
schedule, so it only spoke when a human typed it. It now runs inside
`scripts/hermes_selfcheck.py`, which launchd already runs hourly with `--alert`.

Two properties decide whether that wiring is worth anything, and both are asserted here:

  one row per fault -> `_alert_on_change` compares the SET OF FAILING NAMES. A single
      composite row would page once on the first estate fault and then stay silent however
      much worse the estate got, because the set could never change again.

  a stable name  -> the probe prints a pid and an elapsed-hours figure that move on every
      run. Unmasked, an unchanged estate would look like a new failure set every hour, and
      the hourly page is exactly the noise this alerting is supposed to end.

The third case is the one a measuring instrument fails at: a probe that hangs or cannot run
must register a FAIL, never a pass.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path.home() / ".hermes" / "scripts" / "hermes_selfcheck.py"

# Trimmed from a real run on 2026-08-19. The pid and the hours are the volatile fields.
PROBE_OUTPUT = """\
LAUNCHD  daemons vs the tree
  ❌ ai.hermes.coordinator: pid 62935 started 3.0h BEFORE the last commit — running stale code.
  ✅ ai.hermes.otto-server current
FLY  apps this estate depends on
  ❌ prospector-ci has 1 of 3 machines not started (8e4530a7712248=stopped)
VERDICT: ❌ DEGRADED — at least one ❌ above. Fix before claiming ready.
"""

PROBE_OUTPUT_LATER = PROBE_OUTPUT.replace("pid 62935", "pid 71104").replace("3.0h", "9.5h")


def _load(monkeypatch, probe_result):
    """Import hermes_selfcheck with the verify_estate.sh call replaced.

    Every check in that file runs at module scope, so importing it IS running it. Only the
    subprocess boundary is faked; the grading code under test is the code that ships.
    `probe_result` is either a CompletedProcess or an exception instance to raise.
    """
    real = subprocess.run

    def fake(cmd, *a, **kw):
        argv = [str(c) for c in (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
        if any("verify_estate.sh" in part for part in argv):
            if isinstance(probe_result, BaseException):
                raise probe_result
            return probe_result
        # Every other check is stubbed out too, so this test never touches the network or
        # the live estate. Their rows are ignored; only "estate" rows are asserted on.
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("hermes_selfcheck_undertest", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(subprocess, "run", real)
    return mod


def _estate_rows(mod):
    return [r for r in mod.RESULTS if r["name"].startswith("estate")]


def test_each_estate_fault_is_its_own_result_row(monkeypatch):
    mod = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, PROBE_OUTPUT, ""))
    rows = _estate_rows(mod)

    assert len(rows) == 2, [r["name"] for r in rows]
    assert all(r["ok"] is False for r in rows)
    joined = " ".join(r["name"] for r in rows)
    assert "ai.hermes.coordinator" in joined
    assert "prospector-ci" in joined

    # The VERDICT line summarises the faults above it. Counting it would add a row that
    # appears and clears in lockstep with every other estate row and says nothing.
    assert not any("DEGRADED" in r["name"] for r in rows), joined


def test_fault_names_are_stable_when_only_pid_and_age_move(monkeypatch):
    """The same estate, an hour later, must not read as a new failure set."""
    first = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, PROBE_OUTPUT, ""))
    later = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, PROBE_OUTPUT_LATER, ""))

    names_a = sorted(r["name"] for r in _estate_rows(first))
    names_b = sorted(r["name"] for r in _estate_rows(later))
    assert names_a == names_b, (names_a, names_b)

    # The masking must not swallow the detail an operator needs, so the raw line is kept.
    assert any("pid 71104" in r["detail"] for r in _estate_rows(later))


def test_an_exit_code_change_IS_a_new_failure(monkeypatch):
    """Masking is narrow on purpose: 78 becoming 2 is news, not noise."""
    out = "  ❌ com.prospector.backup last SCHEDULED run exited 78 (periodic job)\n"
    a = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, out, ""))
    b = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, out.replace("78", "2"), ""))
    assert [r["name"] for r in _estate_rows(a)] != [r["name"] for r in _estate_rows(b)]


def test_a_probe_that_hangs_is_a_failure_not_a_pass(monkeypatch):
    mod = _load(monkeypatch, subprocess.TimeoutExpired(["bash"], 180))
    rows = _estate_rows(mod)
    assert len(rows) == 1, rows
    assert rows[0]["ok"] is False
    assert "did not finish" in rows[0]["detail"]


def test_a_probe_that_cannot_run_is_a_failure_not_a_pass(monkeypatch):
    mod = _load(monkeypatch, OSError("Exec format error"))
    rows = _estate_rows(mod)
    assert len(rows) == 1 and rows[0]["ok"] is False, rows


def test_nonzero_with_nothing_marked_is_reported_not_guessed(monkeypatch):
    """The probe disagreeing with itself is a finding, not a clean bill of health."""
    mod = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 3, "all quiet\n", ""))
    rows = _estate_rows(mod)
    assert len(rows) == 1 and rows[0]["ok"] is False, rows
    assert "exited 3" in rows[0]["detail"]


def test_a_green_estate_registers_one_passing_row(monkeypatch):
    mod = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 0, "VERDICT: OPERATIONAL\n", ""))
    rows = _estate_rows(mod)
    assert len(rows) == 1 and rows[0]["ok"] is True, rows


def test_an_unchanged_failure_set_does_not_page(monkeypatch, tmp_path):
    """The reason one row per fault matters: alerting keys on the name set alone."""
    mod = _load(monkeypatch, subprocess.CompletedProcess(["bash"], 1, PROBE_OUTPUT, ""))
    failed = [r for r in mod.RESULTS if not r["ok"]]

    sent: list[str] = []
    fake = type(sys)("estate_alert")
    fake.send_operator_alert = lambda text, **kw: sent.append(text)
    monkeypatch.setitem(sys.modules, "estate_alert", fake)

    state = tmp_path / "selfcheck.json"
    state.write_text(json.dumps({"failing": [r["name"] for r in failed]}))
    monkeypatch.setattr(mod, "STATE", state)

    mod._alert_on_change(failed)
    assert sent == [], sent

    # ...and a genuinely new fault still gets through.
    mod._alert_on_change(failed + [{"name": "estate: something new", "ok": False,
                                    "detail": "d", "why": "w"}])
    assert len(sent) == 1 and "something new" in sent[0], sent
