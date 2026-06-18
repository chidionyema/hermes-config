#!/usr/bin/env python3
"""
Self-Regression Engine (#2 of the Continuous Learning Build).
Maintains a corpus of past failures and re-tests the current policy set against them.
Pass = evidence a policy works. Fail = gap still open.

The corpus is built from:
- Policy firings (injection-log.jsonl)
- Correction reflections (logs/reflection/)
- Direct additions via the add-failure command

Pre-emptible, token-capped, bounded.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
CORPUS_FILE = os.path.join(HERMES_HOME, "logs", "self-regression-corpus.json")
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")
INJECTION_LOG = os.path.join(HERMES_HOME, "logs", "injection-log.jsonl")
REFLECTION_DIR = os.path.join(HERMES_HOME, "logs", "reflection")


DEFAULT_CORPUS = []


def load_corpus():
    """Load or initialise the failure corpus."""
    if os.path.exists(CORPUS_FILE):
        with open(CORPUS_FILE) as f:
            return json.load(f)
    return list(DEFAULT_CORPUS)


def save_corpus(corpus):
    os.makedirs(os.path.dirname(CORPUS_FILE), exist_ok=True)
    with open(CORPUS_FILE, "w") as f:
        json.dump(corpus, f, indent=2)


def load_policies():
    """Load all policies with trigger + rule."""
    policies = []
    if not os.path.isdir(POLICY_DIR):
        return policies
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(POLICY_DIR, fname)
            with open(path) as f:
                p = json.load(f)
            policies.append(p)
    return policies


def extract_failures_from_reflections():
    """Scan reflection files for corrections and build corpus entries."""
    failures = []
    if not os.path.isdir(REFLECTION_DIR):
        return failures
    
    for fname in os.listdir(REFLECTION_DIR):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(REFLECTION_DIR, fname)
        with open(path) as f:
            content = f.read()
        
        # Extract "Corrected: ..." or correction table rows
        corrections = re.findall(r'\|([^|]+)\|([^|]+)\|', content)
        for trigger, fix in corrections:
            trigger = trigger.strip()
            fix = fix.strip()
            if trigger and fix and trigger != "Correction" and fix != "Root cause":
                failures.append({
                    "source": f"reflection/{fname}",
                    "trigger": trigger[:120],
                    "fix": fix[:200],
                    "test": f"Would policy now prevent: '{trigger}'?"
                })
        
        # Also extract "Root cause: X" patterns
        causes = re.findall(r'Root cause[:\s]+(.*?)(?:\n|$)', content)
        for cause in causes:
            cause = cause.strip()
            if cause:
                failures.append({
                    "source": f"reflection/{fname}",
                    "trigger": cause[:120],
                    "fix": "(extracted)",
                    "test": f"Would policy now prevent: '{cause}'?"
                })
    
    return failures


def extract_failures_from_firings():
    """Extract failure patterns from policy firing log."""
    failures = []
    if not os.path.exists(FIRINGS_LOG):
        return failures
    with open(FIRINGS_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line)
                failures.append({
                    "source": "firing",
                    "trigger": entry.get("trigger", "?")[:120],
                    "fix": entry.get("rule", "?")[:200],
                    "test": f"Policy {entry.get('policy_id', '?')} fired"
                })
            except json.JSONDecodeError:
                continue
    return failures


def run_regression(corpus=None):
    """
    Run the entire corpus against current policies.
    Returns (pass_count, fail_count, results).
    """
    if corpus is None:
        corpus = load_corpus()
    
    policies = load_policies()
    policy_texts = [p.get("trigger", "") + " " + p.get("rule", "") for p in policies if p.get("status") in ("active", "provisional")]
    
    results = []
    passed = 0
    failed = 0
    
    for entry in corpus:
        test_text = entry.get("test", entry.get("trigger", ""))
        test_lower = test_text.lower()
        
        # Check if any active/provisional policy covers this case
        covered = False
        covering_policies = []
        for p in policies:
            if p.get("status") not in ("active", "provisional"):
                continue
            trigger_lower = p.get("trigger", "").lower()
            rule_lower = p.get("rule", "").lower()
            combined = trigger_lower + " " + rule_lower
            # Check word overlap
            test_words = set(test_lower.split())
            pol_words = set(combined.split())
            overlap = len(test_words & pol_words) / max(len(test_words), 1)
            if overlap > 0.3:
                covered = True
                covering_policies.append(p["id"])
        
        result = {
            "test": test_text[:80],
            "covered": covered,
            "covering_policies": covering_policies,
            "source": entry.get("source", "unknown"),
        }
        results.append(result)
        if covered:
            passed += 1
        else:
            failed += 1
    
    return passed, failed, results


def add_failure(trigger, fix, source="manual"):
    """Add a failure to the corpus."""
    corpus = load_corpus()
    entry = {
        "source": source,
        "trigger": trigger[:120],
        "fix": fix[:200],
        "test": f"Would policy now prevent: '{trigger}'?",
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    # Deduplicate
    for existing in corpus:
        if existing.get("trigger") == entry["trigger"]:
            print(f"Duplicate: '{trigger}' already in corpus (skipping)")
            return
    corpus.append(entry)
    save_corpus(corpus)
    print(f"Added: '{trigger[:60]}...' → corpus now has {len(corpus)} entries")


def build_regression_report(passed, failed, results):
    """Build a structured regression report."""
    total = passed + failed
    coverage = (passed / total * 100) if total > 0 else 0
    
    lines = []
    lines.append(f"# Self-Regression Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"\n**Coverage:** {passed}/{total} ({coverage:.0f}%)")
    lines.append(f"**Corpus size:** {total} failure entries")
    lines.append("")
    
    # Uncategorised failures
    uncovered = [r for r in results if not r["covered"]]
    if uncovered:
        lines.append(f"## ❌ Still Uncovered ({len(uncovered)})")
        for r in uncovered:
            lines.append(f"- {r['test']} (source: {r['source']})")
        lines.append("")
    
    # Covered by policies
    covered = [r for r in results if r["covered"]]
    if covered:
        lines.append(f"## ✅ Covered by Policies ({len(covered)})")
        for r in covered:
            policies_str = ", ".join(r["covering_policies"][:3])
            lines.append(f"- {r['test']} → {policies_str}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Self-Regression Engine")
    parser.add_argument("--add", nargs=2, metavar=("TRIGGER", "FIX"),
                       help="Add a failure to the corpus")
    parser.add_argument("--run", action="store_true",
                       help="Run regression against current policies")
    parser.add_argument("--harvest", action="store_true",
                       help="Extract failures from reflections + firing logs into corpus")
    parser.add_argument("--report", action="store_true",
                       help="Run regression and print report")
    
    args = parser.parse_args()
    
    if args.add:
        trigger, fix = args.add
        add_failure(trigger, fix)
        return 0
    
    if args.harvest:
        corpus = load_corpus()
        existing_triggers = {c.get("trigger") for c in corpus}
        
        new_failures = extract_failures_from_reflections()
        new_failures += extract_failures_from_firings()
        
        added = 0
        for f in new_failures:
            if f.get("trigger") not in existing_triggers:
                corpus.append(f)
                existing_triggers.add(f.get("trigger"))
                added += 1
        
        save_corpus(corpus)
        print(f"Harvested {added} new failures. Corpus now has {len(corpus)} entries.")
        return 0
    
    if args.run or args.report:
        corpus = args.run and load_corpus() or load_corpus()
        
        # Harvest first if corpus is empty
        if not corpus:
            corpus = extract_failures_from_reflections() + extract_failures_from_firings()
            if not corpus:
                print("Empty corpus. Run with --harvest to populate.")
                return 0
        
        passed, failed, results = run_regression(corpus)
        
        if args.report:
            report = build_regression_report(passed, failed, results)
            report_path = os.path.join(HERMES_HOME, "logs", "regression-report.md")
            with open(report_path, "w") as f:
                f.write(report)
            print(report)
            print(f"\nReport saved to {report_path}")
        else:
            total = passed + failed
            pct = (passed / total * 100) if total > 0 else 0
            print(f"Regression: {passed}/{total} passed ({pct:.0f}%)")
            uncovered = len([r for r in results if not r["covered"]])
            if uncovered:
                print(f"⚠️ {uncovered} failures still uncovered")
        
        return 0
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
