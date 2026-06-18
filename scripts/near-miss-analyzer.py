#!/usr/bin/env python3
"""Near-Miss Analyzer: finds patterns that almost triggered but didn't.
Looks at policy firings, firing context, and the failure corpus to find:
1. Triggers that look similar but have different outcomes
2. Co-firing contexts (multiple policies fire in same turn)
3. Policies that should have fired but didn't (based on trigger similarity)

Runs as part of idle-learning or on-demand.
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")
CORPUS = os.path.join(HERMES_HOME, "logs", "self-regression-corpus.json")
OUTPUT_DIR = Path(HERMES_HOME) / "logs" / "maintenance"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_firings():
    if not os.path.exists(FIRINGS_LOG):
        return []
    with open(FIRINGS_LOG) as f:
        return [json.loads(l) for l in f if l.strip()]

def load_corpus():
    if not os.path.exists(CORPUS):
        return []
    with open(CORPUS) as f:
        return json.load(f)

def load_policies():
    pdir = os.path.join(HERMES_HOME, "policies")
    policies = []
    for fname in sorted(os.listdir(pdir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(pdir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath) as f:
            p = json.load(f)
        policies.append(p)
    return policies

def main():
    firings = load_firings()
    corpus = load_corpus()
    policies = load_policies()

    findings = {
        "generated_at": iso_now(),
        "total_firings": len(firings),
        "untriggered_policies": [],
        "co_firing_contexts": [],
        "domain_coverage_gaps": [],
    }

    # 1. Policies that have never fired
    fired_pids = set(f.get("policy_id") for f in firings)
    for p in policies:
        pid = p.get("id", "")
        if p.get("status") not in ("active", "provisional"):
            continue
        if pid not in fired_pids:
            created = p.get("created", p.get("created_at", "unknown"))
            findings["untriggered_policies"].append({
                "policy_id": pid,
                "trigger": p.get("trigger", "")[:60],
                "domain": p.get("scope", {}).get("domain", "none"),
                "created": created,
                "hits": p.get("hits", 0),
            })

    # 2. Co-firing contexts: multiple policies fired in same context
    context_map = {}
    for f in firings:
        ctx = f.get("context", f.get("trigger", "unknown"))[:80]
        if ctx not in context_map:
            context_map[ctx] = []
        context_map[ctx].append(f.get("policy_id", "?"))

    for ctx, pids in sorted(context_map.items(), key=lambda x: -len(x[1])):
        if len(pids) >= 2:
            findings["co_firing_contexts"].append({
                "context": ctx,
                "policies": list(set(pids)),
                "count": len(pids),
            })

    # 3. Domain coverage gaps: policies exist for domain X, but corpus entries in X not caught
    domain_policies = {}
    for p in policies:
        dom = p.get("scope", {}).get("domain", "none")
        if dom not in domain_policies:
            domain_policies[dom] = []
        domain_policies[dom].append(p.get("id", ""))

    domain_corpus_counts = {}
    for e in corpus:
        dom = e.get("domain", "unknown")
        domain_corpus_counts[dom] = domain_corpus_counts.get(dom, 0) + 1

    for dom, count in sorted(domain_corpus_counts.items(), key=lambda x: -x[1]):
        if dom not in domain_policies:
            # Uncovered domain — no policy exists at all
            findings["domain_coverage_gaps"].append({
                "domain": dom,
                "corpus_entries": count,
                "policies_exist": 0,
                "severity": "high" if count >= 3 else "medium",
            })

    # Output
    report_path = OUTPUT_DIR / f"near-miss-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(findings, f, indent=2)

    print(f"📊 Near-Miss Analysis saved to {report_path}")
    print(f"   Untriggered policies: {len(findings['untriggered_policies'])}")
    print(f"   Co-firing contexts: {len(findings['co_firing_contexts'])}")
    print(f"   Domain coverage gaps: {len(findings['domain_coverage_gaps'])}")

    # Surface top issues
    if findings["untriggered_policies"]:
        print(f"\n🔴 Untriggered policies:")
        for p in findings["untriggered_policies"][:5]:
            print(f"   {p['policy_id']} ({p['domain']}): {p['trigger']}")
    if findings["domain_coverage_gaps"]:
        print(f"\n🟡 Domain coverage gaps:")
        for g in findings["domain_coverage_gaps"]:
            print(f"   {g['domain']}: {g['corpus_entries']} entries, no policy")
    if findings["co_firing_contexts"]:
        print(f"\n🟡 Co-firing patterns ({len(findings['co_firing_contexts'])}):")
        for ctx in findings["co_firing_contexts"][:3]:
            print(f"   {ctx['context'][:50]} → {ctx['policies']}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
