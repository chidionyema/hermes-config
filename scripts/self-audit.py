#!/usr/bin/env python3
"""
self-audit.py — Weekly self-audit: "What could I have prevented?"

Phase 3 of recursive self-improvement. Runs weekly (Sunday 6pm).
Reviews the past week's failures and asks:
1. Which failures could existing policies have prevented?
2. Which failures had no policy coverage? (gap)
3. How effective were the policies that DID fire?
4. What should I learn from this week?

Output goes to ~/.hermes/logs/self-audit/YYYY-MM-DD.md and is also
injected into the daily reflection so Otto sees its own performance.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
POLICIES_DIR = HERMES_HOME / "policies"
FIRINGS_LOG = HERMES_HOME / "logs" / "policy-firings.jsonl"
INJECTION_LOG = HERMES_HOME / "logs" / "injection-log.jsonl"
OPS_LOG = HERMES_HOME / "logs" / "ops-monitor.jsonl"
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
AUDIT_DIR = HERMES_HOME / "logs" / "self-audit"
REFLECTION_DIR = HERMES_HOME / "logs" / "reflection"


def load_jsonl(path: Path, since_hours: int = 168) -> list:
    """Load JSONL entries from the last N hours."""
    if not path.is_file():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    entries = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("ts") or entry.get("timestamp") or ""
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return entries


def analyze_policy_effectiveness() -> dict:
    """How effective were policies this week?"""
    firings = load_jsonl(FIRINGS_LOG, since_hours=168)
    injections = load_jsonl(INJECTION_LOG, since_hours=168)
    ops = load_jsonl(OPS_LOG, since_hours=168)

    # Policy firings by policy
    firing_counts = Counter()
    for f in firings:
        firing_counts[f.get("policy_id", "unknown")] += 1

    # Injection stats
    total_injections = len(injections)
    injections_with_policies = sum(
        1 for i in injections if i.get("relevant_policies_count", i.get("active_policies_count", 0)) > 0
    )
    avg_retrieved = (
        sum(i.get("retrieved_count", 0) for i in injections) / max(total_injections, 1)
    )

    # Ops monitor actions
    ops_actions = [o for o in ops if o.get("type") in ("moat_auto_pause", "policy_proposed")]
    auto_pauses = sum(1 for o in ops_actions if o.get("type") == "moat_auto_pause")
    policies_proposed = sum(1 for o in ops_actions if o.get("type") == "policy_proposed")

    return {
        "total_firings": len(firings),
        "firings_by_policy": dict(firing_counts),
        "total_injections": total_injections,
        "injections_with_policies": injections_with_policies,
        "injection_relevance_pct": (
            round(injections_with_policies / max(total_injections, 1) * 100, 1)
        ),
        "avg_memory_retrieved": round(avg_retrieved, 1),
        "auto_pauses": auto_pauses,
        "policies_proposed": policies_proposed,
    }


def analyze_failure_patterns() -> dict:
    """What failed this week that policies should have caught?"""
    errors = load_jsonl(ERROR_LOG, since_hours=168)
    alerts = load_jsonl(ALERT_LOG, since_hours=168)

    # Categorize errors
    categories = Counter()
    for e in errors:
        msg = str(e.get("message", "") or "").lower()
        if "credit" in msg or "429" in msg or "402" in msg:
            categories["api_credits"] += 1
        elif "moat" in msg or "preflight" in msg:
            categories["prospector_moat"] += 1
        elif "cron" in msg:
            categories["cron_failures"] += 1
        elif "connection" in msg or "timeout" in msg:
            categories["network"] += 1
        elif "ssl" in msg or "certificate" in msg:
            categories["ssl_cert"] += 1
        else:
            categories["other"] += 1

    # Check if existing policies cover these categories
    existing_policy_domains = set()
    if POLICIES_DIR.is_dir():
        for f in POLICIES_DIR.iterdir():
            if f.suffix == ".json":
                try:
                    p = json.loads(f.read_text())
                    scope = p.get("scope", {})
                    domain = scope.get("domain", "")
                    if domain:
                        existing_policy_domains.add(domain)
                except Exception:
                    pass

    uncovered = []
    cat_to_domain = {
        "api_credits": "operations/monitoring",
        "prospector_moat": "operations/monitoring",
        "cron_failures": "operations/monitoring",
        "network": "operations/infra",
        "ssl_cert": "operations/infra",
    }

    for cat, count in categories.most_common():
        domain = cat_to_domain.get(cat, "other")
        covered = any(domain in d for d in existing_policy_domains)
        if count >= 3 and not covered:
            uncovered.append({"category": cat, "count": count, "domain": domain})

    return {
        "total_errors": len(errors),
        "categories": dict(categories.most_common(10)),
        "uncovered_failures": uncovered,
        "alert_count": len(alerts),
    }


def generate_audit() -> str:
    """Generate the weekly self-audit report."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    effectiveness = analyze_policy_effectiveness()
    failures = analyze_failure_patterns()

    lines = [
        f"# Otto Self-Audit — Week of {week_start.strftime('%Y-%m-%d')}",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 1. Policy Effectiveness",
        "",
        f"- Policy firings: **{effectiveness['total_firings']}**",
        f"- Injections with relevant policies: **{effectiveness['injections_with_policies']}** / {effectiveness['total_injections']} ({effectiveness['injection_relevance_pct']}%)",
        f"- Avg memory entries retrieved per injection: **{effectiveness['avg_memory_retrieved']}**",
        f"- Auto-pauses triggered: **{effectiveness['auto_pauses']}**",
        f"- Policies auto-proposed: **{effectiveness['policies_proposed']}**",
    ]

    if effectiveness["firings_by_policy"]:
        lines.append("")
        lines.append("### Firings by policy:")
        for pid, count in sorted(effectiveness["firings_by_policy"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{pid}`: {count}×")

    lines += [
        "",
        "## 2. Failure Patterns",
        "",
        f"- Total errors logged: **{failures['total_errors']}**",
        f"- Watchdog alerts: **{failures['alert_count']}**",
        "",
        "### Error categories:",
    ]
    for cat, count in failures["categories"].items():
        emoji = "🔴" if count > 10 else ("🟡" if count > 3 else "🟢")
        lines.append(f"- {emoji} {cat}: {count}")

    if failures["uncovered_failures"]:
        lines += [
            "",
            "### ⚠️ Uncovered — no policy exists for these:",
        ]
        for uf in failures["uncovered_failures"]:
            lines.append(f"- {uf['category']}: {uf['count']} occurrences — needs policy in `{uf['domain']}`")

    lines += [
        "",
        "## 3. Learning",
        "",
        "### What I should learn from this week:",
    ]

    # Auto-generate learnings based on the data
    if effectiveness["injection_relevance_pct"] < 50:
        lines.append("- Policy injection relevance is low — need better keyword matching or tagging")
    if effectiveness["avg_memory_retrieved"] < 1:
        lines.append("- Memory retrieval returns near-zero — MEMORY.md entries need [tags:] markers")
    if failures["uncovered_failures"]:
        lines.append(f"- {len(failures['uncovered_failures'])} failure types have no policy coverage")
    if effectiveness["auto_pauses"] > 0:
        lines.append(f"- Auto-pause triggered {effectiveness['auto_pauses']}× — moat instability is recurring")
    if effectiveness["policies_proposed"] > 0:
        lines.append(f"- {effectiveness['policies_proposed']} new policies proposed — system is self-improving")
    if not effectiveness["firings_by_policy"]:
        lines.append("- ⚠️ ZERO policy firings this week — policy enforcer may not be running or matching")

    lines += [
        "",
        "### Improvement plan for next week:",
    ]
    if effectiveness["avg_memory_retrieved"] < 1:
        lines.append("1. Tag MEMORY.md entries so retrieval can match them")
    if effectiveness["injection_relevance_pct"] < 50:
        lines.append("2. Improve policy-to-task keyword matching in memory_retrieval.py")
    if failures["uncovered_failures"]:
        domains = set(uf["domain"] for uf in failures["uncovered_failures"])
        lines.append(f"3. Create policies for uncovered domains: {', '.join(domains)}")
    lines.append("4. Verify idle-learning pipeline runs end-to-end with --harvest + --report")

    audit_text = "\n".join(lines)

    # Write to audit file
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = AUDIT_DIR / f"{now.strftime('%Y-%m-%d')}.md"
    audit_path.write_text(audit_text)

    return audit_text


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weekly self-audit")
    parser.add_argument("--force", action="store_true", help="Run even if not Sunday")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if not args.force and now.weekday() != 6:
        print("Self-audit runs on Sundays. Use --force to run now.")
        return

    audit = generate_audit()
    print(audit)


if __name__ == "__main__":
    main()
