#!/usr/bin/env python3
"""Audit Trail Recorder.
Permanent append-only log of every decision made, its rationale, and its outcome.
Runs after every task completion (via outcome-accelerator hook).
Creates a searchable JSONL timeline of what was decided and what happened.
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
AUDIT_LOG = HERMES_HOME / "logs" / "audit" / "decision-trail.jsonl"
SNAPSHOT_DIR = HERMES_HOME / "meta" / "snapshots"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get_last_snapshot():
    """Grab the most recent pre/post snapshot for state context."""
    if not SNAPSHOT_DIR.exists():
        return None
    pre_files = sorted(SNAPSHOT_DIR.glob("snapshot-pre-apply-*.json"))
    post_files = sorted(SNAPSHOT_DIR.glob("snapshot-post-apply-*.json"))
    if pre_files:
        try:
            with open(pre_files[-1]) as f:
                snap = json.load(f)
            return {
                "snapshot_file": pre_files[-1].name,
                "policy_count": len(snap.get("policies", [])),
                "active_count": len([p for p in snap.get("policies", [])
                                     if p.get("status") in ("active", "provisional")]),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return None

def record_decision(decision_type, description, rationale, outcome="pending"):
    """Record a decision with full context."""
    entry = {
        "timestamp": iso_now(),
        "decision_type": decision_type,
        "description": description[:300],
        "rationale": rationale[:500],
        "outcome": outcome,
        "state_snapshot": get_last_snapshot(),
        "source": "auto",
    }
    
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    print(f"📝 Decision logged: {decision_type} — {description[:60]}...")
    return entry

def replay_audit(n=10):
    """Show last N audit entries."""
    if not AUDIT_LOG.exists():
        print("No audit trail yet.")
        return
    with open(AUDIT_LOG) as f:
        lines = f.readlines()
    for line in lines[-n:]:
        try:
            e = json.loads(line.strip())
            ts = e.get("timestamp", "")[11:19]
            dt = e.get("decision_type", "?")
            desc = e.get("description", "")[:70]
            outcome = e.get("outcome", "?")
            print(f"  [{ts}] {dt}: {desc} → {outcome}")
        except json.JSONDecodeError:
            continue

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--replay":
        replay_audit(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif len(sys.argv) > 3:
        record_decision(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        print("Usage:")
        print("  audit-trail.py <decision_type> <description> <rationale>")
        print("  audit-trail.py --replay [N]")
