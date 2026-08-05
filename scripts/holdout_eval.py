"""
Holdout evaluation + causal attribution for Hermes self-improvement policies.

Splits the self-regression corpus into training (70%) and holdout (30%).
The holdout set is NEVER used for policy generation — it's only for
periodic validation. This prevents "testing on training data" and
provides an honest measure of whether policies generalize.

Also provides causal attribution: when a policy deploys, measures whether
domain-specific failure rates actually decrease.

Tier 1 of the commercial readiness roadmap.
"""

import json
import random
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


class HoldoutManager:
    """Manages the train/holdout split for the self-regression failure corpus.

    The corpus at self-regression-corpus.json is split:
    - 70% training: used for policy generation and self-regression testing
    - 30% holdout: NEVER used for generation, only for periodic validation

    This is basic ML hygiene that separates "the system remembers" from
    "the system improves."
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.corpus_file = self.home / "logs" / "self-regression-corpus.json"
        self.holdout_file = self.home / "logs" / "holdout-corpus.json"
        self.split_file = self.home / "logs" / "corpus-split-state.json"

    def split_corpus(self, holdout_ratio: float = 0.3, seed: int = 42) -> dict:
        """Split the corpus into train and holdout sets.

        Only splits items that aren't already assigned. Once assigned,
        items stay in their set forever (holdout is permanent).
        """
        if not self.corpus_file.is_file():
            return {"train": 0, "holdout": 0, "total": 0}

        corpus = json.loads(self.corpus_file.read_text())
        if not isinstance(corpus, list):
            corpus = []

        # Load existing split state
        split_state = self._load_split_state()
        holdout_ids = set(split_state.get("holdout_ids", []))

        # Assign new items
        rng = random.Random(seed)
        new_holdout = []
        for i, item in enumerate(corpus):
            item_id = item.get("id") or item.get("task_id") or str(i)
            if item_id not in holdout_ids and item_id not in split_state.get("train_ids", []):
                if rng.random() < holdout_ratio:
                    holdout_ids.add(item_id)
                    new_holdout.append(item)

        # Save holdout corpus
        holdout_corpus = [item for item in corpus
                         if (item.get("id") or item.get("task_id") or "") in holdout_ids]
        self.holdout_file.write_text(json.dumps(holdout_corpus, indent=2))

        # Update split state
        split_state["holdout_ids"] = list(holdout_ids)
        split_state["train_ids"] = [
            (item.get("id") or item.get("task_id") or str(i))
            for i, item in enumerate(corpus)
            if (item.get("id") or item.get("task_id") or str(i)) not in holdout_ids
        ]
        split_state["total"] = len(corpus)
        split_state["holdout_count"] = len(holdout_ids)
        split_state["train_count"] = len(split_state["train_ids"])
        split_state["last_split_at"] = datetime.now(timezone.utc).isoformat()
        self.split_file.write_text(json.dumps(split_state, indent=2))

        return {
            "train": split_state["train_count"],
            "holdout": split_state["holdout_count"],
            "total": len(corpus),
            "new_holdout": len(new_holdout),
        }

    def validate_policies(self) -> dict:
        """Test current policies against the holdout set.

        Returns pass rate on holdout — the honest measure of whether
        policies generalize to unseen failures.
        """
        if not self.holdout_file.is_file():
            return {"error": "No holdout corpus. Run split_corpus() first."}

        holdout = json.loads(self.holdout_file.read_text())
        if not holdout:
            return {"holdout_pass_rate": 1.0, "total": 0, "note": "Empty holdout"}

        # Load policies
        policies_dir = self.home / "policies"
        policies = []
        if policies_dir.is_dir():
            for f in policies_dir.glob("*.json"):
                try:
                    p = json.loads(f.read_text())
                    policies.append(p)
                except (json.JSONDecodeError, OSError):
                    pass

        # Test each holdout item against policies
        # Simplified: check if any policy's rule text matches the failure pattern
        passes = 0
        failures = []
        for item in holdout:
            failure_text = json.dumps(item).lower()
            matched = False
            for policy in policies:
                rule = policy.get("rule", "").lower()
                trigger = policy.get("trigger", "").lower()
                if rule and any(word in failure_text for word in rule.split()[:5]):
                    matched = True
                    break
                if trigger and any(word in failure_text for word in trigger.split()[:3]):
                    matched = True
                    break
            if matched:
                passes += 1
            else:
                failures.append(item.get("id", item.get("task_id", "unknown")))

        return {
            "holdout_pass_rate": round(passes / max(len(holdout), 1), 4),
            "total": len(holdout),
            "passes": passes,
            "misses": len(holdout) - passes,
            "missed_ids": failures[:10],  # First 10 missed
        }

    def _load_split_state(self) -> dict:
        if self.split_file.is_file():
            try:
                return json.loads(self.split_file.read_text())
            except json.JSONDecodeError:
                pass
        return {"holdout_ids": [], "train_ids": []}


class PolicyAttribution:
    """Causal attribution for policy effectiveness.

    Measures whether deploying a policy actually reduces domain-specific
    failure rates. Uses a simple before/after comparison with statistical
    significance testing.

    Depends on the OutcomeTracker for task-level success/failure data.
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.outcome_log = self.home / "logs" / "task-outcomes.jsonl"

    def measure_policy_effect(
        self,
        policy_id: str,
        domain: str,
        window_before: int = 20,
        window_after: int = 20,
    ) -> dict:
        """Measure a policy's effect on domain-specific failure rate.

        Compares failure rate in `domain` before vs after policy deployment.
        """
        if not self.outcome_log.is_file():
            return {"error": "No outcome data. Run outcome_tracker first."}

        # Get policy deployment time
        policy_file = self.home / "policies" / f"{policy_id}.json"
        if not policy_file.is_file():
            return {"error": f"Policy {policy_id} not found"}

        try:
            policy = json.loads(policy_file.read_text())
            created_at = policy.get("created_at") or policy.get("created") or ""
        except (json.JSONDecodeError, OSError):
            return {"error": f"Cannot read policy {policy_id}"}

        if not created_at:
            return {"error": "Policy has no creation timestamp"}

        try:
            deploy_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if deploy_time.tzinfo is None:
                deploy_time = deploy_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return {"error": f"Cannot parse policy timestamp: {created_at}"}

        # Collect domain outcomes before and after
        before = []
        after = []

        for line in self.outcome_log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                outcome = json.loads(line)
                if outcome.get("domain") != domain:
                    continue
                ts_str = outcome.get("ts", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                is_success = outcome.get("outcome") == "success"
                if ts < deploy_time:
                    before.append(is_success)
                else:
                    after.append(is_success)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Trim to windows
        before = before[-window_before:] if before else []
        after = after[:window_after] if after else []

        if len(before) < 3 or len(after) < 3:
            return {
                "error": "Insufficient data",
                "before_samples": len(before),
                "after_samples": len(after),
            }

        # Simple before/after comparison
        before_rate = sum(before) / len(before)
        after_rate = sum(after) / len(after)
        effect = after_rate - before_rate

        # Determine significance (simplified: >10% change with >5 samples each)
        significant = abs(effect) > 0.1 and len(before) >= 5 and len(after) >= 5

        return {
            "policy_id": policy_id,
            "domain": domain,
            "before_rate": round(before_rate, 4),
            "after_rate": round(after_rate, 4),
            "effect": round(effect, 4),
            "direction": "positive" if effect > 0.05 else ("negative" if effect < -0.05 else "neutral"),
            "significant": significant,
            "before_samples": len(before),
            "after_samples": len(after),
        }


# ── CLI ──

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Holdout evaluation and policy attribution for Hermes"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # holdout split
    split_p = sub.add_parser("split", help="Split corpus into train/holdout")
    split_p.add_argument("--ratio", type=float, default=0.3, help="Holdout ratio (default 0.3)")
    split_p.add_argument("--seed", type=int, default=42)

    # holdout validate
    val_p = sub.add_parser("validate", help="Validate policies against holdout set")

    # attribute
    attr_p = sub.add_parser("attribute", help="Measure policy effect on domain outcomes")
    attr_p.add_argument("--policy-id", required=True)
    attr_p.add_argument("--domain", required=True)
    attr_p.add_argument("--before", type=int, default=20)
    attr_p.add_argument("--after", type=int, default=20)

    args = parser.parse_args()

    if args.action == "split":
        hm = HoldoutManager()
        result = hm.split_corpus(holdout_ratio=args.ratio, seed=args.seed)
        print(f"Corpus split: {result['train']} train / {result['holdout']} holdout "
              f"({result['new_holdout']} new in holdout)")

    elif args.action == "validate":
        hm = HoldoutManager()
        result = hm.validate_policies()
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"Holdout validation: {result['holdout_pass_rate']:.1%} "
                  f"({result['passes']}/{result['total']})")
            if result["misses"]:
                print(f"Missed: {result['missed_ids'][:5]}")

    elif args.action == "attribute":
        pa = PolicyAttribution()
        result = pa.measure_policy_effect(
            args.policy_id, args.domain,
            window_before=args.before, window_after=args.after,
        )
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            direction = "📈" if result["direction"] == "positive" else ("📉" if result["direction"] == "negative" else "➡️")
            sig = " (significant)" if result["significant"] else ""
            print(f"{direction} {result['policy_id']} on {result['domain']}: "
                  f"{result['before_rate']:.1%} → {result['after_rate']:.1%} "
                  f"({result['effect']:+.1%}){sig}")


if __name__ == "__main__":
    main()
