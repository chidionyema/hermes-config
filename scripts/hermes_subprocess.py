#!/usr/bin/env python3
"""hermes_subprocess.run_bounded — the ONE safe way to run a child with a deadline.

THE BUG THIS KILLS (the orphan class)
  `subprocess.run(cmd, shell=True, timeout=T)` on timeout sends SIGKILL to the
  `/bin/sh` PARENT only. Its children (pytest, git, npm) are reparented to init and
  KEEP RUNNING — orphans. Under load they pile up (64 orphans -> load 95 -> the whole
  estate times out). Every script that rolled its own run()/_sh() reintroduced this.

THE FIX
  Start the child as its OWN process-group leader (start_new_session=True). On timeout,
  os.killpg the WHOLE group, then reap. No grandchild survives the deadline.

  This module is the substrate every script must route subprocess calls through — so
  the next autonomously-generated script cannot be an orphan factory. It is the only
  fix that survives self-modification.

API
  run_bounded(cmd, timeout=15) -> Bounded(stdout, stderr, returncode, timed_out)
      returncode == -9 and timed_out == True on deadline. Never raises on timeout.
  sh(cmd, timeout=15) -> (stdout, returncode)
      back-compat shim matching the old run()/_sh() contract; ('(timeout)', -1) on deadline.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass


@dataclass
class Bounded:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_bounded(cmd, timeout: int = 15, text: bool = True, env=None, cwd=None) -> Bounded:
    """Run cmd with a hard deadline; on timeout kill the WHOLE process group.

    cmd: list[str] (preferred — no shell) or str (shell=True). The process-group kill
    is what makes either form orphan-safe.
    """
    shell = isinstance(cmd, str)
    try:
        p = subprocess.Popen(
            cmd, shell=shell, text=text,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,   # child leads its own process group => killable as a unit
            env=env, cwd=cwd,
        )
    except (OSError, ValueError) as e:
        return Bounded("", f"spawn failed: {e}", -1, False)

    try:
        out, err = p.communicate(timeout=timeout)
        return Bounded((out or "").strip(), (err or "").strip(), p.returncode, False)
    except subprocess.TimeoutExpired:
        # Kill the entire group (parent + every grandchild) — THE orphan fix.
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return Bounded((out or "").strip(), (err or "").strip(), -9, True)


def sh(cmd, timeout: int = 15):
    """Back-compat shim: returns (stdout, returncode) like the old helpers, and
    ('(timeout)', -1) on deadline so existing callers behave identically — but with
    the orphan-safe process-group kill underneath."""
    r = run_bounded(cmd, timeout=timeout)
    if r.timed_out:
        return "(timeout)", -1
    return r.stdout, r.returncode


if __name__ == "__main__":
    # Self-proof: a child that spawns a grandchild and hangs must leave NO survivor.
    import sys
    r = run_bounded(
        [sys.executable, "-c",
         "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)"],
        timeout=1,
    )
    print(f"timed_out={r.timed_out} rc={r.returncode} (expected timed_out=True rc=-9)")
