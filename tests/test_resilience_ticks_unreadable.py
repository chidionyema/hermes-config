#!/usr/bin/env python3
"""Ground-truth test for Phase 0a (idle-learning) rc=1 on 2026-08-18T05:13:51Z.

The failure: rotate_ticks() calls TICKS_PATH.read_text() unguarded at
resilience.py:76. The idle-learning cron runs under the Hermes gateway launchd
job, which has no TCC grant for ~/Documents, so open() returns EPERM even though
stat() succeeds. The traceback escaped main(), resilience.py exited 1, and the
whole idle-learning run was recorded Complete-with-failures.

Every other I/O in rotate_ticks() is try/except-guarded and returns
{"rotated": False, "reason": ...}. Line 76 was the only one that could raise.

This test reproduces the denial without needing TCC: a >500KB file with mode 000.
stat() succeeds, open() raises PermissionError -- the same shape as the TCC EPERM.

Run: python3 ~/.hermes/tests/test_resilience_ticks_unreadable.py
Exit 0 = pass.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HERMES = Path.home() / ".hermes"
spec = importlib.util.spec_from_file_location(
    "resilience", HERMES / "scripts" / "resilience.py"
)
resilience = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resilience)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        failures.append(name)


tmpdir = tempfile.mkdtemp(prefix="hermes-ticks-test-")

# --- Case 1: unreadable ticks file (the TCC/EPERM shape) ---
unreadable = Path(tmpdir) / "ticks.jsonl"
unreadable.write_text("x" * (600 * 1024))  # above the 500KB rotation threshold
os.chmod(unreadable, 0o000)

# Sanity: the denial we are simulating must actually be in force.
try:
    open(unreadable, "rb").read(1)
    print("SKIP: cannot simulate EPERM (running as root?)")
    sys.exit(0)
except PermissionError:
    pass

resilience.TICKS_PATH = unreadable
print("Case 1: ticks.jsonl exists, stat()s, but open() is denied")
try:
    result = resilience.rotate_ticks()
    check("rotate_ticks() does not raise", True)
    check("returns a dict", isinstance(result, dict), f"got {type(result)}")
    check("rotated is False", result.get("rotated") is False, f"got {result}")
    check(
        "reason names the read failure",
        "read" in str(result.get("reason", "")).lower(),
        f"got reason={result.get('reason')!r}",
    )
except Exception as exc:
    check("rotate_ticks() does not raise", False, f"raised {type(exc).__name__}: {exc}")

# --- Case 2: readable file still rotates normally (no regression) ---
readable = Path(tmpdir) / "ticks-ok.jsonl"
readable.write_text('{"ts": "2026-08-18T00:00:00+00:00"}\n' * 20000)  # ~680KB, all recent
resilience.TICKS_PATH = readable
print("Case 2: readable oversize ticks.jsonl still processed")
try:
    result = resilience.rotate_ticks()
    check("returns a dict", isinstance(result, dict), f"got {type(result)}")
    check(
        "no entries older than 30 days -> not rotated, real reason",
        result.get("rotated") is False and "30 days" in str(result.get("reason", "")),
        f"got {result}",
    )
except Exception as exc:
    check("readable path does not raise", False, f"raised {type(exc).__name__}: {exc}")

os.chmod(unreadable, 0o600)
for p in (unreadable, readable):
    p.unlink(missing_ok=True)
os.rmdir(tmpdir)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
sys.exit(0)
