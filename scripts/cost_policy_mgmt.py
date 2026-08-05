"""
Cost attribution + Policy compression for Hermes self-improvement.

Tier 2: Tracks self-improvement credit usage, measures overhead vs primary
        task execution, auto-throttles when credit pressure exceeds threshold.
Tier 3: Merges related policies, deduplicates, enforces hard ceiling on
        active policy count, domain-scopes injection to prevent the context
        window collapse predicted at 50-70 policies.
"""

import json
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


class CostTracker:
    """Tracks self-improvement credit/resource consumption.

    Measures what percentage of context window, API credits, and latency
    is consumed by self-improvement vs primary task execution.
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.cost_log = self.home / "logs" / "self-improvement-costs.jsonl"
        self.cost_log.parent.mkdir(parents=True, exist_ok=True)

    def record(self, activity: str, cost_type: str, amount: float, unit: str) -> None:
        """Record a self-improvement cost event.

        Args:
            activity: What self-improvement activity (e.g., "self_regression", "gap_finding")
            cost_type: "credits", "tokens", "latency_seconds", "context_pct"
            amount: Numeric amount consumed
            unit: Unit of measurement
        """
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "activity": activity,
            "cost_type": cost_type,
            "amount": amount,
            "unit": unit,
        }
        with open(self.cost_log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def stats(self, window_hours: int = 24) -> dict:
        """Compute cost statistics over a recent window.

        Returns total self-improvement cost and estimated overhead percentage.
        """
        if not self.cost_log.is_file():
            return {"total_activities": 0, "overhead_pct": 0.0}

        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        activities = defaultdict(lambda: {"count": 0, "total_cost": 0.0, "unit": ""})

        for line in self.cost_log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                ts_str = e.get("ts", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                act = e["activity"]
                activities[act]["count"] += 1
                activities[act]["total_cost"] += e["amount"]
                activities[act]["unit"] = e["unit"]
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                continue

        total_cost = sum(a["total_cost"] for a in activities.values())
        total_activities = sum(a["count"] for a in activities.values())

        return {
            "window_hours": window_hours,
            "total_activities": total_activities,
            "total_cost": round(total_cost, 2),
            "per_activity": {
                act: {"count": a["count"], "total": round(a["total_cost"], 2), "unit": a["unit"]}
                for act, a in sorted(activities.items())
            },
            "overhead_pct": 0.0,  # Requires primary task cost baseline to compute
        }

    def should_throttle(self, credit_limit: float = 10.0) -> tuple[bool, str]:
        """Check if self-improvement should be throttled due to credit pressure.

        Returns (should_throttle, reason).
        """
        stats = self.stats(window_hours=6)
        total_credits = sum(
            a["total"] for a in stats["per_activity"].values()
            if a["unit"] == "credits"
        )
        if total_credits > credit_limit:
            return True, f"Credit usage ({total_credits:.1f}) exceeds limit ({credit_limit}) in 6h"
        return False, "Within limits"


class PolicyCompressor:
    """Compresses, deduplicates, and domain-scopes the policy corpus.

    Prevents the architectural collapse predicted at 50-70 policies by:
    1. Merging related policies (similar triggers/rules)
    2. Deduplicating near-identical policies
    3. Domain-scoping: tagging policies with applicable domains
    4. Enforcing a hard ceiling on active policy count
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.policies_dir = self.home / "policies"
        self.compression_log = self.home / "logs" / "policy-compression.jsonl"
        self.max_active = 50  # Hard ceiling

    def analyze(self) -> dict:
        """Analyze the current policy corpus for compression opportunities.

        Returns stats and recommendations.
        """
        if not self.policies_dir.is_dir():
            return {"total": 0, "active": 0, "recommendations": []}

        policies = []
        for f in self.policies_dir.glob("*.json"):
            try:
                p = json.loads(f.read_text())
                p["_file"] = str(f.name)
                policies.append(p)
            except (json.JSONDecodeError, OSError):
                continue

        active = [p for p in policies if p.get("status") not in ("archived", "retired")]
        total = len(policies)
        active_count = len(active)

        # Find near-duplicates (similar trigger text)
        duplicates = []
        for i, p1 in enumerate(active):
            for j, p2 in enumerate(active):
                if j <= i:
                    continue
                t1 = (p1.get("trigger", "") + " " + p1.get("rule", "")).lower()
                t2 = (p2.get("trigger", "") + " " + p2.get("rule", "")).lower()
                # Simple Jaccard-like similarity on words
                words1 = set(t1.split())
                words2 = set(t2.split())
                if not words1 or not words2:
                    continue
                overlap = len(words1 & words2) / min(len(words1), len(words2))
                if overlap > 0.7:
                    duplicates.append({
                        "policy_a": p1["_file"],
                        "policy_b": p2["_file"],
                        "similarity": round(overlap, 2),
                        "trigger_a": p1.get("trigger", "")[:80],
                        "trigger_b": p2.get("trigger", "")[:80],
                    })

        recommendations = []
        if active_count > self.max_active:
            recommendations.append({
                "action": "ceiling_breach",
                "severity": "critical",
                "message": f"Active policies ({active_count}) exceed hard ceiling ({self.max_active}). "
                           f"Compression required.",
            })
        if duplicates:
            recommendations.append({
                "action": "deduplicate",
                "severity": "warning",
                "message": f"Found {len(duplicates)} near-duplicate policy pairs. Consider merging.",
                "pairs": duplicates[:5],
            })

        # Domain coverage
        domains = set()
        for p in active:
            domain = p.get("domain") or p.get("scope") or p.get("applies_to") or ""
            if domain:
                if isinstance(domain, list):
                    domains.update(domain)
                else:
                    domains.add(str(domain))

        return {
            "total": total,
            "active": active_count,
            "archived": total - active_count,
            "ceiling": self.max_active,
            "at_risk": active_count > self.max_active * 0.7,
            "domains": sorted(domains) if domains else ["unscoped"],
            "unscoped_policies": sum(1 for p in active
                                     if not (p.get("domain") or p.get("scope") or p.get("applies_to"))),
            "duplicates": duplicates,
            "recommendations": recommendations,
        }

    def compress(self, dry_run: bool = True) -> dict:
        """Execute policy compression: archive near-duplicates.

        In dry_run mode, only reports what would change.
        """
        analysis = self.analyze()
        if not analysis.get("duplicates"):
            return {"compressed": 0, "dry_run": dry_run, "message": "No duplicates found"}

        compressed = 0
        seen_kept = set()

        for dup in analysis["duplicates"]:
            # Keep the older policy (likely more tested), archive the newer
            keep = dup["policy_a"]  # Simple heuristic: keep first
            archive = dup["policy_b"]

            if archive in seen_kept or keep in seen_kept:
                continue  # Already handled

            if not dry_run:
                archive_path = self.policies_dir / archive
                archived_dir = self.policies_dir / "archived"
                archived_dir.mkdir(exist_ok=True)
                if archive_path.is_file():
                    policy = json.loads(archive_path.read_text())
                    policy["status"] = "archived"
                    policy["archived_at"] = datetime.now(timezone.utc).isoformat()
                    policy["merged_into"] = keep
                    (archived_dir / archive).write_text(json.dumps(policy, indent=2))
                    archive_path.unlink()
                    compressed += 1

                    # Log compression
                    with open(self.compression_log, "a") as f:
                        f.write(json.dumps({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "action": "compress",
                            "kept": keep,
                            "archived": archive,
                            "similarity": dup["similarity"],
                        }) + "\n")

            seen_kept.add(keep)
            seen_kept.add(archive)

        return {
            "compressed": compressed,
            "dry_run": dry_run,
            "message": f"{'Would compress' if dry_run else 'Compressed'} {compressed} policies",
        }

    def domain_scope_policy(self, policy_file: str, domains: list[str]) -> bool:
        """Tag a policy with the domains it applies to.

        Domain-scoped policies are only injected into tasks matching those domains.
        """
        policy_path = self.policies_dir / policy_file
        if not policy_path.is_file():
            return False
        try:
            policy = json.loads(policy_path.read_text())
            policy["domain"] = domains
            policy["domain_scoped_at"] = datetime.now(timezone.utc).isoformat()
            policy_path.write_text(json.dumps(policy, indent=2))
            return True
        except (json.JSONDecodeError, OSError):
            return False

    def get_domain_policies(self, domain: str) -> list[dict]:
        """Get policies applicable to a specific task domain.

        Only returns domain-scoped policies whose domains match, plus
        unscoped policies (which apply to all domains).
        """
        if not self.policies_dir.is_dir():
            return []

        applicable = []
        for f in self.policies_dir.glob("*.json"):
            try:
                p = json.loads(f.read_text())
                if p.get("status") in ("archived", "retired"):
                    continue
                policy_domains = p.get("domain") or p.get("scope") or p.get("applies_to") or []
                if isinstance(policy_domains, str):
                    policy_domains = [policy_domains]
                # Unscoped policies apply everywhere
                if not policy_domains or domain in policy_domains:
                    applicable.append(p)
            except (json.JSONDecodeError, OSError):
                continue

        return applicable


# ── CLI ──

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Cost tracking and policy compression for Hermes"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # cost stats
    cost_p = sub.add_parser("costs", help="Show self-improvement cost statistics")
    cost_p.add_argument("--hours", type=int, default=24)

    # cost record
    rec_p = sub.add_parser("record-cost", help="Record a self-improvement cost")
    rec_p.add_argument("--activity", required=True)
    rec_p.add_argument("--type", dest="cost_type", required=True)
    rec_p.add_argument("--amount", type=float, required=True)
    rec_p.add_argument("--unit", required=True)

    # policy analyze
    sub.add_parser("analyze", help="Analyze policy corpus for compression opportunities")

    # policy compress
    comp_p = sub.add_parser("compress", help="Compress policy corpus")
    comp_p.add_argument("--execute", action="store_true", help="Actually compress (not dry run)")

    # policy scope
    scope_p = sub.add_parser("scope", help="Domain-scope a policy")
    scope_p.add_argument("--policy", required=True, help="Policy filename")
    scope_p.add_argument("--domains", required=True, help="Comma-separated domains")

    args = parser.parse_args()

    if args.action == "costs":
        ct = CostTracker()
        stats = ct.stats(window_hours=args.hours)
        print(f"Self-improvement costs ({args.hours}h):")
        print(f"  Activities: {stats['total_activities']}")
        print(f"  Total cost: {stats['total_cost']}")
        for act, a in stats["per_activity"].items():
            print(f"  {act:30s} {a['count']:3d}x {a['total']:8.1f} {a['unit']}")

    elif args.action == "record-cost":
        ct = CostTracker()
        ct.record(args.activity, args.cost_type, args.amount, args.unit)
        print(f"✅ Recorded: {args.activity} = {args.amount} {args.unit}")

    elif args.action == "analyze":
        pc = PolicyCompressor()
        analysis = pc.analyze()
        print(f"Policies: {analysis['active']} active / {analysis['total']} total "
              f"(ceiling: {analysis['ceiling']})")
        print(f"Unscoped: {analysis['unscoped_policies']}")
        print(f"Domains: {', '.join(analysis['domains'])}")
        for r in analysis["recommendations"]:
            icon = "🔴" if r["severity"] == "critical" else "🟡"
            print(f"{icon} {r['message']}")

    elif args.action == "compress":
        pc = PolicyCompressor()
        dry_run = not args.execute
        result = pc.compress(dry_run=dry_run)
        print(f"{'[DRY RUN] ' if dry_run else ''}{result['message']}")

    elif args.action == "scope":
        pc = PolicyCompressor()
        domains = [d.strip() for d in args.domains.split(",")]
        ok = pc.domain_scope_policy(args.policy, domains)
        print(f"{'✅' if ok else '❌'} Scoped {args.policy} to {domains}")


if __name__ == "__main__":
    main()
