"""watchdog — exit-code grading on real invariants (hidden-restart-loop fix)."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from conftest import SCRIPTS, load


def _jobs(path, last_status="ok"):
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "demo-job", "enabled": True, "state": "scheduled",
         "last_status": last_status, "last_run_at": "2026-06-18T20:00:00Z", "last_error": "boom"}
    ]}))


def _run(path, env, **extra):
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=False)
    e = {**env, "HERMES_FAKE_GATEWAY": "up", **{k: str(v) for k, v in extra.items()}}
    return subprocess.run([sys.executable, str(SCRIPTS / "watchdog.py")],
                          capture_output=True, text=True, env=e).returncode


def test_healthy_daemon_up_exits_0(hermes_env):
    path, env = hermes_env
    _jobs(path)
    assert _run(path, env) == 0


def test_daemon_down_exits_2_restart_loop(hermes_env):
    path, env = hermes_env
    _jobs(path)
    # Restart-loop grading is debounced: it fires only once the daemon is NOT
    # sustained-alive across SUSTAIN_N known runs (so a single momentary down — a
    # launchd restart blip — can't false-alarm). Drive SUSTAIN_N down readings and
    # assert it grades healthy until the streak completes, then exits 2.
    rc1 = _run(path, env, HERMES_FAKE_GATEWAY="down", HERMES_WD_SUSTAIN_N=2)
    rc2 = _run(path, env, HERMES_FAKE_GATEWAY="down", HERMES_WD_SUSTAIN_N=2)
    assert rc1 == 0 and rc2 == 2  # debounced first run, restart loop on the N-th


def test_open_alert_breaches_after_k_runs(hermes_env):
    path, env = hermes_env
    _jobs(path)
    # DISK_HIGH at 0% threshold persists (self-healer can't clear it)
    rc1 = _run(path, env, HERMES_DISK_PCT_MAX=0, HERMES_WD_BREACH_K=2)
    rc2 = _run(path, env, HERMES_DISK_PCT_MAX=0, HERMES_WD_BREACH_K=2)
    assert rc1 == 0 and rc2 == 1  # tracked first run, breach on the K-th


def _wd(path):
    """Load watchdog.py bound to an isolated HERMES_HOME (read at import time)."""
    os.environ["HERMES_HOME"] = str(path)
    (path / "cron").mkdir(exist_ok=True)
    return load("watchdog.py")


def _on_schedule():
    """A job the scheduler is not late for, whatever the host's uptime happens to be.

    2026-08-20: this file pinned `last_run_at` to a literal date in the past and asserted an
    exact alert COUNT. check_cron_health grades staleness against `time.time()` clamped by
    `_awake_since()`, so once this laptop had been awake longer than `cron_stale_hours` (26)
    a second alert appeared — `CRON_STALE: demo-job not run in 35h` — and the assertion
    `len(alerts) == 1` failed. Nothing was broken; the machine had simply been on for a day
    and a half. It refused the Hermes deploy. A fixture that reads the wall clock without
    saying so is a test that passes on a rebooted laptop and fails on a running one.

    `next_run_at` in the future takes the schedule-aware branch (watchdog.py:212), which
    cannot emit CRON_STALE, so the count assertions below measure the error grading alone.
    """
    now = datetime.now(timezone.utc)
    return {
        "last_run_at": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "next_run_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }


def test_cron_timeout_is_not_a_cron_error(hermes_env):
    # A bounded-runner TIMEOUT under post-wake overload self-resolves — it must NOT raise a
    # CRON_ERROR (the false health-watchdog failure root-caused 2026-06-21).
    path, _ = hermes_env
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "repo-health-check", "enabled": True, "state": "scheduled",
         "last_status": "error", **_on_schedule(),
         "last_error": "Script timed out after 120s: /x/scripts/repo-health-check.py"}
    ]}))
    assert _wd(path).check_cron_health() == []


def test_genuine_cron_error_still_alerts(hermes_env):
    # A real nonzero exit is NOT suppressed — the guard is timeout-class only.
    path, _ = hermes_env
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "demo-job", "enabled": True, "state": "scheduled",
         "last_status": "error", **_on_schedule(),
         "last_error": "Script exited with code 1"}
    ]}))
    alerts = _wd(path).check_cron_health()
    assert len(alerts) == 1 and alerts[0].startswith("CRON_ERROR: demo-job")


def test_a_stale_job_is_still_reported(hermes_env):
    """_on_schedule must not be a blanket muzzle: a genuinely overdue job still alerts."""
    path, _ = hermes_env
    overdue = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "demo-job", "enabled": True, "state": "scheduled",
         "last_status": "ok", "last_run_at": overdue, "next_run_at": overdue,
         "last_error": ""}
    ]}))
    alerts = _wd(path).check_cron_health()
    assert len(alerts) == 1 and alerts[0].startswith("CRON_STALE: demo-job")


def test_git_status_timeout_kill_is_not_a_git_error(hermes_env, monkeypatch):
    # run() returns code < 0 when our bounded runner kills git on timeout or the OS signals it
    # (SIGHUP on sleep/wake). That's transient load-noise, not a broken repo — no GIT_ERROR.
    path, _ = hermes_env
    wd = _wd(path)
    monkeypatch.setattr(wd, "run", lambda *a, **k: ("(timeout)", -1))
    assert wd.check_git_health() == []
    monkeypatch.setattr(wd, "run", lambda *a, **k: ("fatal: not a git repo", 128))
    assert wd.check_git_health() == ["GIT_ERROR: git status failed code 128"]
