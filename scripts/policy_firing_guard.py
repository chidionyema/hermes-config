#!/usr/bin/env python3
"""Regression guard for the policy enforcer wiring (F-NEW-INV-1).

Fires ALERT if no policy firings in 24h — proves the import chain still works.
Run from daily_reflection.py so it surfaces in the morning brief.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")


def main() -> int:
    if not os.path.exists(LOG):
        print(f"⚠️  POLICY GUARD: {LOG} missing — enforcer never ran")
        return 2

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    recent = []
    with open(LOG) as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                elif "+" not in ts and ts:
                    ts = ts + "+00:00"
                t = datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t > cutoff:
                    recent.append(e)
            except Exception:
                continue

    # Also verify the enforcer is actually callable — protects against filename drift
    try:
        sys.path.insert(0, os.path.join(HERMES_HOME, "scripts"))
        import policy_enforcer
        probe = policy_enforcer.check_and_fire_policies(
            "would you like me to check", context="daily-guard-probe"
        )
        enforcer_ok = True
    except Exception as e:
        enforcer_ok = False
        print(f"⚠️  POLICY GUARD: enforcer import failed — {e}")

    if not enforcer_ok:
        return 3

    if not recent:
        print(
            f"⚠️  POLICY GUARD: 0 firings in last 24h "
            f"(since {cutoff.isoformat()}). "
            f"Enforcer callable but silent — check triggers/route_query thresholds."
        )
        return 1

    print(f"✓ POLICY GUARD: {len(recent)} firings in last 24h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
