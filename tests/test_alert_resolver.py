"""alert-resolver — probe-verified resolution, never message-absence (Fire 4-LF)."""
import subprocess
import sys

from conftest import SCRIPTS, load

ar = load("alert-resolver.py")


def test_open_set_collapses_pid_variants():
    """Two PID-varying messages for the same condition = ONE open fingerprint."""
    entries = [
        {"type": "CRON_ERROR", "message": "CRON_ERROR: job errored: code 1 PID 111", "status": "open"},
        {"type": "CRON_ERROR", "message": "CRON_ERROR: job errored: code 1 PID 222", "status": "open"},
    ]
    assert len(ar.open_fingerprints(entries)) == 1


def test_resolution_closes_fingerprint():
    entries = [
        {"type": "GIT_DIRTY", "message": "GIT_DIRTY: 99 files", "status": "open"},
        {"type": "GIT_DIRTY", "message": "GIT_DIRTY: 99 files", "status": "resolved"},
    ]
    assert ar.open_fingerprints(entries) == {}


def test_job_name_extraction():
    assert ar._job_name_from("CRON_ERROR: idle-continuous-learning errored: x") == "idle-continuous-learning"


def test_every_alert_type_has_a_verifier():
    for t in ("CRON_ERROR", "GATEWAY_DOWN", "GIT_DIRTY", "DISK_HIGH", "IDLE_ERROR"):
        assert t in ar.VERIFIERS


def test_self_test_subprocess_passes():
    r = subprocess.run([sys.executable, str(SCRIPTS / "alert-resolver.py"), "--self-test"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
