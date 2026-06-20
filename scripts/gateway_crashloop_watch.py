#!/usr/bin/env python3
"""gateway_crashloop_watch — detect a crash-looping gateway and alert the operator.

Runs OUTSIDE the gateway (from the coordinator daemon tick) because a crash-looping
gateway cannot watch itself. Counts `gateway.start` events in the recent window from
~/.hermes/logs/gateway-exit-diag.log; too many starts in too little time == a loop.

Built 2026-06-20 after a broken commit crash-looped the gateway silently for minutes.
The preflight (Layer 2) catches import-time breakage; this is the backstop for any
crash that slips past it — the operator gets told instead of guessing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DIAG_LOG = HERMES_HOME / "logs" / "gateway-exit-diag.log"

WINDOW_S = float(os.environ.get("GATEWAY_CRASHLOOP_WINDOW_S", "300"))
THRESHOLD = int(os.environ.get("GATEWAY_CRASHLOOP_THRESHOLD", "4"))


def count_recent_starts(now: float | None = None, window_s: float = WINDOW_S) -> int:
    """Number of gateway.start events within the last window_s seconds."""
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    if not DIAG_LOG.exists():
        return 0
    n = 0
    # read tail-ish: file is small/rotated; full scan is fine
    for line in DIAG_LOG.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or '"gateway.start"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("tag") != "gateway.start":
            continue
        ts = rec.get("ts")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts).timestamp()
        except ValueError:
            continue
        if now - t <= window_s:
            n += 1
    return n


def check(send: bool = True, now: float | None = None) -> dict:
    """Returns {looping, starts, window_s, threshold, alerted}. Safe to call every tick."""
    starts = count_recent_starts(now=now)
    looping = starts >= THRESHOLD
    alerted = False
    if looping and send:
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import estate_alert
            alerted = estate_alert.send_operator_alert(
                f"🔁 Gateway CRASH-LOOP: {starts} restarts in {int(WINDOW_S)}s "
                f"(threshold {THRESHOLD}). Likely a broken import or config — "
                f"check ~/.hermes/logs/gateway.error.log.",
                debounce_key="gateway_crashloop", debounce_s=900)
        except Exception:
            alerted = False
    return {"looping": looping, "starts": starts, "window_s": WINDOW_S,
            "threshold": THRESHOLD, "alerted": alerted}


if __name__ == "__main__":
    import sys
    send = "--no-send" not in sys.argv
    print(json.dumps(check(send=send)))
