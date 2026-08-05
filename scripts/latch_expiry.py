#!/usr/bin/env python3
"""Latch expiry — no automatic trip may require manual recovery forever.

Every silence found in the 2026-08-05 audit had the same shape: something tripped
automatically, and clearing it needed a human who was never asked.

  meta/ESTATE_PAUSED         held 3.2d   — blocked every tick; no event, no owner, no reason
  otto-dispatch              held 46.3d  — disabled, and a disabled job reports last_status=ok
  otto-improvement-pulse     held 46.0d
  daily-strategist-audit     held 7.6d   — auto-disabled after one RuntimeError
  breaker manual_test        held 2.5d   — a breaker with no cooldown is a latch, not a breaker
  4 cron jobs                never ran   — enabled, last_run_at=None, no status to fail

None of these were failures. Each was the ABSENCE of a signal, which is invisible to
anything that watches for failures — which is why Otto never caught them.

This turns every latch into a bounded state:

    held < max_age            fine, no action
    held > max_age            ESCALATE — emit an alert naming the latch, its age, its owner
    held > max_age * expire_x AUTO-RELEASE, where the latch declares it safe to do so

Auto-release is opt-in per latch (`auto_release: true`) and never applies to a latch
the founder set deliberately. ESTATE_PAUSED is deliberately NOT auto-releasable: a
kill-switch that clears itself is not a kill-switch. It escalates loudly instead, every
run, until a human resolves it — which is the behaviour that was missing.

Read-only unless --apply is passed. Exit 0 = no latch past its window.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

HOME = os.path.expanduser("~/.hermes")
REGISTRY = os.environ.get("HERMES_CAPABILITIES") or os.path.join(HOME, "capabilities.json")
ALERTS = os.path.join(HOME, "logs", "alerts", "latch_expiry.jsonl")

sys.path.insert(0, os.path.join(HOME, "scripts"))
try:
    from capability_audit import audit_latches, _fmt_age  # reuse one definition of "held"
except ImportError as exc:  # pragma: no cover
    print(f"❌ cannot import capability_audit: {exc}", file=sys.stderr)
    raise SystemExit(2)


def _emit(record: dict) -> None:
    """Append an alert. This is the escalation channel the latches never had."""
    os.makedirs(os.path.dirname(ALERTS), exist_ok=True)
    with open(ALERTS, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def _release_cron(job_name: str) -> str:
    """Re-enable a disabled cron job."""
    path = os.path.join(HOME, "cron", "jobs.json")
    with open(path) as fh:
        data = json.load(fh)
    jobs = data["jobs"] if isinstance(data, dict) and "jobs" in data else data
    for job in jobs:
        if (job.get("name") or job.get("id")) == job_name:
            job["enabled"] = True
            job.pop("disabled_at", None)
            job["reenabled_by"] = "latch_expiry"
            job["reenabled_at"] = time.time()
            break
    else:
        return f"job not found: {job_name}"
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)  # atomic: a torn jobs.json would disable the whole scheduler
    return f"re-enabled cron job {job_name}"


def _release_breaker(filename: str) -> str:
    """Close a circuit breaker that has been open past its window."""
    path = os.path.join(HOME, "state", "circuit_breakers", filename)
    if not os.path.exists(path):
        return f"breaker not found: {filename}"
    with open(path) as fh:
        state = json.load(fh)
    state["state"] = "closed"
    state["failures"] = 0
    state["closed_by"] = "latch_expiry"
    state["closed_at"] = time.time()
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)
    return f"closed breaker {filename}"


RELEASERS = {"cron_disabled": _release_cron, "breaker_open": _release_breaker}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually release expired auto-releasable latches (default: report only)")
    ap.add_argument("--quiet", action="store_true", help="suppress output when nothing is breached")
    args = ap.parse_args()

    with open(REGISTRY) as fh:
        reg = json.load(fh)
    by_id = {l["id"]: l for l in reg.get("latches", [])}

    now = time.time()
    results = audit_latches(reg, now)
    breached = [r for r in results if r["breached"]]

    if not breached:
        if not args.quiet:
            print("✅ no latch past its window")
        return 0

    print("=" * 78)
    print(f"LATCH EXPIRY — {sum(len(r['breached']) for r in breached)} held past window")
    print("=" * 78)

    for res in breached:
        decl = by_id.get(res["id"], {})
        kind = decl.get("kind")
        max_age = res["max_age_s"]
        auto = bool(decl.get("auto_release"))
        expire_x = float(decl.get("expire_multiplier", 2))

        print(f"\n🔒 {res['id']}  (max {_fmt_age(max_age)}, auto_release={auto})")
        for name, age in res["breached"]:
            # An unmeasurable hold is treated as expired, not as exonerated: a latch with
            # no start time is precisely the case nobody can reason about, and letting it
            # sit is how otto-dispatch reached 46 days.
            over = age is None or age > max_age * expire_x
            verdict = "AUTO-RELEASE" if (auto and over) else "ESCALATE"
            print(f"   {name} — held {_fmt_age(age)} → {verdict}")

            record = {
                "at": now, "latch": res["id"], "item": name, "held_s": age,
                "max_age_s": max_age, "action": verdict, "owner": decl.get("what", ""),
            }

            if verdict == "AUTO-RELEASE" and args.apply:
                releaser = RELEASERS.get(kind)
                if releaser is None:
                    record["result"] = f"no releaser for kind {kind!r}"
                else:
                    try:
                        record["result"] = releaser(name)
                    except Exception as exc:  # noqa: BLE001
                        record["result"] = f"release failed: {exc}"
                print(f"      └─ {record['result']}")
            elif verdict == "AUTO-RELEASE":
                print("      └─ (dry run — pass --apply to release)")

            _emit(record)

    print(f"\nalerts → {os.path.relpath(ALERTS, HOME)}")
    if not args.apply:
        print("dry run: nothing was changed. Pass --apply to release expired latches.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
