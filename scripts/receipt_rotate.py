#!/usr/bin/env python3
"""Bound the growth of state/capability_receipts.jsonl without breaking its semantics.

WHY. The receipts ledger is append-only and capability_audit.py reads ALL of it on every
run (capability_audit.py:160-186, and again at :275 for receipts_since). Measured
2026-08-07, two days after cron instrumentation landed: 1,783 records / 590KB, i.e. about
890 records and 295KB per day, on a trajectory of ~108MB/year re-read hourly. Bringing the
launchd jobs into the same layer roughly doubles the rate, so the ledger needed a bound
before it got one more writer, not after.

THE TRAP THIS AVOIDS. Naive truncation silently breaks the audit's own false-alarm
defence. receipts_since() (capability_audit.py:260-290) reads the OLDEST record to learn
when instrumentation began, and uses it to score a capability UNPROVEN rather than DARK
when its job simply has not come round yet. Drop the old records and that epoch jumps to
"a moment ago", so every daily and weekly capability looks freshly-instrumented forever
and a genuinely dead job is reported as merely young. The docstring there records what
that costs: 11 of 17 DARK rows false on the first audit, re-sent 24x/day. So rotation
leaves behind an __origin__ marker carrying the TRUE first-instrumentation epoch. It
matches no capability (every reader filters on rec["script"] first, :174) so it is inert
for scoring, and it keeps receipts_since() returning exactly what it returned before.

RETENTION IS BY AGE, NOT BY LINE COUNT. A count-based window would evict a daily job's
only receipt as soon as a 5-minute job filled the buffer, and that job would read as
"no run recorded yet" while running perfectly. 30 days covers every registered period,
the longest being the weekly delivery canary at 604800s.

CONCURRENCY. Rotation renames and rewrites, while other processes append with O_APPEND.
A concurrent append during the rename can land in the archived file. The window is
sub-millisecond and it is bounded to one record, which cannot change a verdict: verdicts
key on the LATEST receipt per script, and every job writes again within its own period.
Rotation is deliberately rare (a stat, then only above the threshold) to keep it that way.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
RETAIN_DAYS = 30
ORIGIN_SCRIPT = "__origin__"


def maybe_rotate(path: str | os.PathLike, *, max_bytes: int = MAX_BYTES,
                 retain_days: int = RETAIN_DAYS, now: float | None = None) -> str | None:
    """Rotate `path` if it exceeds `max_bytes`. Returns the archive path, or None.

    Never raises: this runs inside the receipt-writing path, and observation must not be
    able to break the thing being observed.
    """
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size <= max_bytes:
            return None
    except OSError:
        return None

    now = time.time() if now is None else now
    cutoff = now - retain_days * 86400

    try:
        oldest: float | None = None
        keep: list[str] = []
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn line is dropped here rather than carried forever
                t = rec.get("ended_at")
                if isinstance(t, (int, float)):
                    # The existing marker counts: rotating twice must not walk the epoch
                    # forward one window at a time.
                    if oldest is None or t < oldest:
                        oldest = t
                    if t < cutoff and rec.get("script") != ORIGIN_SCRIPT:
                        continue
                elif rec.get("script") == ORIGIN_SCRIPT:
                    continue
                else:
                    continue  # undateable record: unusable to every reader, so drop it
                if rec.get("script") == ORIGIN_SCRIPT:
                    continue  # re-emitted below, exactly once, from `oldest`
                keep.append(line)

        if oldest is None:
            return None

        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        archive = p.with_name(f"{p.name}.{stamp}.gz")
        with open(p, "rb") as src, gzip.open(archive, "wb") as dst:
            shutil.copyfileobj(src, dst)

        marker = json.dumps({
            "script": ORIGIN_SCRIPT,
            "ended_at": oldest,
            "note": (f"Instrumentation origin, preserved across rotation on {stamp}. "
                     f"Full history: {archive.name}. Matches no capability; exists only "
                     f"so capability_audit.receipts_since() keeps returning the true "
                     f"first-instrumentation epoch."),
        })

        tmp = p.with_name(p.name + ".rotating")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(marker + "\n")
            for line in keep:
                fh.write(line + "\n")
        os.replace(tmp, p)  # atomic: readers see the old file or the new one, never neither
        return str(archive)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/.hermes/state/capability_receipts.jsonl")
    # Manual invocation rotates on demand; the automatic path only fires above MAX_BYTES.
    forced = 0 if "--force" in sys.argv else MAX_BYTES
    out = maybe_rotate(target, max_bytes=forced)
    print(f"rotated -> {out}" if out else "no rotation needed")
