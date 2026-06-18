#!/usr/bin/env python3
"""Cross-Project Pattern Bridge.
Connects LUX verification results → policy improvement signals.
When LUX finds a test failure or spec violation in any repo, that
becomes a structured entry in the self-regression corpus so the
self-improvement pipeline learns from it.

Runs as part of the idle-learning pipeline (after gap-finding).
"""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
CORPUS = HERMES_HOME / "logs" / "self-regression-corpus.json"
HEALTH_LOG = HERMES_HOME / "logs" / "health" / "repo-health.jsonl"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def latest_health_state():
    """Read the last health state to find failures across repos."""
    if not HEALTH_LOG.exists():
        return {}
    with open(HEALTH_LOG) as f:
        lines = f.readlines()
    if not lines:
        return {}
    try:
        return json.loads(lines[-1].strip()).get("results", {})
    except (json.JSONDecodeError, IndexError):
        return {}

def find_lux_specs():
    """Scan ~/Documents/code/lux/specs/ for recent spec violations."""
    lux_specs = Path.home() / "Documents" / "code" / "lux" / "specs"
    if not lux_specs.exists():
        return []
    spec_files = sorted(lux_specs.glob("**/*.spec.*")) + sorted(lux_specs.glob("**/*.tspec.*"))
    return [str(s) for s in spec_files[:10]]

def main():
    results = latest_health_state()
    failures = {name: info for name, info in results.items() if info.get("state") == "fail"}
    dirty = {name: info for name, info in results.items() if info.get("state") == "dirty"}
    
    new_corpus_entries = []
    
    # Bridge health failures → corpus entries
    for name, info in failures.items():
        entry = {
            "source": f"health-bridge/{name}",
            "domain": "engineering/reliability",
            "trigger": f"{name} tests failed: {info.get('summary', '?')}",
            "fix": f"Investigate and fix {name} test failures",
            "test": f"Would the new policy prevent {name} tests from failing unnoticed?",
            "added_at": iso_now(),
        }
        new_corpus_entries.append(entry)
    
    for name, info in dirty.items():
        entry = {
            "source": f"health-bridge/{name}",
            "domain": "infra/process-management",
            "trigger": f"{name} has uncommitted changes ({info.get('summary', '?')})",
            "fix": f"Commit or stash changes in {name}",
            "test": f"Would policy now prevent uncommitted work in {name}?",
            "added_at": iso_now(),
        }
        new_corpus_entries.append(entry)
    
    if not new_corpus_entries:
        print("All repos healthy — no bridge entries needed")
        return 0
    
    # Append to corpus
    if CORPUS.exists():
        with open(CORPUS) as f:
            corpus = json.load(f)
    else:
        corpus = []
    
    corpus.extend(new_corpus_entries)
    with open(CORPUS, "w") as f:
        json.dump(corpus, f, indent=2)
    
    print(f"Bridged {len(new_corpus_entries)} health events into corpus:")
    for e in new_corpus_entries:
        print(f"  + {e['domain']}: {e['trigger'][:70]}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
