#!/usr/bin/env python3
"""Re-load estate launchd agents that fell out of launchd. READ-ONLY without --apply.

Why this exists
---------------
On 2026-08-17 eight of twenty-one estate agents were not loaded, at three separate times
(32h, 22.7h and 18.6h earlier). Every one of them was registered in capabilities.json and
every one went DARK correctly, so DETECTION was never the gap. Two things made the
detection useless on its own:

  1. alarm_gate.py fires on STATE CHANGE, not on state. A job that is unloaded and stays
     unloaded alarms ONCE and then goes quiet. An unloaded job cannot alarm about itself
     twice.
  2. Nothing repaired it. The fix was one `launchctl bootstrap` per label, typed by a
     human who happened to look.

This script is the repair half. The watchdog already runs latch_expiry.py --apply before
composing its report; this runs in the same slot and for the same reason, so the report
observes the estate as this run LEAVES it.

What it will and will not touch
-------------------------------
  * Only labels under the estate prefixes below, and only agents in ~/Library/LaunchAgents.
  * NEVER a plist carrying its own `Disabled` key. That key is how the estate declares a
    retirement (ai.hermes.cockpit and ai.hermes.ngrok are retired that way, and
    verify_estate.sh FAILS the estate if ngrok comes back). Reviving one would be the
    watchdog undoing a founder decision.
  * NEVER a label already loaded.

Self-healing must not hide a real fault
---------------------------------------
A job that needs healing every hour is not healthy, it is crash-looping, and a repair that
silently succeeds every hour would look exactly like health. So each heal is appended to
state/launchd_selfheal.jsonl, and a label healed more than MAX_HEALS_PER_DAY times in the
last 24h is REFUSED and reported as a fault instead — which puts it back in front of the
alarm gate as a state change.

Exit codes: 0 = nothing to do, or everything healed. 1 = something is unloaded that this
script refused or failed to heal (so the watchdog's own non-zero exit reaches the founder).
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.join(HOME, ".hermes"))
AGENTS_DIR = os.path.join(HOME, "Library", "LaunchAgents")
# Overridable so a proof run can never write to live state. On 2026-08-17 the very first
# proof of the crash-loop refusal left a real "refused" row in the live ledger, and the
# session-start probe then alarmed on it for a condition that only existed inside the test.
LEDGER = os.environ.get(
    "HERMES_SELFHEAL_LEDGER",
    os.path.join(HERMES_HOME, "state", "launchd_selfheal.jsonl"),
)

ESTATE_PREFIXES = ("ai.hermes.", "com.chidionyema.", "com.prospector.", "com.estate.")
MAX_HEALS_PER_DAY = 4
DAY_S = 86400


def loaded_labels() -> set[str]:
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15).stdout
    labels = set()
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3:
            labels.add(parts[2].strip())
    return labels


def declared_disabled(plist_path: str) -> bool:
    """True when the plist declares its own retirement. Unreadable counts as NOT disabled:
    an unreadable agent is a fault we want surfaced, not silently skipped."""
    try:
        with open(plist_path, "rb") as fh:
            return bool(plistlib.load(fh).get("Disabled"))
    except Exception:
        return False


def recent_heals(label: str, now: float) -> int:
    if not os.path.exists(LEDGER):
        return 0
    n = 0
    with open(LEDGER) as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("label") == label and row.get("action") == "healed" \
                    and now - float(row.get("at", 0)) < DAY_S:
                n += 1
    return n


def record(row: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually bootstrap. Without it, report only and write nothing.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = time.time()
    uid = os.getuid()
    live = loaded_labels()

    report = {"checked": 0, "loaded": 0, "retired": 0,
              "healed": [], "refused": [], "failed": []}

    for fname in sorted(os.listdir(AGENTS_DIR)):
        if not fname.endswith(".plist") or not fname.startswith(ESTATE_PREFIXES):
            continue
        label = fname[:-6]
        path = os.path.join(AGENTS_DIR, fname)
        report["checked"] += 1

        if declared_disabled(path):
            report["retired"] += 1
            continue
        if label in live:
            report["loaded"] += 1
            continue

        n = recent_heals(label, now)
        if n >= MAX_HEALS_PER_DAY:
            # Healing it again would make a crash-loop look like health.
            report["refused"].append({"label": label, "heals_24h": n})
            if args.apply:
                record({"at": now, "label": label, "action": "refused",
                        "reason": f"healed {n}x in 24h — crash-loop, not a missing load"})
            continue

        if not args.apply:
            report["healed"].append({"label": label, "would": True})
            continue

        proc = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", path],
            capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            report["healed"].append({"label": label, "heals_24h_before": n})
            record({"at": now, "label": label, "action": "healed", "prior_heals_24h": n})
        else:
            err = (proc.stderr or proc.stdout).strip()[:200]
            report["failed"].append({"label": label, "rc": proc.returncode, "err": err})
            record({"at": now, "label": label, "action": "failed",
                    "rc": proc.returncode, "err": err})

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        verb = "healed" if args.apply else "WOULD heal"
        print(f"launchd self-heal: {report['checked']} estate agents · "
              f"{report['loaded']} loaded · {report['retired']} retired by declaration")
        for h in report["healed"]:
            print(f"  🔧 {verb}: {h['label']}")
        for r in report["refused"]:
            print(f"  ⛔ REFUSED {r['label']} — healed {r['heals_24h']}x in 24h; "
                  f"this is a crash-loop, not a missing load")
        for f in report["failed"]:
            print(f"  ❌ FAILED {f['label']} rc={f['rc']} {f['err']}")

    # Non-zero only when something is still wrong after this run. A successful heal is not
    # a fault; a refusal or a failure is.
    return 1 if (report["refused"] or report["failed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
