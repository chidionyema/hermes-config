"""Shared fixtures/loaders for the Hermes self-improvement test suite.

These tests are the receipt for Item 4 (47 untested scripts had 0 tests). They cover
the CRITICAL substrate: fingerprinting, alert-resolver, relay queue, watchdog grading,
dropped-ball watchdog, dispatcher, and memory. Pure logic is unit-tested in-process;
CLI scripts are integration-tested via subprocess in an isolated HERMES_HOME so a test
can never touch the live ledger/queue/alert log.
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
HERE = Path(__file__).resolve().parent


def script_style_tests() -> list[str]:
    """Names of test_*.py files here that define no top-level test function.

    Half the files named `test_*.py` in this directory are not pytest tests. They are
    standalone scripts: they do their work at module scope, print
    `Results: N passed, M failed`, and end in `sys.exit(...)`. Pytest IMPORTS every file
    it collects, so collecting one RUNS it — and any failure there is a collection error
    that aborts the whole session.

    That is what had been happening, silently. `bash tests/run.sh` reported
    `INTERNALERROR ... no tests ran` and exited 3, so this repo had no working gate at
    all. The last file standing was `test_product_readiness.py`, which shells out to
    `db_health.py --check` at import time and hit its own 15-second timeout.

    So pytest collects only the real pytest files, and run.sh runs these directly, as
    scripts. Neither kind is skipped, and both verdicts count toward the gate's exit code.

    The split is COMPUTED, never listed by hand — a hand-maintained list in a file like
    this goes stale silently, which is the failure mode this whole comment is about.
    """
    out = []
    for path in sorted(HERE.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue  # a file pytest cannot parse is pytest's to report, not ours
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
            for node in tree.body
        ):
            out.append(path.name)
    return out


collect_ignore = script_style_tests()


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
