"""dropped-ball-tracker — telemetry probe: counts drops, fires on new ones (Ball 19)."""
import json
import subprocess
import sys
import time

from conftest import SCRIPTS

TRACKER = str(SCRIPTS / "dropped-ball-tracker.py")
QUEUE = str(SCRIPTS / "hermes_queue.py")


def _drop(env, fp, msg="ball"):
    subprocess.run([sys.executable, QUEUE, "submit", "--source", "otto-dropped-ball",
                    "--severity", "error", "--message", msg, "--fingerprint", fp],
                   capture_output=True, env=env)


def test_clean_queue_passes(hermes_env):
    _, env = hermes_env
    r = subprocess.run([sys.executable, TRACKER], capture_output=True, text=True, env=env)
    assert r.returncode == 0


def test_per_class_dedup_and_total(hermes_env):
    _, env = hermes_env
    _drop(env, "dropped-ball-19-proving-ground")
    _drop(env, "dropped-ball-19-proving-ground")          # same class -> dedup, count 2
    _drop(env, "dropped-ball-20-signal-engine")
    subprocess.run([sys.executable, QUEUE, "drain"], capture_output=True, env=env)
    st = json.loads(subprocess.run([sys.executable, QUEUE, "status"],
                                   capture_output=True, text=True, env=env).stdout)
    assert st["dropped_ball_total"] == 3
    assert st["dropped_ball_by_source"] == {"otto-dropped-ball": 3}


def test_new_drop_fires_exit_2(hermes_env):
    _, env = hermes_env
    _drop(env, "dropped-ball-21-x")
    subprocess.run([sys.executable, QUEUE, "drain"], capture_output=True, env=env)
    r = subprocess.run([sys.executable, TRACKER], capture_output=True, text=True,
                       env={**env, "HERMES_DB_WINDOW_MIN": "60"})
    assert r.returncode == 2


def test_window_excludes_old_drops(hermes_env):
    _, env = hermes_env
    _drop(env, "dropped-ball-22-y")
    subprocess.run([sys.executable, QUEUE, "drain"], capture_output=True, env=env)
    # window of 0 minutes => the just-now drop is already outside the window
    r = subprocess.run([sys.executable, TRACKER], capture_output=True, text=True,
                       env={**env, "HERMES_DB_WINDOW_MIN": "0"})
    assert r.returncode == 0
