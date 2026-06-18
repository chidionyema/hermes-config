"""Shared fixtures/loaders for the Hermes self-improvement test suite.

These tests are the receipt for Item 4 (47 untested scripts had 0 tests). They cover
the CRITICAL substrate: fingerprinting, alert-resolver, relay queue, watchdog grading,
dropped-ball watchdog, dispatcher, and memory. Pure logic is unit-tested in-process;
CLI scripts are integration-tested via subprocess in an isolated HERMES_HOME so a test
can never touch the live ledger/queue/alert log.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(modfile: str):
    """Import a (possibly hyphenated) script from scripts/ as a module."""
    name = modfile.replace("-", "_").removesuffix(".py")
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / modfile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hermes_env(tmp_path):
    """An isolated HERMES_HOME with the real scripts/ symlinked in and an empty cron.

    Returns (path, env) where env is a dict ready to pass to subprocess.run.
    """
    (tmp_path / "cron").mkdir()
    (tmp_path / "logs" / "alerts").mkdir(parents=True)
    (tmp_path / "queue").mkdir()
    (tmp_path / "scripts").symlink_to(SCRIPTS)
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}
    return tmp_path, env
