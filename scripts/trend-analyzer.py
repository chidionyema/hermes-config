#!/usr/bin/env python3
"""Cross-session Trend Analyzer.
Compares data across days to find week-level patterns.
Outputs: uncovered domain trends, policy firing velocity, recurring failure patterns.
"""
import json, os, glob, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter, defaultdict

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
REFLECTION_DIR = Path(HERMES_HOME) / "logs" / "reflection"
MAINTENANCE_DIR = Path(HERMES_HOME) / "logs" / "maintenance"
OUTCOMES_DIR = Path(HERMES_HOME) / "logs" / "outcomes"
OUTPUT_DIR = Path(HERMES_HOME) / "logs" / "trends"
POLICY_DIR = Path(HERMES_HOME) / "policies"
CORPUS = Path(HERMES_HOME) / "logs" / "self-regression-corpus.json"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_reflections():
    """Load all daily reflection files and extract improvement items."""
    reflections = []
    for path in sorted(REFLECTION_DIR.glob("*.md")):
        content = path.read_text()
        entries = {"date": path.stem, "improvement_items": [], "corrections": 0}
        for line in content.split("\n"):
            if line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. "):
                entries["improvement_items"].append(line.strip())
            if "| Correction |" in line:
                # Count correction table rows
                pass
            if "Root cause" in line:
                entries["corrections"] += 1
        reflections.append(entries)
    return reflections

def load_near_misses():
    """Load all near-miss reports and aggregate untriggered policies."""
    all_untriggered = Counter()
    all_co_firing = []
    for path in sorted(MAINTENANCE_DIR.glob("near-miss-*.json")):
        try:
            data = json.loads(path.read_text())
            for p in data.get("untriggered_policies", []):
                all_untriggered[p["policy_id"]] += 1
            for ctx in data.get("co_firing_contexts", []):
                all_co_firing.append(ctx["context"])
        except (json.JSONDecodeError, KeyError):
            continue
    return all_untriggered, all_co_firing

def load_outcomes():
    """Load task outcomes and compute velocity."""
    outcomes = []
    path = OUTCOMES_DIR / "task-outcomes.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    outcomes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return outcomes

def compute_velocity(outcomes):
    """Compute outcome velocity: how many outcomes per day."""
    if not outcomes:
        return 0.0, {}
    dates = Counter()
    for o in outcomes:
        d = o.get("applied_at", "")[:10]
        if d:
            dates[d] += 1
    if not dates:
        return 0.0, dates
    total = sum(dates.values())
    days = len(dates)
    return round(total / max(days, 1), 2), dict(dates.most_common())

def main():
    reflections = load_reflections()
    untriggered, co_firing = load_near_misses()
    outcomes = load_outcomes()
    velocity, daily_counts = compute_velocity(outcomes)

    # Corpus domain growth over time
    corpus_domains = {}
    if CORPUS.exists():
        try:
            with open(CORPUS) as f:
                corpus = json.load(f)
            for e in corpus:
                dom = e.get("domain", "unknown")
                added = e.get("added_at", "unknown")[:10]
                if added not in corpus_domains:
                    corpus_domains[added] = set()
                corpus_domains[added].add(dom)
        except (json.JSONDecodeError, OSError):
            pass

    report = {
        "generated_at": iso_now(),
        "days_analyzed": len(reflections),
        "total_reflection_days": len(reflections),
        "total_outcomes": len(outcomes),
        "outcome_velocity_per_day": velocity,
        "outcomes_by_day": daily_counts,
        "persistently_untriggered_policies": [
            {"policy_id": pid, "appearances_in_near_miss": count}
            for pid, count in untriggered.most_common(10)
        ],
        "co_firing_pattern_count": len(set(co_firing)),
        "corpus_domain_growth": {
            day: sorted(domains) for day, domains in sorted(corpus_domains.items())
        },
        "recurring_patterns": [],
        "suggested_improvements": [],
    }

    # Detect recurring patterns: same untriggered policy appearing in multiple near-miss reports
    for pid, count in untriggered.most_common(5):
        if count >= 2:
            report["recurring_patterns"].append(
                f"Policy {pid} appears untriggered in {count} consecutive near-miss scans"
            )

    # Detect declining outcome velocity
    if len(outcomes) >= 3:
        recent = outcomes[-3:]
        types = Counter(o.get("change_type", "unknown") for o in recent)
        if types.get("improvement", 0) < types.get("general", 0):
            report["recurring_patterns"].append(
                "General outcomes outpacing improvement outcomes — suggest explicit improvement tasks"
            )

    # Generate suggestions
    for pid, count in untriggered.most_common(3):
        if count >= 2:
            report["suggested_improvements"].append(
                f"Consider archiving or rewriting {pid} — untriggered in {count} consecutive scans"
            )

    if velocity < 1.0 and len(reflections) >= 2:
        report["suggested_improvements"].append(
            "Outcome velocity low — consider scheduling more improvement tasks"
        )

    if len(corpus_domains) <= 1 and len(reflections) >= 2:
        report["suggested_improvements"].append(
            "Corpus not growing across days — probe may need broader scanning"
        )

    # Write report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"trend-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"📈 Trend Report saved to {report_path}")
    print(f"   Days analyzed: {len(reflections)}")
    print(f"   Total outcomes: {len(outcomes)} (velocity: {velocity}/day)")
    print(f"   Persistently untriggered: {len(report['persistently_untriggered_policies'])}")
    print(f"   Recurring patterns: {len(report['recurring_patterns'])}")
    print(f"   Suggested improvements: {len(report['suggested_improvements'])}")

    if report["suggested_improvements"]:
        print("\n💡 Suggestions:")
        for s in report["suggested_improvements"]:
            print(f"   • {s}")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
