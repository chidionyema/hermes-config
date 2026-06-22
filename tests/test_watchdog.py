"""watchdog — exit-code grading on real invariants (hidden-restart-loop fix)."""
import json
import os
import subprocess
import sys

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


def test_cron_timeout_is_not_a_cron_error(hermes_env):
    # A bounded-runner TIMEOUT under post-wake overload self-resolves — it must NOT raise a
    # CRON_ERROR (the false health-watchdog failure root-caused 2026-06-21).
    path, _ = hermes_env
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "repo-health-check", "enabled": True, "state": "scheduled",
         "last_status": "error", "last_run_at": "2026-06-21T05:00:00Z",
         "last_error": "Script timed out after 120s: /x/scripts/repo-health-check.py"}
    ]}))
    assert _wd(path).check_cron_health() == []


def test_genuine_cron_error_still_alerts(hermes_env):
    # A real nonzero exit is NOT suppressed — the guard is timeout-class only.
    path, _ = hermes_env
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "demo-job", "enabled": True, "state": "scheduled",
         "last_status": "error", "last_run_at": "2026-06-21T05:00:00Z",
         "last_error": "Script exited with code 1"}
    ]}))
    alerts = _wd(path).check_cron_health()
    assert len(alerts) == 1 and alerts[0].startswith("CRON_ERROR: demo-job")


def test_git_status_timeout_kill_is_not_a_git_error(hermes_env, monkeypatch):
    # run() returns code < 0 when our bounded runner kills git on timeout or the OS signals it
    # (SIGHUP on sleep/wake). That's transient load-noise, not a broken repo — no GIT_ERROR.
    path, _ = hermes_env
    wd = _wd(path)
    monkeypatch.setattr(wd, "run", lambda *a, **k: ("(timeout)", -1))
    assert wd.check_git_health() == []
    monkeypatch.setattr(wd, "run", lambda *a, **k: ("fatal: not a git repo", 128))
    assert wd.check_git_health() == ["GIT_ERROR: git status failed code 128"]
