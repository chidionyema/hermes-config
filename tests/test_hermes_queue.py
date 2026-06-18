"""hermes_queue — the relay substrate (Fire 0): submit / drain / dedup / resolve."""
import json
import subprocess
import sys

from conftest import SCRIPTS


def q(env, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / "hermes_queue.py"), *args],
                          capture_output=True, text=True, env=env)


def status(env):
    return json.loads(q(env, "status").stdout)


def test_submit_drain_dedup_resolve(hermes_env):
    _, env = hermes_env
    # two re-fires of the SAME condition (PID varies) collapse to one fingerprint
    assert q(env, "submit", "--source", "t", "--message", "daemon down PID 1").returncode == 0
    assert q(env, "submit", "--source", "t", "--message", "daemon down PID 2").returncode == 0
    assert q(env, "drain").returncode == 0
    st = status(env)
    assert st["open_fingerprints"] == 1, st
    assert st["items"][0]["count"] == 2  # both re-fires counted under one fingerprint

    # probe-verified resolution removes it from the open set
    fp = st["items"][0]["fingerprint"]
    assert q(env, "resolve", "--fingerprint", fp).returncode == 0
    assert status(env)["open_fingerprints"] == 0


def test_distinct_conditions_stay_separate(hermes_env):
    _, env = hermes_env
    q(env, "submit", "--source", "a", "--message", "disk high")
    q(env, "submit", "--source", "b", "--message", "gateway down")
    q(env, "drain")
    assert status(env)["open_fingerprints"] == 2
