#!/usr/bin/env python3
"""Hermes relay queue — Otto-side ingestion of cron/probe/watchdog events.

FIRE 0 (the relay gap): cron jobs delivered alerts straight to the user's
Telegram; Otto was blind until the user pasted them back, so Otto could never
triage before the user. This queue is the ingestion point and Otto's read surface:

  submit  — any cron/script enqueues an event (ATOMIC write to incoming/)
  drain   — triage: dedup by canonical fingerprint, write curated digest, archive
  status  — current open fingerprints (what Otto's heartbeat reads & reports)

Stdlib only. Atomic writes (tmp + os.replace + fsync) so a kill mid-write never
leaves a partial event. Dedup uses the SHARED canonicalizer (hermes_fingerprint),
so PID/timestamp-varying messages collapse to one fingerprint — the exact bug that
made alert-resolver false-clear. Resolution lifecycle stays alert-resolver's job;
this queue is ingestion + dedup + surfacing only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes_fingerprint import canonicalize  # noqa: E402

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
QUEUE = HERMES_HOME / "queue"
INCOMING = QUEUE / "incoming"
PROCESSED = QUEUE / "processed"
DIGEST = QUEUE / "digest.jsonl"
STATE = QUEUE / "state.json"

# A re-fire within this window is a duplicate (suppressed, count incremented).
DEDUP_WINDOW_SEC = int(os.environ.get("HERMES_QUEUE_DEDUP_WINDOW", "3600"))
# Housekeeping only (NOT resolution): drop fingerprints unseen this long from the
# open set so status() reflects currently-active issues. Long window on purpose;
# authoritative resolved/healthy lifecycle belongs to alert-resolver.
EXPIRY_SEC = int(os.environ.get("HERMES_QUEUE_EXPIRY", "86400"))


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    INCOMING.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
    with open(tmp, "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def submit(args) -> int:
    _ensure_dirs()
    event = {
        "id": uuid.uuid4().hex[:12],
        "ts": iso_now(),
        "source": args.source,
        "severity": args.severity,
        "message": args.message,
        "fingerprint": canonicalize(f"{args.source}: {args.message}"),
        "meta": json.loads(args.meta) if args.meta else {},
    }
    stamp = event["ts"].replace(":", "").replace("-", "")
    fname = INCOMING / f"{stamp}-{args.source}-{event['id']}.json"
    _atomic_write(fname, json.dumps(event))
    print(f"queued {event['id']} [{args.severity}] {args.source}: {args.message[:60]}")
    return 0


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"fingerprints": {}}


def drain(args) -> int:
    _ensure_dirs()
    state = _load_state()
    fps: dict = state["fingerprints"]
    now = time.time()
    files = sorted(INCOMING.glob("*.json"))

    drained = new_fp = suppressed = 0
    digest_lines: list[dict] = []

    for ev_file in files:
        try:
            ev = json.loads(ev_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        fp = ev.get("fingerprint", "")
        rec = fps.get(fp)
        if rec is None:
            fps[fp] = {
                "count": 1, "first_seen": ev["ts"], "last_seen": ev["ts"],
                "last_epoch": now, "severity": ev["severity"],
                "source": ev["source"], "sample": ev["message"][:200],
            }
            new_fp += 1
            is_new = True
        else:
            is_dup = (now - rec.get("last_epoch", 0)) < DEDUP_WINDOW_SEC
            rec["count"] += 1
            rec["last_seen"] = ev["ts"]
            rec["last_epoch"] = now
            if is_dup:
                suppressed += 1
            is_new = False
        # Curated digest: surface NEW fingerprints, and ALWAYS surface crit.
        if is_new or ev["severity"] == "crit":
            digest_lines.append({
                "ts": iso_now(), "fingerprint": fp, "severity": ev["severity"],
                "source": ev["source"], "message": ev["message"][:200],
                "count": fps[fp]["count"], "status": "open",
            })
        os.replace(ev_file, PROCESSED / ev_file.name)
        drained += 1

    # Housekeeping: expire stale fingerprints from the open set.
    expired = [k for k, v in fps.items() if (now - v.get("last_epoch", 0)) > EXPIRY_SEC]
    for k in expired:
        del fps[k]

    if digest_lines:
        with open(DIGEST, "a") as f:
            for d in digest_lines:
                f.write(json.dumps(d) + "\n")
    _atomic_write(STATE, json.dumps(state, indent=2))

    print(f"drained {drained} event(s): {new_fp} new fingerprint(s), "
          f"{suppressed} duplicate(s) suppressed, {len(expired)} expired")
    if digest_lines:
        print(f"digest: {len(digest_lines)} curated entr(ies) -> {DIGEST}")
    return 0


def resolve(args) -> int:
    """Probe-verified resolution — remove a fingerprint (or all of a source) from the
    open set. This is the CORRECT resolution lifecycle (the anti-false-clear): the
    caller clears an issue only because a verification probe PASSED, never because a
    message went absent. otto-dispatch calls this after a successful auto-remediation.
    """
    state = _load_state()
    fps: dict = state["fingerprints"]
    removed = 0
    for fp in list(fps.keys()):
        if args.fingerprint and fp == args.fingerprint:
            del fps[fp]
            removed += 1
        elif args.source and fps[fp].get("source") == args.source:
            del fps[fp]
            removed += 1
    _atomic_write(STATE, json.dumps(state, indent=2))
    print(f"resolved {removed} fingerprint(s)")
    return 0


def status(args) -> int:
    fps = _load_state().get("fingerprints", {})
    out = {
        "open_fingerprints": len(fps),
        "items": [
            {"fingerprint": k, "count": v["count"], "severity": v["severity"],
             "source": v["source"], "last_seen": v["last_seen"]}
            for k, v in fps.items()
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Hermes relay queue")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--source", required=True)
    s.add_argument("--severity", default="warn", choices=["info", "warn", "crit"])
    s.add_argument("--message", required=True)
    s.add_argument("--meta", default="")
    s.set_defaults(func=submit)
    sub.add_parser("drain").set_defaults(func=drain)
    r = sub.add_parser("resolve")
    r.add_argument("--fingerprint", default="")
    r.add_argument("--source", default="")
    r.set_defaults(func=resolve)
    sub.add_parser("status").set_defaults(func=status)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
