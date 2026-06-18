"""hermes_claims — the dropped-ball watchdog: no self-certification survives."""
import subprocess
import sys

from conftest import SCRIPTS

CLAIMS = str(SCRIPTS / "hermes_claims.py")


def claim(env, *args):
    return subprocess.run([sys.executable, CLAIMS, *args], capture_output=True, text=True, env=env)


def test_passing_probe_is_verified(hermes_env):
    _, env = hermes_env
    r = claim(env, "assert", "--claim", "daemon up", "--probe", "true")
    assert r.returncode == 0 and "VERIFIED" in r.stdout


def test_failing_probe_is_dropped_ball(hermes_env):
    _, env = hermes_env
    r = claim(env, "assert", "--claim", "equity cleared", "--probe", "false")
    assert r.returncode == 2 and "DROPPED BALL" in r.stdout


def test_no_probe_is_self_certification(hermes_env):
    _, env = hermes_env
    r = claim(env, "assert", "--claim", "memory saved")
    assert r.returncode == 2 and "DROPPED BALL" in r.stdout


def test_audit_flags_open_balls(hermes_env):
    _, env = hermes_env
    claim(env, "assert", "--claim", "x", "--probe", "false")
    r = claim(env, "audit")
    assert r.returncode == 2
