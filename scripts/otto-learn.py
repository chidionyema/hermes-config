#!/usr/bin/env python3
"""
otto-learn — Policy management CLI for Otto's correction-learning loop.

Usage:
    otto-learn add <trigger> <rule> [--scope <scope>]
    otto-learn list
    otto-learn fire <id>
    otto-learn review

Policies are stored as JSON files in ~/.hermes/policies/<id>.json.
Firings are logged to ~/.hermes/logs/policy-firings.jsonl.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

POLICIES_DIR = Path.home() / ".hermes" / "policies"
ARCHIVED_DIR = POLICIES_DIR / "archived"
FIRINGS_LOG = Path.home() / ".hermes" / "logs" / "policy-firings.jsonl"

POLICIES_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)
FIRINGS_LOG.parent.mkdir(parents=True, exist_ok=True)

# ── Helpers ────────────────────────────────────────────────────────────────

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")


def next_id() -> str:
    """Generate the next policy id in sequence: pol-YYYYMMDD-NNN."""
    existing = list(POLICIES_DIR.glob(f"pol-{TODAY}-*.json"))
    seq = len(existing) + 1
    return f"pol-{TODAY}-{seq:03d}"


def load_policy(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_policy(policy: dict):
    path = POLICIES_DIR / f"{policy['id']}.json"
    with open(path, "w") as f:
        json.dump(policy, f, indent=2)
        f.write("\n")


def all_policies() -> list[dict]:
    """Return all non-archived policies sorted by id."""
    files = sorted(POLICIES_DIR.glob("pol-*.json"))
    return [load_policy(p) for p in files]


def parse_scope(raw: str | None) -> dict:
    """Parse '--scope project:x domain:y type:z' into a dict."""
    scope: dict[str, str] = {}
    if not raw:
        return scope
    for token in raw.strip().split():
        m = re.match(r"^(\w+):(.+)$", token)
        if m:
            scope[m.group(1)] = m.group(2)
    return scope


# ── Commands ───────────────────────────────────────────────────────────────

def cmd_add(args: argparse.Namespace):
    """Create a new policy file."""
    policy = {
        "id": next_id(),
        "trigger": args.trigger,
        "rule": args.rule,
        "scope": parse_scope(args.scope),
        "confidence": 0.3,
        "hits": 0,
        "helped": 0,
        "hurt": 0,
        "status": "provisional",
        "created": ISO_NOW,
        "last_fired": None,
        "source_correction": args.source or "",
    }
    save_policy(policy)
    print(f"✓ Created policy {policy['id']}: {args.trigger}")
    return policy


def cmd_list(args: argparse.Namespace):
    """List all policies with status, confidence, hits."""
    policies = all_policies()
    if not policies:
        print("No policies yet.")
        return

    print(f"{'ID':<22} {'Status':<14} {'Conf':<6} {'Hits':<6} {'Trigger':<50}")
    print("-" * 100)
    for p in policies:
        trigger = p["trigger"][:47] + "..." if len(p["trigger"]) > 50 else p["trigger"]
        print(
            f"{p['id']:<22} {p['status']:<14} {p['confidence']:<6.1f} {p['hits']:<6} {trigger}"
        )


def cmd_fire(args: argparse.Namespace):
    """Increment the hits counter and log the firing."""
    path = POLICIES_DIR / f"{args.id}.json"
    if not path.exists():
        print(f"✗ Policy {args.id} not found.", file=sys.stderr)
        sys.exit(1)

    policy = load_policy(path)
    policy["hits"] += 1
    policy["last_fired"] = ISO_NOW
    save_policy(policy)

    # Log the firing
    entry = {
        "policy_id": args.id,
        "trigger": policy["trigger"],
        "rule": policy["rule"],
        "timestamp": ISO_NOW,
        "context": args.context or "",
    }
    with open(FIRINGS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"✓ Fired {args.id} (hits: {policy['hits']})")


def cmd_review(args: argparse.Namespace):
    """Show promote/demote candidates based on thresholds."""
    policies = all_policies()
    if not policies:
        print("No policies to review.")
        return

    promotes: list[dict] = []
    demotes: list[dict] = []

    for p in policies:
        total = p["helped"] + p["hurt"]
        if total == 0:
            continue
        ratio = p["helped"] / total if total > 0 else 1.0

        if p["status"] == "provisional" and p["hits"] >= 3 and ratio >= 0.7:
            promotes.append(p)
        if p["status"] == "active" and p["hits"] >= 5 and (p["hurt"] / total) > 0.5:
            demotes.append(p)

    if promotes:
        print("=== Promote candidates (provisional → active) ===")
        for p in promotes:
            total = p["helped"] + p["hurt"]
            ratio = p["helped"] / total
            print(f"  {p['id']}: {p['trigger']} (hits={p['hits']}, ratio={ratio:.1%})")
    else:
        print("No promote candidates.")

    print()

    if demotes:
        print("=== Demote candidates (active → demoted) ===")
        for p in demotes:
            total = p["helped"] + p["hurt"]
            ratio = p["hurt"] / total
            print(f"  {p['id']}: {p['trigger']} (hits={p['hits']}, hurt_ratio={ratio:.1%})")
    else:
        print("No demote candidates.")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Otto correction-learning policy manager"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Create a new policy")
    p_add.add_argument("trigger", help="The trigger pattern (e.g., 'killed a process without plan')")
    p_add.add_argument("rule", help="The rule to follow")
    p_add.add_argument("--scope", help="Scope tags, e.g. 'project:x domain:y type:z'")
    p_add.add_argument("--source", help="Source correction text for provenance")

    # list
    p_list = sub.add_parser("list", help="List all policies")

    # fire
    p_fire = sub.add_parser("fire", help="Increment hits and log a firing")
    p_fire.add_argument("id", help="Policy ID (e.g., pol-20260618-001)")
    p_fire.add_argument("--context", help="Context of the firing")

    # review
    p_review = sub.add_parser("review", help="Show promote/demote candidates")

    args = parser.parse_args()

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "fire": cmd_fire,
        "review": cmd_review,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
