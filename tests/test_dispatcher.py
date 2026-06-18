"""otto-dispatch — silent when nothing is user-worthy (Ball 17 relay step)."""
import json
import subprocess
import sys

from conftest import SCRIPTS

DISPATCH = str(SCRIPTS / "otto-dispatch.py")


def test_silent_and_exit0_when_no_digest(hermes_env):
    _, env = hermes_env  # no pending-digest.json present
    r = subprocess.run([sys.executable, DISPATCH], capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == ""  # nothing forwarded to the user


def test_silent_on_empty_digest(hermes_env):
    path, env = hermes_env
    (path / "queue" / "pending-digest.json").write_text(json.dumps({"items": []}))
    r = subprocess.run([sys.executable, DISPATCH], capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
