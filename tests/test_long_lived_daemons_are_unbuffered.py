"""A python daemon whose stdout is a file must run with -u, or its log is empty.

The incident. `coordinator.py` holds 20 print() calls. `coordinator.log` held 0 bytes for 60
days. Nothing was broken about the prints: launchd's StandardOutPath makes stdout a FILE, so
CPython block-buffers it at 8KB, and a daemon that never exits never flushes. The estate's main
autonomous process was therefore unobservable, which is why both defects found on 2026-08-19
had to be dug out of the database by hand.

The failure is worst exactly when it matters most: the log is empty precisely because the
process is still alive, so a crash-loop leaves a trail and a silent malfunction leaves none.

Only LONG-LIVED wrappers are covered. A one-shot script flushes when it exits, so `-u` there is
noise. The list is explicit rather than inferred, because guessing which wrapper never returns
is exactly the kind of implicit rule this file exists to replace.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# wrapper -> the process it execs and never returns from
LONG_LIVED = {
    "coordinator-daemon.sh": "the autonomous coordinator tick loop",
    "cockpit-daemon.sh": "the cockpit uvicorn server",
}

EXEC_PY = re.compile(r"^\s*exec\s+\S*python3?\s+(?P<rest>.*)$", re.M)


def test_every_long_lived_wrapper_execs_python_unbuffered():
    offenders = []
    for name, what in LONG_LIVED.items():
        path = SCRIPTS / name
        assert path.exists(), f"{name} is in LONG_LIVED but not on disk"
        src = path.read_text(encoding="utf-8")
        m = EXEC_PY.search(src)
        if not m:
            offenders.append(f"{name}: no `exec ... python` line found ({what})")
            continue
        if not m.group("rest").lstrip().startswith("-u"):
            offenders.append(f"{name}: execs python without -u, so {what} writes an empty log")
    assert not offenders, "\n  ".join([""] + offenders)
