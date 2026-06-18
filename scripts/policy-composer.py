#!/usr/bin/env python3
"""
policy-composer.py — Slope maximisation via policy co-firing analysis.

Scans policy-firings.jsonl for co-firing patterns. When two or more policy IDs
fire together frequently (3+ times within the same action context), proposes
a combined rule. Also finds frequently co-occurring trigger patterns and
proposes general policies.

Updates policy-enforcer.py's composed rules file so the enforcer can use them.

Usage:
    python3 policy-composer.py [--analyze] [--apply] [--status]

    --analyze   Scan firing log, detect co-firing patterns, propose compositions
    --apply     Apply pending compositions (creates combined policies)
    --status    Show current composition state
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
FIRINGS_LOG = HERMES_HOME / "logs" / "policy-firings.jsonl"
POLICY_DIR = HERMES_HOME / "policies"
COMPOSED_POLICIES_FILE = HERMES_HOME / "meta" / "composed-policies.json"
COMPOSED_LOG = HERMES_HOME / "logs" / "composed-firings.jsonl"

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_firings() -> list[dict]:
    if not FIRINGS_LOG.exists():
        return []
    entries = []
    with open(FIRINGS_LOG) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_policies() -> list[dict]:
    policies = []
    for fname in sorted(POLICY_DIR.glob("pol-*.json")):
        with open(fname) as f:
            policies.append(json.load(f))
    return policies


def load_composed() -> list[dict]:
    if not COMPOSED_POLICIES_FILE.exists():
        return []
    with open(COMPOSED_POLICIES_FILE) as f:
        return json.load(f)


def save_composed(composed: list[dict]):
    os.makedirs(COMPOSED_POLICIES_FILE.parent, exist_ok=True)
    with open(COMPOSED_POLICIES_FILE, "w") as f:
        json.dump(composed, f, indent=2)


def analyze_co_firing(firings: list[dict]) -> list[dict]:
    """
    Detect policy IDs that fire together in the same context.
    Groups firings by context string, then finds co-occurring IDs.
    Returns proposals for combined rules.
    """
    # Group by context
    by_context = defaultdict(list)
    for f in firings:
        ctx = f.get("context", "")
        by_context[ctx].append(f)

    # Find co-firing pairs
    pair_counts = Counter()
    for ctx, entries in by_context.items():
        if len(entries) < 2:
            continue
        ids = sorted(set(e.get("policy_id") for e in entries if e.get("policy_id")))
        # Generate all pairs
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = (ids[i], ids[j])
                pair_counts[pair] += 1

    # Proposals
    proposals = []
    policies = {p.get("id"): p for p in load_policies()}

    for (id1, id2), count in pair_counts.most_common():
        if count < 3:
            break  # Threshold: 3+ co-firings needed for proposal

        p1 = policies.get(id1, {})
        p2 = policies.get(id2, {})

        trigger1 = p1.get("trigger", "")
        trigger2 = p2.get("trigger", "")
        rule1 = p1.get("rule", "")
        rule2 = p2.get("rule", "")

        # Find common words in triggers
        words1 = set(trigger1.lower().split())
        words2 = set(trigger2.lower().split())
        common = words1 & words2

        if common:
            # They share a theme — general policy candidate
            combined_trigger = f"Combined: {trigger1[:50]} + {trigger2[:50]}"
            combined_rule = (
                f"Composite rule ({id1} + {id2}, fired together {count}x): "
                f"{rule1[:80]} AND {rule2[:80]}"
            )
        else:
            # Different themes but co-fire — context-dependent composition
            combined_trigger = f"Context pattern: '{trigger1[:40]}' when '{trigger2[:40]}'"
            combined_rule = (
                f"Contextual composition ({id1} + {id2}, {count}x co-fires): "
                f"When context matches both, apply: {rule1[:60]}; then {rule2[:60]}"
            )

        proposals.append({
            "id1": id1,
            "id2": id2,
            "co_fire_count": count,
            "combined_trigger": combined_trigger[:100],
            "combined_rule": combined_rule[:200],
            "status": "proposed",
            "proposed_at": ISO_NOW,
        })

    return proposals


def find_trigger_clusters(firings: list[dict]) -> list[dict]:
    """
    Find trigger patterns that fire together frequently.
    Identifies which triggers (by normalized text) co-occur.
    """
    # Group by normalized trigger text
    by_trigger = defaultdict(list)
    for f in firings:
        trigger = f.get("trigger", "").lower().strip()
        # Normalize: remove leading "asked"/"killed"/etc
        trigger_norm = re.sub(r"^(asked|killed|waited|surfaced|guessed|repeated|presented)\s+", "", trigger)
        by_trigger[trigger_norm].append(f)

    # Find triggers that share common action words
    action_clusters = defaultdict(list)
    for norm, entries in by_trigger.items():
        # Extract the first verb (action word)
        action_match = re.match(r"(\w+)", norm)
        if action_match:
            action = action_match.group(1)
            action_clusters[action].extend(entries)

    proposals = []
    for action, entries in action_clusters.items():
        if len(entries) < 3:
            continue
        # This action triggers frequently — propose a general policy
        policy_ids = list(set(e.get("policy_id") for e in entries if e.get("policy_id")))
        if len(policy_ids) < 2:
            continue

        proposals.append({
            "action": action,
            "frequency": len(entries),
            "unique_policies": len(policy_ids),
            "policy_ids": policy_ids,
            "description": f"Action '{action}' fired {len(entries)}x across {len(policy_ids)} policies. "
                          f"Consider a general rule covering this pattern.",
            "status": "proposed",
            "proposed_at": ISO_NOW,
        })

    return proposals


def apply_composition(proposal: dict, policies: list[dict]):
    """Apply a composition proposal: create a combined policy."""
    existing = load_composed()

    # Check if already applied
    for comp in existing:
        if comp.get("id1") == proposal["id1"] and comp.get("id2") == proposal["id2"]:
            print(f"  Already composed: {proposal['id1']} + {proposal['id2']}")
            return

    # Create composed policy record
    composed = {
        "composition_id": f"comp-{len(existing) + 1:03d}",
        "id1": proposal["id1"],
        "id2": proposal["id2"],
        "co_fire_count": proposal.get("co_fire_count", 0),
        "combined_trigger": proposal.get("combined_trigger", ""),
        "combined_rule": proposal.get("combined_rule", ""),
        "applied_at": ISO_NOW,
        "status": "active",
    }
    existing.append(composed)
    save_composed(existing)

    # Log the composition firing
    os.makedirs(COMPOSED_LOG.parent, exist_ok=True)
    with open(COMPOSED_LOG, "a") as f:
        f.write(json.dumps(composed) + "\n")

    print(f"  ✅ Applied composition: {composed['composition_id']} "
          f"({proposal['id1']} + {proposal['id2']})")


def cmd_analyze():
    """Analyze firing log for co-firing patterns."""
    print("=== Policy Composition Analysis ===")
    print()

    firings = load_firings()
    if not firings:
        print("  No policy firings logged yet.")
        return 0

    print(f"  Analyzing {len(firings)} firing entries...")
    print()

    # Co-firing analysis
    proposals = analyze_co_firing(firings)
    if proposals:
        print(f"  🔥 Co-Firing Proposals ({len(proposals)})")
        for p in proposals:
            print(f"     ({p['id1']} + {p['id2']}) x{p['co_fire_count']}")
            print(f"     → {p['combined_trigger'][:80]}")
            print(f"       {p['combined_rule'][:100]}")
            print()
    else:
        print("  No co-firing patterns detected (need 3+ same-context firings).")
        print()

    # Trigger cluster analysis
    clusters = find_trigger_clusters(firings)
    if clusters:
        print(f"  🔄 Trigger Cluster Proposals ({len(clusters)})")
        for c in clusters:
            print(f"     Action '{c['action']}': {c['frequency']} firings, {c['unique_policies']} policies")
            print(f"     → {c['description'][:100]}")
            print()
    else:
        print("  No trigger clusters detected.")

    # Save proposals so --apply can use them
    all_proposals = proposals + clusters
    if all_proposals:
        props_file = HERMES_HOME / "meta" / "composition-proposals.json"
        with open(props_file, "w") as f:
            json.dump(all_proposals, f, indent=2)
        print(f"  Proposals saved to {props_file}")

    return 0


def cmd_apply():
    """Apply pending composition proposals."""
    print("=== Applying Compositions ===")
    print()

    props_file = HERMES_HOME / "meta" / "composition-proposals.json"
    if not props_file.exists():
        # No proposals is a normal idle state, not a failure — analyze simply found
        # nothing to compose. Returning non-zero here false-flagged the whole
        # idle-learning run as failed (Ball 16 follow-on).
        print("  No proposals to apply (analyze found none) — nothing to do.")
        return 0

    with open(props_file) as f:
        proposals = json.load(f)

    policies = load_policies()
    applied = 0

    for p in proposals:
        if p.get("status") != "proposed":
            continue
        # Only apply co-firing proposals (not cluster proposals — those need human review)
        if "id1" in p and "id2" in p:
            apply_composition(p, policies)
            applied += 1

    print(f"\n  Applied {applied} compositions.")
    return 0


def cmd_status():
    """Show current composition state."""
    print("=== Policy Composition Status ===")
    print()

    composed = load_composed()
    if composed:
        print(f"  Active compositions: {len(composed)}")
        for c in composed:
            print(f"    {c['composition_id']}: {c['id1']} + {c['id2']} "
                  f"(co-fires: {c.get('co_fire_count', '?')}x, status: {c.get('status', '?')})")
    else:
        print("  No active compositions.")

    print()

    # Show co-firing stats
    firings = load_firings()
    by_context = defaultdict(list)
    for f in firings:
        by_context[f.get("context", "")].append(f)

    multi_fire_contexts = sum(1 for ctx, entries in by_context.items() if len(entries) >= 2)
    print(f"  Firing log entries: {len(firings)}")
    print(f"  Contexts with multi-fire: {multi_fire_contexts}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Policy Composition Analyzer")
    parser.add_argument("--analyze", action="store_true", help="Scan firings for co-firing patterns")
    parser.add_argument("--apply", action="store_true", help="Apply pending compositions")
    parser.add_argument("--status", action="store_true", help="Show composition state")

    args = parser.parse_args()

    if args.analyze:
        sys.exit(cmd_analyze())
    elif args.apply:
        sys.exit(cmd_apply())
    elif args.status:
        sys.exit(cmd_status())
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    main()
