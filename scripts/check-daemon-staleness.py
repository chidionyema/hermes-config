#!/usr/bin/env python3
"""Is each long-lived daemon running the code that is on disk?

`verify_estate.sh` carried a section headed "gateway process matches on-disk hermes-agent
(staleness)" that compared nothing at all: it checked the pid was alive and the tree was committed,
and called that a staleness check. So on 2026-08-17 the coordinator had been up since 16 Aug 20:04
hosting `cron/scheduler.py` in-process, while that file had been changed and committed at 18:09 the
next day. Every scheduler fix made in those 25 hours was inert, and nothing in the estate said so.
The failure looked like a bug that had already been fixed still happening.

This is the comparison. A daemon is STALE when the code it hosts changed after it started.

Read-only. Exit 0 = every daemon is current, 1 = at least one is stale, 2 = could not measure.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime

AGENT = os.path.expanduser("~/.hermes/hermes-agent")

#: label -> what it hosts. Every one of these runs hermes-agent python in-process, so a change to
#: that tree does not reach them without a restart.
DAEMONS = {
    "ai.hermes.coordinator": "cron scheduler + coordinator loop",
    "ai.hermes.gateway": "telegram gateway",
    "ai.hermes.otto-server": "otto server",
}

RESTART = "launchctl kickstart -k gui/$(id -u)/{label}"


def _sh(*cmd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _pid(label: str) -> int | None:
    rc, out = _sh("launchctl", "print", f"gui/{os.getuid()}/{label}")
    if rc != 0:
        return None
    m = re.search(r"^\s*pid\s*=\s*(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def _started(pid: int) -> float | None:
    """Process start time as an epoch. `ps -o lstart=` is the only reliable source on macOS."""
    rc, out = _sh("ps", "-o", "lstart=", "-p", str(pid))
    if rc != 0 or not out.strip():
        return None
    try:
        return datetime.strptime(out.strip(), "%a %d %b %H:%M:%S %Y").timestamp()
    except ValueError:
        try:  # some ps builds pad the day differently
            return datetime.strptime(" ".join(out.split()), "%a %b %d %H:%M:%S %Y").timestamp()
        except ValueError:
            return None


def _code_changed_at() -> tuple[float, str] | None:
    """Newest of (last commit, newest tracked .py mtime).

    Both halves matter: a committed fix that nobody restarted for, and an edit sitting in the
    working tree that the daemon also is not running.
    """
    rc, out = _sh("git", "-C", AGENT, "log", "-1", "--format=%ct")
    if rc != 0 or not out.strip():
        return None
    newest, what = float(out.strip()), "last commit"

    rc, out = _sh("git", "-C", AGENT, "ls-files", "-z", "*.py")
    if rc == 0:
        for rel in out.split("\0"):
            if not rel:
                continue
            try:
                mt = os.path.getmtime(os.path.join(AGENT, rel))
            except OSError:
                continue
            if mt > newest:
                newest, what = mt, f"edit to {rel}"
    return newest, what


def main() -> int:
    code = _code_changed_at()
    if code is None:
        print("  🟡 cannot read hermes-agent git state — staleness unmeasured")
        return 2
    changed_at, what = code

    stale = 0
    for label, hosts in DAEMONS.items():
        pid = _pid(label)
        if pid is None:
            print(f"  🟡 {label}: not running (nothing to compare)")
            continue
        started = _started(pid)
        if started is None:
            print(f"  🟡 {label}: pid {pid} alive, start time unreadable")
            stale = max(stale, 2)
            continue
        age_h = (changed_at - started) / 3600.0
        if changed_at > started:
            stale = 1
            print(
                f"  ❌ {label}: pid {pid} started {age_h:.1f}h BEFORE the {what} — "
                f"running stale {hosts}. Restart: {RESTART.format(label=label)}"
            )
        else:
            print(f"  ✅ {label}: pid {pid} started after the {what} — running current code")
    return stale


if __name__ == "__main__":
    raise SystemExit(main())
