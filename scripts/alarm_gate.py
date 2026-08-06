#!/usr/bin/env python3
"""alarm_gate — decide whether an alarm state is worth telling the founder AGAIN.

Why this exists
---------------
cron/scheduler.py:1409-1412 defines the no_agent contract: "non-zero exit / timeout
-> delivered as an error alert". The exit CODE alone triggers delivery — a script
cannot opt out by staying silent on stdout. So any watchdog that exits non-zero
while a fault persists delivers a Telegram every single time it runs. At hourly
cadence that is 24 identical messages a day about a fault the founder already knows
about, which is precisely how otto-dispatch came to sit disabled for 46 days behind
a muted alert chain.

Suppressing repeats is therefore not a nicety; without it the alarm destroys itself.

The contract
------------
Alarms fire on STATE CHANGE, not on state. Given a fingerprint of the current
failing set, this returns one of:

  REPORT     the failing set differs from what was last reported (or nothing has
             been reported yet) -> escalate
  RECOVERED  the failing set is now empty and the last report was not -> tell the
             founder once that it cleared, then go quiet
  REASSERT   unchanged, but --reassert-after has elapsed -> re-state it so a
             long-running fault is not forgotten entirely
  SUPPRESS   unchanged and re-assert is not due -> say nothing

An empty fingerprint means healthy. The caller decides exit codes; this only
decides whether to speak.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE = HOME / "state" / "alarm_gate.json"


def _load() -> dict:
    try:
        with open(STATE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    """Atomic write — a torn gate file would re-alarm or, worse, suppress forever."""
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE)
    except OSError:
        # Losing the gate state costs a duplicate alert; failing the caller costs
        # the alert entirely. Prefer the duplicate.
        pass


def decide(key: str, fingerprint: str, reassert_after: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    data = _load()
    prev = data.get(key) or {}
    prev_fp = prev.get("fingerprint", "")
    last_reported = float(prev.get("last_reported") or 0)

    healthy = not fingerprint

    if healthy:
        if not prev_fp:
            # Healthy and was healthy — nothing to say, and nothing to record.
            return "SUPPRESS"
        decision = "RECOVERED"
    elif fingerprint != prev_fp:
        decision = "REPORT"
    elif now - last_reported >= reassert_after:
        decision = "REASSERT"
    else:
        return "SUPPRESS"

    data[key] = {
        "fingerprint": fingerprint,
        "last_reported": now,
        "first_seen": prev.get("first_seen") if fingerprint == prev_fp else now,
        "last_decision": decision,
    }
    _save(data)
    return decision


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--key", required=True, help="alarm identity, e.g. 'reliability'")
    ap.add_argument(
        "--fingerprint",
        default="",
        help="stable digest of the current failing set; empty means healthy",
    )
    ap.add_argument(
        "--reassert-after",
        type=float,
        default=86400.0,
        help="seconds before an unchanged fault is re-stated (default 24h)",
    )
    args = ap.parse_args()
    print(decide(args.key, args.fingerprint.strip(), args.reassert_after))
    return 0


if __name__ == "__main__":
    sys.exit(main())
