#!/usr/bin/env python3
"""Estate Optimization Scanner — reads all analysis outputs from the
self-improvement pipeline and produces ranked, actionable recommendations.

Sources:
  - Meta-improver bottleneck reports (~/.hermes/logs/meta-improver/bottleneck-*.json)
  - Near-miss analysis (~/.hermes/logs/maintenance/near-miss-*.json)
  - Improvement pulse ideas (~/.hermes/logs/improvement-pulse/ideas.md)
  - Watchdog alert log (~/.hermes/logs/alerts/watchdog.jsonl)
  - Trend analysis (~/.hermes/logs/trends/trend-*.json)
  - Policy firing log (~/.hermes/logs/policy-firings.jsonl)
  - Estate drift report (~/.hermes/reports/estate-drift.md)

Output: ~/.hermes/reports/estate-optimization.md
"""

import json, os, glob
from datetime import datetime, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
REPORT_PATH = HERMES_HOME / "reports" / "estate-optimization.md"

def read_bottlenecks():
    """Read latest bottleneck reports and extract recommendations."""
    bottlenecks = []
    files = sorted((HERMES_HOME / "logs" / "meta-improver").glob("bottleneck-*.json"))
    for f in files[-5:]:  # last 5
        try:
            with open(f) as fh:
                data = json.load(fh)
            phase = data.get("metrics", {}).get("slowest_phase", data.get("bottleneck_phase", "?"))
            latency = data.get("metrics", {}).get("phase_latency", {})
            suggestions = []
            # Extract any improvement suggestions
            for k, v in data.items():
                if "suggest" in k.lower() or "fix" in k.lower() or "recommend" in k.lower():
                    suggestions.append(str(v)[:100])
            bottlenecks.append({
                "file": f.name,
                "timestamp": data.get("timestamp", "?"),
                "phase": phase,
                "latency": latency,
                "suggestions": suggestions,
                "raw_data": data,
            })
        except (json.JSONDecodeError, OSError) as e:
            pass
    return bottlenecks

def read_near_misses():
    """Read latest near-miss analysis."""
    files = sorted((HERMES_HOME / "logs" / "maintenance").glob("near-miss-*.json"))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except:
        return None

def read_watchdog_alerts():
    """Read recent watchdog alerts with proper type extraction."""
    alerts = []
    log = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
    if not log.exists():
        return alerts
    with open(log) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                # Skip summary entries, keep individual typed alerts
                if entry.get("type") not in ("watchdog_summary",):
                    alerts.append(entry)
            except:
                pass
    return alerts[-20:]  # last 20 typed alerts

def read_trends():
    """Read latest trend analysis."""
    files = sorted((HERMES_HOME / "logs" / "trends").glob("trend-*.json"))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except:
        return None

def read_policy_firings():
    """Read policy firing stats."""
    log = HERMES_HOME / "logs" / "policy-firings.jsonl"
    if not log.exists():
        return None
    firings = {}
    with open(log) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                pid = entry.get("policy_id", "?")
                firings.setdefault(pid, {"count": 0, "domains": set()})
                firings[pid]["count"] += 1
                if "context" in entry:
                    firings[pid]["domains"].add(entry.get("context", {}).get("domain", "?"))
            except:
                pass
    return firings

def analyze_bottlenecks(bottlenecks):
    """Produce recommendations from bottleneck data."""
    recs = []
    if not bottlenecks:
        return recs
    
    # Check if same phase is repeatedly slow
    phase_counts = {}
    for b in bottlenecks:
        p = b.get("phase", "?")
        phase_counts[p] = phase_counts.get(p, 0) + 1
    
    for phase, count in sorted(phase_counts.items(), key=lambda x: -x[1]):
        if count >= 2 and phase != "?":
            recs.append({
                "priority": "high" if count >= 3 else "medium",
                "category": "bottleneck",
                "message": f"Phase '{phase}' identified as bottleneck in {count}/{len(bottlenecks)} reports",
                "detail": f"Consider parallelizing or optimizing {phase}",
                "action": f"investigate_{phase.replace('-', '_')}",
            })
    
    return recs

def analyze_near_misses(nm):
    """Produce recommendations from near-miss data."""
    recs = []
    if not nm:
        return recs
    
    untriggered = nm.get("untriggered_policies", [])
    if len(untriggered) > 3:
        recs.append({
            "priority": "medium",
            "category": "policy_staleness",
            "message": f"{len(untriggered)} policies have never triggered",
            "detail": "Consider archiving or rewriting: " + ", ".join(
                p.get("policy_id", "?") for p in untriggered[:5]
            ),
            "action": "archive_dead_policies",
        })
    
    # Read actual policy files to check for escalation chains before flagging overlap
    policy_dir = HERMES_HOME / "policies"
    escalation_chains = {}  # domain -> list of policy ids with escalates_to
    for fname in sorted(policy_dir.glob("*.json")):
        try:
            with open(fname) as f:
                p = json.load(f)
            domain = p.get("scope", {}).get("domain", "uncategorized")
            if p.get("escalates_to") or p.get("supersedes"):
                escalation_chains.setdefault(domain, []).append(p.get("id", "?"))
        except:
            pass
    
    co_firing = nm.get("co_firing_contexts", [])
    # Filter out co-firing contexts that are escalation chains
    actual_overlap = []
    for ctx in co_firing:
        domain = None
        if isinstance(ctx, dict):
            ctx_inner = ctx.get("context", None)
            if isinstance(ctx_inner, dict):
                domain = ctx_inner.get("domain", None)
        # If it's a string or unknown, include as potential genuine overlap
        if not domain or domain not in escalation_chains:
            actual_overlap.append(ctx)
    
    if len(actual_overlap) > 2:
        recs.append({
            "priority": "medium",
            "category": "policy_overlap",
            "message": f"{len(actual_overlap)} contexts detected with multiple policies firing together (unrelated to escalation chains)",
            "detail": "These policies may genuinely overlap — consider merging or clarifying scope",
            "action": "consolidate_overlapping_policies",
        })
    
    return recs

def analyze_trends(trend):
    """Produce recommendations from trend data."""
    recs = []
    if not trend:
        return recs
    
    recurring = trend.get("recurring_patterns", [])
    suggested = trend.get("suggested_improvements", [])
    
    for p in recurring[:3]:
        recs.append({
            "priority": "medium",
            "category": "recurring_pattern",
            "message": f"Recurring pattern: {p.get('description', str(p)[:80])}",
            "detail": f"Occurred {p.get('count', '?')} times — consider automating this",
            "action": f"automate_{p.get('label', 'pattern')}",
        })
    
    for s in suggested[:3]:
        recs.append({
            "priority": "info",
            "category": "suggested_improvement",
            "message": str(s)[:100],
            "detail": "",
            "action": "review_suggestion",
        })
    
    # Outcome velocity
    vel = trend.get("outcome_velocity_per_day", 0)
    if vel == 0:
        recs.append({
            "priority": "high",
            "category": "no_outcomes",
            "message": "Outcome velocity is 0 — the outer loop has no training data",
            "detail": "Task outcomes need to be evaluated. Run outcome-evaluator to seed the loop.",
            "action": "seed_outcomes",
        })
    elif vel < 1:
        recs.append({
            "priority": "medium",
            "category": "low_velocity",
            "message": f"Outcome velocity is low ({vel:.1f}/day)",
            "detail": "The meta-improver has insufficient data to learn from",
            "action": "accelerate_outcomes",
        })
    
    # Domain coverage
    domain_growth = trend.get("corpus_domain_growth", {})
    if domain_growth:
        all_domains = set()
        for day, doms in domain_growth.items():
            all_domains.update(doms)
        if len(all_domains) < 3:
            recs.append({
                "priority": "medium",
                "category": "narrow_coverage",
                "message": f"Policy domain coverage is narrow ({len(all_domains)} domains)",
                "detail": f"Domains covered: {', '.join(sorted(all_domains))}",
                "action": "expand_domain_coverage",
            })
    
    return recs

def analyze_watchdog(watchdog_alerts):
    """Produce recommendations from watchdog alerts."""
    recs = []
    if not watchdog_alerts:
        return recs
    
    alert_types = {}
    for a in watchdog_alerts:
        at = a.get("type", "UNKNOWN")
        alert_types[at] = alert_types.get(at, 0) + 1
    
    for atype, count in sorted(alert_types.items(), key=lambda x: -x[1]):
        if count >= 3:
            recs.append({
                "priority": "high",
                "category": "recurring_alert",
                "message": f"Alert type '{atype}' fired {count} times",
                "detail": f"Recurring issue — needs root cause fix, not symptom handling",
                "action": f"fix_recurring_{atype.lower().replace('-', '_')}",
            })
    
    return recs

def analyze_policy_firings(firings):
    """Produce recommendations from policy firing stats."""
    recs = []
    if not firings:
        return recs
    
    high_fire_policies = [(pid, data) for pid, data in firings.items() if data["count"] >= 5]
    for pid, data in high_fire_policies:
        recs.append({
            "priority": "info",
            "category": "high_fire_policy",
            "message": f"Policy {pid} fires frequently ({data['count']} times)",
            "detail": f"Consider if this should be automated or hard-coded",
            "action": f"optimize_policy_{pid}",
        })
    
    zero_fire = [pid for pid, data in firings.items() if data["count"] == 0]
    if len(zero_fire) > 2:
        recs.append({
            "priority": "low",
            "category": "unused_policies",
            "message": f"{len(zero_fire)} policies have 0 firings: {', '.join(zero_fire[:5])}",
            "detail": "Candidates for archival",
            "action": "archive_zero_fire_policies",
        })
    
    return recs

def score_priority(rec):
    """Map priority string to numeric for sorting."""
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(rec.get("priority", "info"), 5)

def generate_report(bottlenecks, nm, trends, watchdog_alerts, firings):
    """Generate the full optimization report."""
    all_recs = []
    all_recs.extend(analyze_bottlenecks(bottlenecks))
    all_recs.extend(analyze_near_misses(nm))
    all_recs.extend(analyze_trends(trends))
    all_recs.extend(analyze_watchdog(watchdog_alerts))
    all_recs.extend(analyze_policy_firings(firings))
    
    all_recs.sort(key=score_priority)
    
    parts = [
        f"# Estate Optimization Report",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Sources:** {len(bottlenecks)} bottleneck reports, {1 if nm else 0} near-miss, {1 if trends else 0} trends, {len(watchdog_alerts)} alerts, {len(firings) if firings else 0} policies\n",
    ]
    
    if not all_recs:
        parts.append("✅ **No optimization opportunities found.** Everything looks clean.")
        parts.append("")
        parts.append("## Data Health")
        parts.append(f"- Meta-improver bottlenecks: {len(bottlenecks)}")
        parts.append(f"- Near-miss analysis: {'✅' if nm else '❌'} available")
        parts.append(f"- Trend data: {'✅' if trends else '❌'} available")
        parts.append(f"- Watchdog alerts: {len(watchdog_alerts)}")
        parts.append(f"- Policy firing data: {'✅' if firings else '❌'} available")
        return "\n".join(parts)
    
    # Group by priority
    priority_groups = {"critical": [], "high": [], "medium": [], "low": [], "info": []}
    for r in all_recs:
        p = r.get("priority", "info")
        priority_groups.get(p, priority_groups["info"]).append(r)
    
    for severity in ["critical", "high", "medium", "low"]:
        group = priority_groups.get(severity, [])
        if group:
            label = {"critical": "🔴 Critical", "high": "🟠 High", "medium": "🟡 Medium", "low": "🔵 Low"}[severity]
            parts.append(f"## {label} Priority")
            for r in group:
                parts.append(f"- **{r['message']}**")
                if r.get("detail"):
                    parts.append(f"  → {r['detail']}")
            parts.append("")
    
    # Action items summary
    parts.append("## Actions Required")
    actions_by_type = {}
    for r in all_recs:
        action = r.get("action", "review")
        actions_by_type.setdefault(action, []).append(r["priority"])
    
    for action, priorities in sorted(actions_by_type.items()):
        highest = sorted(priorities, key=lambda p: {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(p, 5))[0]
        parts.append(f"- [{' ]' if highest in ('info', 'low') else 'x'}] `{action}` — highest priority: {highest}")
    
    # Summary stats
    parts.append("\n## Data Health")
    parts.append(f"- Meta-improver bottlenecks: {len(bottlenecks)}")
    parts.append(f"- Near-miss analysis: {'✅' if nm else '❌'} available")
    parts.append(f"- Trend data: {'✅' if trends else '❌'} available")
    parts.append(f"- Watchdog alerts: {len(watchdog_alerts)}")
    parts.append(f"- Policy firing data: {'✅' if firings else '❌'} available")
    parts.append(f"- **Total recommendations:** {len(all_recs)}")
    
    return "\n".join(parts)

# ── MAIN ──────────────────────────────────────────
if __name__ == "__main__":
    bottlenecks = read_bottlenecks()
    nm = read_near_misses()
    trends = read_trends()
    watchdog_alerts = read_watchdog_alerts()
    firings = read_policy_firings()
    
    report = generate_report(bottlenecks, nm, trends, watchdog_alerts, firings)
    
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    
    print(report)
