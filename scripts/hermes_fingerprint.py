#!/usr/bin/env python3
"""Canonical alert/event fingerprinting — single source of truth.

The dropped-ball root cause in alert-resolver.py was that variable parts of a
message (PIDs, embedded timestamps, counts) made the SAME persistent condition
look like a NEW message every run, so the prior alert appeared "absent" and was
false-cleared as resolved/healthy. The real log proved it: 741/813 lines were
"resolved" while idle-learning failed every run, because each message embedded
"=== Idle Learning Run — <changing timestamp> ===".

canonicalize() strips the variable parts so recurring conditions collapse to one
stable fingerprint. Both the relay queue (dedup) and the alert-resolver (lifecycle)
import THIS function, so they can never drift apart.
"""
from __future__ import annotations

import re

# Order matters: timestamps (which contain digits and colons) must be collapsed
# before bare times and bare numbers, and PIDs before bare numbers.
_RE_TS = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_RE_PID = re.compile(r"\b[Pp][Ii][Dd][ =:]+\d+")
_RE_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_RE_HEX = re.compile(r"\b[0-9a-f]{8,}\b")
_RE_NUM = re.compile(r"\b\d+\b")
_RE_WS = re.compile(r"\s+")


def canonicalize(message: str) -> str:
    """Collapse variable parts so a recurring condition has ONE stable fingerprint."""
    s = (message or "").strip()
    s = _RE_TS.sub("<TS>", s)
    s = _RE_PID.sub("PID<N>", s)
    s = _RE_TIME.sub("<TIME>", s)
    s = _RE_HEX.sub("<HEX>", s)
    s = _RE_NUM.sub("<N>", s)
    s = _RE_WS.sub(" ", s)
    return s.strip().lower()


if __name__ == "__main__":
    # Self-test: the real-world false-clear case must collapse to one fingerprint.
    a = ("IDLE_ERROR: idle-learning failed: code 1\nstdout:\n"
         "=== Idle Learning Run — 2026-06-18 16:53 ===")
    b = ("IDLE_ERROR: idle-learning failed: code 1\nstdout:\n"
         "=== Idle Learning Run — 2026-06-18 19:24 ===")
    c = "daemon not running. Started PID 111 at 2026-06-18 19:01"
    d = "daemon not running. Started PID 222 at 2026-06-18 19:06"
    assert canonicalize(a) == canonicalize(b), "timestamp variants must match"
    assert canonicalize(c) == canonicalize(d), "PID variants must match"
    assert canonicalize(a) != canonicalize(c), "distinct conditions must differ"
    print("hermes_fingerprint self-test: PASS")
    print("  fp(idle):", canonicalize(a))
    print("  fp(daemon):", canonicalize(c))
