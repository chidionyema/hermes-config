"""hermes_fingerprint — the canonicalizer that stops false-clears at the source."""
from conftest import load

fp = load("hermes_fingerprint.py")


def test_timestamp_variants_collapse():
    a = "=== Idle Learning Run — 2026-06-18 16:53 === code 1"
    b = "=== Idle Learning Run — 2026-06-18 19:24 === code 1"
    assert fp.canonicalize(a) == fp.canonicalize(b)


def test_pid_variants_collapse():
    assert fp.canonicalize("daemon restarted PID 111") == fp.canonicalize("daemon restarted PID 222")


def test_distinct_conditions_differ():
    assert fp.canonicalize("IDLE_ERROR: x") != fp.canonicalize("daemon not running")


def test_empty_is_stable():
    assert fp.canonicalize("") == ""
    assert fp.canonicalize(None) == ""
