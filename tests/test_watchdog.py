"""watchdog — exit-code grading on real invariants (hidden-restart-loop fix)."""
import json
import subprocess
import sys

from conftest import SCRIPTS


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
