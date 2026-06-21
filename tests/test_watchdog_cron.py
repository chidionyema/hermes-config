"""watchdog-cron — the cron-boundary wrapper that stops the false 'failure: health-watchdog'.

watchdog.py is exit-code-honest (1=open breach, 2=restart loop); cron reads any nonzero exit
as a JOB failure, so a breach about OTHER jobs falsely marked health-watchdog itself errored.
The wrapper re-maps a graded run -> exit 0 (findings are relayed elsewhere) while a genuine
watchdog crash still surfaces as exit 1. These tests pin that contract.
"""
import json
import subprocess
import sys

from conftest import SCRIPTS


def _jobs(path, last_status="ok"):
    (path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "x", "name": "demo-job", "enabled": True, "state": "scheduled",
         "last_status": last_status, "last_run_at": "2026-06-18T20:00:00Z", "last_error": "boom"}
    ]}))


def _run(script, path, env, **extra):
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=False)
    e = {**env, "HERMES_FAKE_GATEWAY": "up", **{k: str(v) for k, v in extra.items()}}
    return subprocess.run([sys.executable, str(SCRIPTS / script)],
                          capture_output=True, text=True, env=e).returncode


def test_wrapper_healthy_exits_0(hermes_env):
    path, env = hermes_env
    _jobs(path)
    assert _run("watchdog-cron.py", path, env) == 0


def test_wrapper_maps_open_breach_to_0(hermes_env):
    """The exact bug: watchdog.py exits 1 on a sustained breach; the wrapper must exit 0
    so cron never marks health-watchdog itself errored."""
    path, env = hermes_env
    _jobs(path)
    # DISK_HIGH at 0% threshold persists -> breach on the K-th run (K=1 here).
    direct = _run("watchdog.py", path, env, HERMES_DISK_PCT_MAX=0, HERMES_WD_BREACH_K=1)
    wrapped = _run("watchdog-cron.py", path, env, HERMES_DISK_PCT_MAX=0, HERMES_WD_BREACH_K=1)
    assert direct == 1, "watchdog.py must stay exit-code-honest on a breach"
    assert wrapped == 0, "wrapper must absorb the finding so cron sees a successful job"


def test_wrapper_propagates_real_crash(hermes_env, tmp_path):
    """A genuine watchdog operational failure (exception) must still exit nonzero so cron
    flags a blind sensor — the wrapper only absorbs GRADES, never crashes."""
    path, env = hermes_env
    _jobs(path)
    driver = tmp_path / "crash_driver.py"
    driver.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import importlib.util\n"
        "import watchdog\n"
        "watchdog.main = lambda: (_ for _ in ()).throw(RuntimeError('state unwritable'))\n"
        f"spec = importlib.util.spec_from_file_location('wc', {str(SCRIPTS / 'watchdog-cron.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "sys.exit(m.main())\n"
    )
    rc = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True,
                        env={**env, "HERMES_FAKE_GATEWAY": "up"}).returncode
    assert rc == 1
