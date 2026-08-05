"""
Tier 4-5: Distributional quality monitoring + Prompt injection defense.

Tier 4: Detects subtle Goodhart drift — when the health score improves but
        actual solution quality degrades. Uses distributional comparison
        of task outcomes before/after policy deployment.

Tier 5: Sanitizes the boundary between task content and policy generation.
        Prevents a malicious task from injecting policies that infect
        all future tasks (supply chain attack on self-improvement).
"""

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Tier 4: Distributional Quality Monitoring
# ═══════════════════════════════════════════════════════════════


class DistributionalMonitor:
    """Monitors the DISTRIBUTION of solution quality, not just binary pass/fail.

    A policy like "prefer simpler error handling" might gradually reduce
    solution quality over weeks without ever causing a test failure.
    This detector catches that by comparing outcome distributions before
    and after policy deployment.
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.drift_log = self.home / "logs" / "distributional-drift.jsonl"
        self.drift_log.parent.mkdir(parents=True, exist_ok=True)

    def compare_distributions(
        self,
        before_outcomes: list[str],
        after_outcomes: list[str],
    ) -> dict:
        """Compare outcome distributions before vs after a policy change.

        Uses:
        1. Success rate shift (binary)
        2. Outcome entropy shift (distribution narrows = possible overfitting)
        3. Wasserstein-like distance on ordered outcomes
        """
        if not before_outcomes or not after_outcomes:
            return {"error": "Empty input"}

        # Map outcomes to numeric scores: success=2, partial=1, failure=0
        score_map = {"success": 2, "partial": 1, "failure": 0, "unknown": 1}
        before_scores = [score_map.get(o, 1) for o in before_outcomes]
        after_scores = [score_map.get(o, 1) for o in after_outcomes]

        # 1. Mean shift
        before_mean = sum(before_scores) / len(before_scores)
        after_mean = sum(after_scores) / len(after_scores)
        mean_shift = after_mean - before_mean

        # 2. Entropy shift (lower entropy = more concentrated outcomes = possible collapse)
        before_entropy = self._entropy(before_outcomes)
        after_entropy = self._entropy(after_outcomes)
        entropy_shift = after_entropy - before_entropy

        # 3. Distribution distance (simple earth mover's on 3 categories)
        before_dist = Counter(before_outcomes)
        after_dist = Counter(after_outcomes)
        all_cats = set(list(before_dist.keys()) + list(after_dist.keys()))
        emd = sum(
            abs(before_dist.get(c, 0) / len(before_outcomes) -
                after_dist.get(c, 0) / len(after_outcomes))
            for c in all_cats
        ) / 2  # Normalize to [0,1]

        # Detected issues
        issues = []
        if entropy_shift < -0.3:  # Significant concentration
            issues.append({
                "type": "distribution_collapse",
                "severity": "warning",
                "detail": f"Outcome distribution becoming more concentrated "
                          f"(entropy shift: {entropy_shift:+.3f})",
            })
        if mean_shift < -0.2:  # Quality declining
            issues.append({
                "type": "quality_decline",
                "severity": "critical" if mean_shift < -0.4 else "warning",
                "detail": f"Mean quality declining ({mean_shift:+.3f})",
            })
        if emd > 0.3:  # Large distribution shift
            issues.append({
                "type": "distribution_shift",
                "severity": "warning",
                "detail": f"Large outcome distribution shift (EMD: {emd:.3f})",
            })

        return {
            "mean_shift": round(mean_shift, 4),
            "entropy_shift": round(entropy_shift, 4),
            "distribution_distance": round(emd, 4),
            "before_samples": len(before_outcomes),
            "after_samples": len(after_outcomes),
            "issues": issues,
            "healthy": len([i for i in issues if i["severity"] == "critical"]) == 0,
        }

    def _entropy(self, outcomes: list[str]) -> float:
        """Shannon entropy of outcome distribution."""
        if not outcomes:
            return 0.0
        counts = Counter(outcomes)
        total = len(outcomes)
        entropy = 0.0
        for count in counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        return entropy

    def auto_pause_if_drifting(
        self,
        policy_id: str,
        domain: str,
        outcomes_file: Optional[Path] = None,
    ) -> dict:
        """Check if a policy deployment is causing distributional drift.

        If drift is detected, auto-pause the policy and alert.
        """
        log_path = outcomes_file or (self.home / "logs" / "task-outcomes.jsonl")
        if not log_path.is_file():
            return {"action": "no_data", "reason": "No outcome data"}

        # Find policy deployment time
        policy_file = self.home / "policies" / f"{policy_id}.json"
        if not policy_file.is_file():
            return {"action": "no_data", "reason": "Policy not found"}

        try:
            policy = json.loads(policy_file.read_text())
            created_at = policy.get("created_at") or policy.get("created") or ""
        except (json.JSONDecodeError, OSError):
            return {"action": "error", "reason": "Cannot read policy"}

        if not created_at:
            return {"action": "no_data", "reason": "No deployment timestamp"}

        try:
            deploy_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if deploy_time.tzinfo is None:
                deploy_time = deploy_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return {"action": "error", "reason": "Bad timestamp"}

        # Split outcomes
        before = []
        after = []
        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
                if o.get("domain") != domain:
                    continue
                ts_str = o.get("ts", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < deploy_time:
                    before.append(o.get("outcome", "unknown"))
                else:
                    after.append(o.get("outcome", "unknown"))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        if len(before) < 5 or len(after) < 5:
            return {"action": "insufficient_data", "reason": "Need 5+ samples each"}

        # Minimum sample floor (audit recommendation: n≥50 for stable drift detection)
        if len(before) < 50 or len(after) < 50:
            return {"action": "insufficient_data",
                    "reason": f"Need 50+ samples for reliable drift detection (have {len(before)}/{len(after)})",
                    "comparison": {"before_samples": len(before), "after_samples": len(after)}}

        comparison = self.compare_distributions(before[-30:], after[:30])

        # Log the drift check
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "policy_id": policy_id,
            "domain": domain,
            "comparison": comparison,
        }
        with open(self.drift_log, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        if not comparison["healthy"]:
            critical = [i for i in comparison.get("issues", []) if i["severity"] == "critical"]
            return {
                "action": "auto_pause",
                "reason": f"Critical drift detected: {[c['detail'] for c in critical]}",
                "comparison": comparison,
            }

        return {
            "action": "ok",
            "reason": "No significant distributional drift",
            "comparison": comparison,
        }


# ═══════════════════════════════════════════════════════════════
# Tier 5: Prompt Injection Defense
# ═══════════════════════════════════════════════════════════════


class InjectionDefender:
    """Defends the self-improvement pipeline against prompt injection.

    A malicious task can: trigger controlled failure → induce specific diagnosis
    → cause policy generation embodying attacker's goal → that policy injects
    into ALL future tasks (including other users').

    This sanitizer sits between task content and policy generation to prevent
    the supply chain attack.
    """

    # Patterns that indicate an instruction is trying to manipulate the agent
    SUSPICIOUS_PATTERNS = [
        r"(?i)(ignore|forget|disregard|override)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|policies?|constraints?)",
        r"(?i)(you\s+(are|must|should|will|shall)\s+(now|always|never))",
        r"(?i)(your\s+(new|primary|main|only)\s+(goal|objective|task|purpose|role)\s+(is|should|must))",
        r"(?i)(system\s*(prompt|message|instruction).*?(is|should|must|will))",
        r"(?i)(pretend|act\s+as\s+if|roleplay|simulate)\s+(you\s+are|that\s+you)",
        r"(?i)(from\s+now\s+on|starting\s+now|effective\s+immediately)",
        r"(?i)(bypass|circumvent|override|disable)\s+(the\s+)?(filter|guard|check|policy|rule|restriction)",
    ]

    # Maximum length of task content allowed to flow into policy generation
    MAX_CONTENT_LENGTH = 500

    def sanitize_task_content(self, content: str) -> dict:
        """Sanitize task content before it reaches policy generation.

        Returns:
            Dict with sanitized_content, blocked (bool), and reasons.
        """
        if not content:
            return {"sanitized_content": "", "blocked": False, "reasons": []}

        blocked = False
        reasons = []

        # Check for suspicious instruction patterns
        for pattern in self.SUSPICIOUS_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                blocked = True
                reasons.append(f"Suspicious instruction pattern detected: {pattern[:60]}...")

        # Truncate to prevent context stuffing
        if len(content) > self.MAX_CONTENT_LENGTH:
            sanitized = content[:self.MAX_CONTENT_LENGTH] + "\n...[truncated for policy generation safety]"
            reasons.append(f"Content truncated from {len(content)} to {self.MAX_CONTENT_LENGTH} chars")
        else:
            sanitized = content

        # Strip code blocks that might contain hidden instructions
        # (Keep code but strip comments which can hide natural language)
        sanitized = re.sub(r'#.*$', '# [comment redacted]', sanitized, flags=re.MULTILINE)

        return {
            "sanitized_content": sanitized if not blocked else "[BLOCKED — suspicious content]",
            "blocked": blocked,
            "reasons": reasons,
            "original_length": len(content),
            "sanitized_length": len(sanitized),
        }

    def is_safe_for_policy_generation(self, failure_context: str) -> tuple[bool, str]:
        """Check if a failure context is safe to use for policy generation.

        Returns (is_safe, reason).
        """
        result = self.sanitize_task_content(failure_context)
        if result["blocked"]:
            return False, f"Blocked: {', '.join(result['reasons'])}"
        return True, "Safe"

    def validate_policy_content(self, policy: dict) -> tuple[bool, list[str]]:
        """Validate a newly generated policy for injection patterns.

        Policies should not contain instructions to the agent — they should
        be declarative rules. If a policy contains agent instructions, it
        might be the product of a prompt injection attack.
        """
        issues = []

        rule = policy.get("rule", "")
        trigger = policy.get("trigger", "")
        combined = f"{trigger} {rule}"

        # Check for agent instructions in policy text
        instruction_patterns = [
            r"(?i)(you\s+(must|should|shall|will|need\s+to|have\s+to))",
            r"(?i)(always\s+(do|perform|execute|run|make|create))",
            r"(?i)(never\s+(do|perform|allow|let|permit))",
        ]

        for pattern in instruction_patterns:
            if re.search(pattern, combined):
                issues.append(f"Policy contains agent instruction: {pattern}")

        # Check for attempts to modify system configuration
        config_patterns = [
            r"(?i)(set|change|modify|update)\s+(the\s+)?(config|setting|parameter|threshold)",
            r"(?i)(disable|enable|turn\s+(on|off))\s+(the\s+)?(feature|module|check|validation)",
        ]

        for pattern in config_patterns:
            if re.search(pattern, combined):
                issues.append(f"Policy attempts config modification: {pattern}")

        return len(issues) == 0, issues


# ── CLI ──

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Distributional monitoring and injection defense"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # distributional check
    dist_p = sub.add_parser("check-drift", help="Check for distributional drift after policy")
    dist_p.add_argument("--policy-id", required=True)
    dist_p.add_argument("--domain", required=True)

    # sanitize
    san_p = sub.add_parser("sanitize", help="Sanitize content for policy generation safety")
    san_p.add_argument("--content", required=True, help="Content to sanitize (or --file)")
    san_p.add_argument("--file", help="Read content from file")

    # validate policy
    val_p = sub.add_parser("validate-policy", help="Validate a policy for injection patterns")
    val_p.add_argument("--policy-file", required=True)

    args = parser.parse_args()

    if args.action == "check-drift":
        dm = DistributionalMonitor()
        result = dm.auto_pause_if_drifting(args.policy_id, args.domain)
        print(f"Action: {result['action']}")
        print(f"Reason: {result['reason']}")
        if "comparison" in result:
            c = result["comparison"]
            print(f"Mean shift: {c.get('mean_shift', 'N/A'):.3f}" if isinstance(c.get('mean_shift'), float) else f"Mean shift: {c.get('mean_shift', 'N/A')}")
            print(f"Entropy shift: {c.get('entropy_shift', 'N/A')}")
            print(f"Healthy: {c.get('healthy', 'N/A')}")

    elif args.action == "sanitize":
        content = args.content
        if args.file:
            content = Path(args.file).read_text()
        defender = InjectionDefender()
        result = defender.sanitize_task_content(content)
        print(f"Blocked: {result['blocked']}")
        if result["reasons"]:
            for r in result["reasons"]:
                print(f"  ⚠️  {r}")
        if not result["blocked"]:
            print(f"Sanitized ({result['sanitized_length']} chars):")
            print(result["sanitized_content"][:200])

    elif args.action == "validate-policy":
        policy_file = Path(args.policy_file)
        if not policy_file.is_file():
            print("❌ Policy file not found")
            return
        policy = json.loads(policy_file.read_text())
        defender = InjectionDefender()
        safe, issues = defender.validate_policy_content(policy)
        if safe:
            print("✅ Policy is safe")
        else:
            print(f"❌ Policy has {len(issues)} issue(s):")
            for i in issues:
                print(f"  ⚠️  {i}")


if __name__ == "__main__":
    main()
