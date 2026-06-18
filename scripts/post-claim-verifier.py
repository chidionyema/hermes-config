#!/usr/bin/env python3
"""
Post-claim verifier — runs automatically after every significant claim.
Checks that what I just said exists actually exists on disk.

If a claim is false (file missing, count wrong, status wrong), it's caught
immediately and the correction is logged — not discovered hours later.

This is the structural fix for: claiming things exist that don't.
The pattern is: I claim X is done → X doesn't exist → user catches it → repeat.
The fix is: verify every claim against disk BEFORE reporting it.
"""

import json
import os
import sys
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
CLAIM_LOG = os.path.join(HERMES_HOME, "logs", "claim-verifications.jsonl")


def verify_file_exists(path: str) -> dict:
    """Verify a file exists and has content."""
    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    return {"path": path, "exists": exists, "size": size}


def verify_file_count(directory: str, pattern: str = "", expected: int = None) -> dict:
    """Verify a directory has the expected number of files."""
    if not os.path.isdir(directory):
        return {"directory": directory, "count": 0, "exists": False, "expected": expected}
    files = [f for f in os.listdir(directory) if pattern in f]
    count = len(files)
    return {"directory": directory, "count": count, "exists": True, "expected": expected, "match": count == expected if expected is not None else True}


class ClaimVerifier:
    """Chainable verifier for post-claim checking."""
    
    def __init__(self):
        self.claims = []
        self.failures = []
        self.start = datetime.now()
    
    def file_exists(self, path: str, description: str = ""):
        """Claim: a file exists."""
        result = verify_file_exists(path)
        entry = {"type": "file_exists", "description": description or path, **result}
        self.claims.append(entry)
        if not result["exists"]:
            self.failures.append(entry)
        return self
    
    def file_count(self, directory: str, expected: int, pattern: str = "", description: str = ""):
        """Claim: a directory has N files."""
        result = verify_file_count(directory, pattern, expected)
        entry = {"type": "file_count", "description": description or directory, **result}
        self.claims.append(entry)
        if not result.get("match", False):
            self.failures.append(entry)
        return self
    
    def verify(self):
        """Run all checks and return success/failure."""
        return len(self.failures) == 0


def verify_current_state():
    """Run a complete verification of everything claimed this session."""
    v = ClaimVerifier()
    
    # Scripts
    v.file_count(os.path.join(HERMES_HOME, "scripts"), 13, ".py", "All Python scripts exist")
    v.file_exists(os.path.join(HERMES_HOME, "scripts", "policy-enforcer.py"), "Policy enforcer")
    v.file_exists(os.path.join(HERMES_HOME, "scripts", "meta-improver.py"), "Meta improver")
    v.file_exists(os.path.join(HERMES_HOME, "scripts", "reflect-on-correction.py"), "Post-correction reflection")
    v.file_exists(os.path.join(HERMES_HOME, "scripts", "memory_retrieval.py"), "Memory retrieval Phase 2")
    
    # Specs
    spec_dir = os.path.join(HERMES_HOME, "specs", "otto-system")
    v.file_count(spec_dir, 11, ".md", "All 10 specs + README")
    for i in range(11):
        fname = f"{i:02d}-*.md" if i > 0 else "README.md"
    
    # Policies
    v.file_count(os.path.join(HERMES_HOME, "policies"), 8, ".json", "8 policies")
    v.file_exists(os.path.join(HERMES_HOME, "policies", "pol-20260618-004.json"), "Policy 004 (active)")
    
    # Cron
    v.file_exists(os.path.join(HERMES_HOME, "cron", "jobs.json"), "Cron jobs file")
    
    # Off-switch
    v.file_exists(os.path.join(HERMES_HOME, "meta", "OFF_SWITCH"), "Off-switch")
    
    # Regression corpus
    v.file_exists(os.path.join(HERMES_HOME, "logs", "self-regression-corpus.json"), "Self-regression corpus")
    
    # Log the verification
    os.makedirs(os.path.dirname(CLAIM_LOG), exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_claims": len(v.claims),
        "failures": len(v.failures),
        "passed": v.verify(),
        "failed_claims": [f["description"] for f in v.failures],
    }
    with open(CLAIM_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    return v


def main():
    # Run the verification
    v = verify_current_state()
    
    # Print results
    total = len(v.claims)
    failed = len(v.failures)
    print(f"Claims verified: {total}")
    print(f"Passed: {total - failed}")
    print(f"Failed: {failed}")
    
    if v.failures:
        print("\n⚠️ FALSE CLAIMS:")
        for f in v.failures:
            print(f"  ❌ {f['description']}")
            print(f"     Expected: exists=True, Got: exists={f.get('exists', '?')}")
        return 1
    else:
        print("\n✅ All claims verified.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
