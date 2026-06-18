#!/usr/bin/env python3
"""Dropped-ball watchdog — catches self-certification at the substrate level.

THE SYSTEMIC BUG: Otto reports "X is fixed / resolved / healthy" without independent
verification, so a success claim is CHEAP and a lie is SILENT — the user is the only
check. This module inverts that: a success claim is recorded ONLY together with the
probe that verifies it; the probe is RUN at assert time AND re-run on audit; and any
claim that is unverified (no probe) or whose probe FAILS is escalated to the relay
queue (hermes_queue) as a dropped ball. Mechanism, not "remember to check".

  assert --claim "<text>" --probe "<cmd>"   record + verify a claim now
  audit                                       re-verify every open claim; escalate failures
  status                                      list open claims + verification state

Exit codes — assert: 0 if verified, 2 if unverified/failed.  audit: 0 if all claims
verified, 2 if any dropped ball (so a cron or test fails LOUDLY, not silently).

NOTE ON ENFORCEMENT: this is the mechanism. Forcing Otto's "done/fixed" claims THROUGH
it is a Stop/PostToolUse hook (the hooks fire). Until that lands, `audit` also scans the
real alert log for absence-based "condition_cleared" resolutions — unverified by
construction — so existing self-certification is surfaced immediately.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
QUEUE = HERMES_HOME / "queue"
LEDGER = QUEUE / "claims.jsonl"
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
SCRIPTS = Path(__file__).resolve().parent
PROBE_TIMEOUT = int(os.environ.get("HERMES_CLAIM_PROBE_TIMEOUT", "120"))


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure() -> None:
    QUEUE.mkdir(parents=True, exist_ok=True)


def _run_probe(cmd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT)
        return r.returncode, (r.stdout or "")[-400:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:  # noqa: BLE001 — a broken probe cmd is itself a dropped ball
        return 125, str(e)


def _append(entry: dict) -> None:
    _ensure()
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _latest_open() -> list[dict]:
    by_key: dict[str, dict] = {}
    for e in _read_ledger():
        by_key[e.get("claim", "")] = e  # later entry wins
    return [e for e in by_key.values() if e.get("status") == "open"]


def _submit_queue(claim: str, reason: str) -> None:
    try:
        subprocess.run(
            ["python3", str(SCRIPTS / "hermes_queue.py"), "submit",
             "--source", "dropped-ball-watchdog", "--severity", "crit",
             "--message", f"unverified success claim: {claim} ({reason})"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:  # noqa: BLE001 — never let escalation failure mask the audit
        pass


def cmd_assert(args) -> int:
    claim = args.claim
    probe = args.probe
    base = {"id": uuid.uuid4().hex[:12], "ts": iso_now(), "claim": claim,
            "source": args.source, "status": "open", "last_checked": iso_now()}
    if not probe:
        _append({**base, "probe": "", "verified": False, "exit_code": None,
                 "reason": "no_probe"})
        print(f"DROPPED BALL: claim asserted with NO verifying probe -> {claim}")
        return 2
    rc, _tail = _run_probe(probe)
    verified = rc == 0
    _append({**base, "probe": probe, "verified": verified, "exit_code": rc,
             "reason": "" if verified else "probe_failed"})
    if verified:
        print(f"VERIFIED: {claim}  (probe exit 0)")
        return 0
    print(f"DROPPED BALL: probe FAILED (exit {rc}) for claim -> {claim}")
    return 2


def cmd_audit(args) -> int:
    open_claims = _latest_open()
    balls: list[tuple[str, str]] = []
    for e in open_claims:
        probe = e.get("probe", "")
        if not probe:
            balls.append((e["claim"], "no_probe"))
            continue
        rc, _ = _run_probe(probe)
        if rc != 0:
            balls.append((e["claim"], f"probe_exit_{rc}"))

    # Systemic scan: absence-based resolutions are unverified by construction.
    absence = 0
    if ALERT_LOG.exists():
        for line in ALERT_LOG.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("resolution") == "condition_cleared":
                absence += 1

    for claim, reason in balls:
        _submit_queue(claim, reason)

    print(f"audit: {len(open_claims)} open claim(s), {len(balls)} DROPPED BALL(s)")
    for claim, reason in balls:
        print(f"  ❗ {reason}: {claim}")
    if absence:
        print(f"  ⚠ systemic: {absence} absence-based 'condition_cleared' resolution(s) "
              f"in watchdog.jsonl — unverified by construction (fix alert-resolver to "
              f"emit probe_verified resolutions)")
    return 2 if balls else 0


def cmd_status(args) -> int:
    rows = _latest_open()
    if not rows:
        print("no open claims")
        return 0
    for e in rows:
        tag = "OK  " if e.get("verified") else "BALL"
        print(f"[{tag}] {e['claim']}  probe={e.get('probe') or '<none>'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Dropped-ball watchdog (claims ledger)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assert")
    a.add_argument("--claim", required=True)
    a.add_argument("--probe", default="")
    a.add_argument("--source", default="otto")
    a.set_defaults(func=cmd_assert)
    sub.add_parser("audit").set_defaults(func=cmd_audit)
    sub.add_parser("status").set_defaults(func=cmd_status)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
