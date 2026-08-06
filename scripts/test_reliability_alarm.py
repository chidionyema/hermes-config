"""Tests for the reliability alarm: alarm_gate, missed-run intake, WARMING.

Run: python3 -m pytest ~/.hermes/scripts/test_reliability_alarm.py -q

EVERY test must redirect the module's state paths. alarm_gate.STATE,
reliability_report.MISSED and capability_audit.HOME are all bound AT IMPORT from
HERMES_HOME, so monkeypatching the environment variable inside a test is a no-op
and the test silently reads and WRITES production. The 2026-08-05 session shipped
two probes with exactly that bug: they passed against the live estate for the
wrong reason. Patch the module attribute, never the env var.

The suppression logic is the dangerous half of this file: a gate that wrongly
suppresses fails SILENTLY and forever. Every branch below is therefore asserted
in both directions — it speaks when it must, and only when it must.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alarm_gate  # noqa: E402
import capability_audit as ca  # noqa: E402
import reliability_report as rr  # noqa: E402


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """Point alarm_gate at a scratch state file (module attribute, not env)."""
    monkeypatch.setattr(alarm_gate, "STATE", tmp_path / "alarm_gate.json")
    return alarm_gate


# --------------------------------------------------------------------------
# alarm_gate — fires on change, stays quiet otherwise
# --------------------------------------------------------------------------

def test_first_fault_is_reported(gate):
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0) == "REPORT"


def test_identical_fault_is_suppressed(gate):
    gate.decide("k", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("k", "fp-aaa", 86400.0, now=1100.0) == "SUPPRESS"


def test_changed_fault_set_reports_again(gate):
    """The mutation that matters: if this ever returns SUPPRESS, a NEW failure
    arriving while an old one is open is swallowed permanently."""
    gate.decide("k", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("k", "fp-bbb", 86400.0, now=1100.0) == "REPORT"


def test_unchanged_fault_is_restated_after_the_reassert_window(gate):
    gate.decide("k", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0 + 86399) == "SUPPRESS"
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0 + 86400) == "REASSERT"


def test_reassert_resets_the_clock(gate):
    """Without last_reported being rewritten on REASSERT, every subsequent run
    stays past the window and the daily re-assert becomes hourly again."""
    gate.decide("k", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0 + 86400) == "REASSERT"
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0 + 86500) == "SUPPRESS"


def test_recovery_is_announced_once_then_silent(gate):
    gate.decide("k", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("k", "", 86400.0, now=1100.0) == "RECOVERED"
    assert gate.decide("k", "", 86400.0, now=1200.0) == "SUPPRESS"


def test_healthy_from_the_start_never_speaks(gate):
    assert gate.decide("k", "", 86400.0, now=1000.0) == "SUPPRESS"


def test_keys_are_independent(gate):
    gate.decide("a", "fp-aaa", 86400.0, now=1000.0)
    assert gate.decide("b", "fp-aaa", 86400.0, now=1000.0) == "REPORT"


def test_unreadable_state_file_still_reports(gate, tmp_path):
    """A corrupt gate file must fail toward speaking, not toward silence."""
    (tmp_path / "alarm_gate.json").write_text("{ not json")
    assert gate.decide("k", "fp-aaa", 86400.0, now=1000.0) == "REPORT"


# --------------------------------------------------------------------------
# fingerprint — must ignore churn, must not ignore identity
# --------------------------------------------------------------------------

def test_fingerprint_ignores_changing_detail_text():
    """Details carry ages ('held 3.2d') that change every run. If they fed the
    fingerprint, every run would look like a new fault and the gate would pass
    everything through — gated in appearance, hourly in fact."""
    a = rr.fingerprint([("latch", "estate_paused", "LATCHED: held 3.2d")])
    b = rr.fingerprint([("latch", "estate_paused", "LATCHED: held 3.9d")])
    assert a == b


def test_fingerprint_changes_when_verdict_changes():
    a = rr.fingerprint([("capability", "x", "STALE: foo")])
    b = rr.fingerprint([("capability", "x", "DARK: foo")])
    assert a != b


def test_fingerprint_changes_when_a_new_fault_appears():
    a = rr.fingerprint([("capability", "x", "DARK: foo")])
    b = rr.fingerprint([("capability", "x", "DARK: foo"),
                        ("capability", "y", "DARK: bar")])
    assert a != b


def test_fingerprint_is_order_independent():
    a = rr.fingerprint([("capability", "x", "DARK: f"), ("capability", "y", "DARK: g")])
    b = rr.fingerprint([("capability", "y", "DARK: g"), ("capability", "x", "DARK: f")])
    assert a == b


def test_healthy_fingerprint_is_empty():
    assert rr.fingerprint([]) == ""


# --------------------------------------------------------------------------
# missed-run intake — the signal that had no reader
# --------------------------------------------------------------------------

def _write_missed(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_skipped_runs_are_collected(tmp_path, monkeypatch):
    now = time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600))
    p = tmp_path / "missed_runs.jsonl"
    _write_missed(p, [{"at": at, "job": "otto-dispatch", "action": "skipped"}])
    monkeypatch.setattr(rr, "MISSED", p)
    got = rr.recent_missed(now)
    assert [r["job"] for r in got] == ["otto-dispatch"]


def test_ran_late_is_not_an_alarm(tmp_path, monkeypatch):
    """catch_up ran the job late — the work happened. Alarming on it would bury
    the real signal (a genuinely dropped run) in noise."""
    now = time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600))
    p = tmp_path / "missed_runs.jsonl"
    _write_missed(p, [{"at": at, "job": "queue-curator", "action": "ran_late"}])
    monkeypatch.setattr(rr, "MISSED", p)
    assert rr.recent_missed(now) == []


def test_old_misses_fall_out_of_the_window(tmp_path, monkeypatch):
    now = time.time()
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 40 * 3600))
    p = tmp_path / "missed_runs.jsonl"
    _write_missed(p, [{"at": old, "job": "otto-dispatch", "action": "skipped"}])
    monkeypatch.setattr(rr, "MISSED", p)
    assert rr.recent_missed(now) == []


def test_missing_and_corrupt_lines_do_not_break_intake(tmp_path, monkeypatch):
    now = time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 60))
    p = tmp_path / "missed_runs.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "{ not json\n"
        + json.dumps({"at": "nonsense", "job": "x", "action": "skipped"}) + "\n"
        + json.dumps({"at": at, "job": "good", "action": "skipped"}) + "\n"
    )
    monkeypatch.setattr(rr, "MISSED", p)
    assert [r["job"] for r in rr.recent_missed(now)] == ["good"]

    monkeypatch.setattr(rr, "MISSED", tmp_path / "does-not-exist.jsonl")
    assert rr.recent_missed(now) == []


# --------------------------------------------------------------------------
# WARMING — "not yet watched" is not the same claim as "not producing"
# --------------------------------------------------------------------------

@pytest.fixture
def fake_estate(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "HOME", str(tmp_path))
    monkeypatch.setattr(ca, "_RECEIPTS_SINCE", "unset")  # cache is process-global
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _receipt_cap(period_s=86400):
    return {"id": "c", "what": "", "period_s": period_s,
            "observable": {"kind": "receipt", "script": "x.sh", "requires": "exit0"}}


def test_receipt_capability_is_warming_while_instrumentation_is_young(fake_estate):
    now = time.time()
    (fake_estate / "state" / "capability_receipts.jsonl").write_text(
        json.dumps({"script": "other.sh", "ended_at": now - 600, "exit_code": 0}) + "\n"
    )
    rows = ca.audit_capabilities({"capabilities": [_receipt_cap()]}, now)
    assert rows[0]["verdict"] == "WARMING"


def test_receipt_capability_is_dark_once_a_full_period_has_been_watched(fake_estate):
    """The mutation that matters in the other direction: WARMING must EXPIRE.
    A grace that never ends is just a permanently green light."""
    now = time.time()
    (fake_estate / "state" / "capability_receipts.jsonl").write_text(
        json.dumps({"script": "other.sh", "ended_at": now - 86400 * 3, "exit_code": 0}) + "\n"
    )
    rows = ca.audit_capabilities({"capabilities": [_receipt_cap()]}, now)
    assert rows[0]["verdict"] == "DARK"


def test_warming_is_not_a_failure_but_dark_is():
    assert "WARMING" not in ca.FAIL_VERDICTS
    assert "DARK" in ca.FAIL_VERDICTS


def test_file_observable_never_warms(fake_estate):
    """A file observable reads history that predates the probe, so an absent file
    is real evidence of absence. Only receipts have a blind spot to forgive."""
    now = time.time()
    (fake_estate / "state" / "capability_receipts.jsonl").write_text(
        json.dumps({"script": "other.sh", "ended_at": now - 60, "exit_code": 0}) + "\n"
    )
    cap = {"id": "f", "what": "", "period_s": 86400,
           "observable": {"kind": "file", "path": "reports/never-existed-*.md"}}
    rows = ca.audit_capabilities({"capabilities": [cap]}, now)
    assert rows[0]["verdict"] == "DARK"


# --------------------------------------------------------------------------
# cron_never_ran — the grace window that read a field nobody writes
# --------------------------------------------------------------------------

_NEVER_RAN_LATCH = {"id": "never_fired_cron_jobs", "what": "", "kind": "cron_never_ran",
                    "max_age_s": 86400, "auto_release": False}


def _jobs_file(tmp_path, monkeypatch, jobs):
    p = tmp_path / "jobs.json"
    p.write_text(json.dumps({"jobs": jobs}))
    monkeypatch.setattr(ca, "JOBS", str(p))


def _iso(offset_s):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + offset_s))


def test_a_job_created_moments_ago_is_not_yet_silent(tmp_path, monkeypatch):
    """The regression that proved itself on installation: registering delivery-canary
    latched it as 'never fired' within the minute, because the grace window read
    `registered_at` — a field NOTHING in the estate writes. A probe that escalates its
    own install teaches the founder that its escalations mean nothing."""
    _jobs_file(tmp_path, monkeypatch,
               [{"name": "brand-new", "enabled": True, "last_run_at": None,
                 "created_at": _iso(-60)}])
    rows = ca.audit_latches({"latches": [_NEVER_RAN_LATCH]}, time.time())
    assert rows[0]["breached"] == []


def test_a_job_that_has_been_silent_past_the_window_still_latches(tmp_path, monkeypatch):
    """The other direction — the grace must expire, or the latch is decorative."""
    _jobs_file(tmp_path, monkeypatch,
               [{"name": "stuck", "enabled": True, "last_run_at": None,
                 "created_at": _iso(-3 * 86400)}])
    rows = ca.audit_latches({"latches": [_NEVER_RAN_LATCH]}, time.time())
    assert [n for n, _ in rows[0]["breached"]] == ["stuck"]


def test_registered_at_still_wins_when_present(tmp_path, monkeypatch):
    """created_at is the fallback, not a replacement: a job re-registered recently
    should get its grace from the re-registration, not from its original creation."""
    _jobs_file(tmp_path, monkeypatch,
               [{"name": "re-registered", "enabled": True, "last_run_at": None,
                 "created_at": _iso(-30 * 86400), "registered_at": time.time() - 60}])
    rows = ca.audit_latches({"latches": [_NEVER_RAN_LATCH]}, time.time())
    assert rows[0]["breached"] == []


def test_a_job_that_has_run_is_never_latched(tmp_path, monkeypatch):
    _jobs_file(tmp_path, monkeypatch,
               [{"name": "healthy", "enabled": True, "last_run_at": _iso(-600),
                 "created_at": _iso(-30 * 86400)}])
    rows = ca.audit_latches({"latches": [_NEVER_RAN_LATCH]}, time.time())
    assert rows[0]["breached"] == []


def test_producing_capability_is_unaffected_by_the_warming_branch(fake_estate):
    now = time.time()
    (fake_estate / "state" / "capability_receipts.jsonl").write_text(
        json.dumps({"script": "x.sh", "ended_at": now - 60, "exit_code": 0}) + "\n"
    )
    rows = ca.audit_capabilities({"capabilities": [_receipt_cap()]}, now)
    assert rows[0]["verdict"] == "PRODUCING"


# --------------------------------------------------------------------------
# main() exit code — a watchdog reporting a fault is a watchdog WORKING
# --------------------------------------------------------------------------

def _run_main(monkeypatch, tmp_path, failing, argv=("reliability_report",)):
    """Drive main() with every module-bound path redirected (see file docstring)."""
    monkeypatch.setattr(alarm_gate, "STATE", tmp_path / "alarm_gate.json")
    monkeypatch.setattr(rr, "STATUS", tmp_path / "reliability_status.json")
    monkeypatch.setattr(rr, "collect", lambda now: (failing, {"probe": "stub"}))
    monkeypatch.setattr(sys, "argv", list(argv))
    return rr.main()


_FAULT = [("capability", "uncommitted_watch", "DARK: no receipt in 4.4h")]


def test_a_reported_fault_exits_zero_but_still_speaks(monkeypatch, tmp_path, capsys):
    """The alarm rides on stdout, not on the exit code.

    cron/scheduler.py delivers a no_agent job's non-empty stdout verbatim when
    the script SUCCEEDS. Exiting 1 delivered the same text a second way (wrapped
    in "Script exited with code 1", scheduler.py:1068-1074) AND recorded
    last_status="error" in cron/jobs.json — from which ops-monitor re-reported
    "1 cron jobs failing: reliability-watchdog" every ~31 min indefinitely.
    alarm_gate cannot suppress that repeat: a different process emits it, by
    reading state, not by calling decide().
    """
    code = _run_main(monkeypatch, tmp_path, _FAULT)
    out = capsys.readouterr().out
    assert code == 0, "a fault the watchdog is REPORTING is not the watchdog failing"
    # Non-vacuous: if the fix had silenced the alarm instead of the exit code,
    # this is what would catch it.
    assert "uncommitted_watch" in out, "the alarm stopped speaking — silence is the worse bug"


def test_the_suppressed_repeat_says_nothing_and_still_exits_zero(monkeypatch, tmp_path, capsys):
    assert _run_main(monkeypatch, tmp_path, _FAULT) == 0
    capsys.readouterr()
    code = _run_main(monkeypatch, tmp_path, _FAULT)
    assert code == 0
    assert capsys.readouterr().out.strip() == "", "gated repeat must be silent on stdout too"


def test_healthy_run_is_silent_and_exits_zero(monkeypatch, tmp_path, capsys):
    code = _run_main(monkeypatch, tmp_path, [])
    assert code == 0
    assert capsys.readouterr().out.strip() == ""


def test_force_still_exits_nonzero_for_a_human_shell(monkeypatch, tmp_path, capsys):
    """--force is a separate contract: a person running `if reliability_report
    --force` in a shell wants a truthy failure. Only the cron path changed."""
    code = _run_main(monkeypatch, tmp_path, _FAULT, argv=("reliability_report", "--force"))
    assert code == 1
    assert "uncommitted_watch" in capsys.readouterr().out


def test_force_on_a_healthy_estate_exits_zero(monkeypatch, tmp_path, capsys):
    assert _run_main(monkeypatch, tmp_path, [], argv=("reliability_report", "--force")) == 0
    assert "all proven" in capsys.readouterr().out
