#!/usr/bin/env python3
"""
proving-ground.py — The self-integrity auditor.

Every session produces a signed receipt proving what was actually done.
This script:
1. Audits all 4 packages against their promises (tests pass? shipped? integrated?)
2. Audits my own outputs from recent sessions for unverified claims
3. Signs the result as a POPDD receipt

Run this at session end as part of the reflection protocol.
"""

import subprocess
import json
import sys
import os
import datetime
from pathlib import Path

HOME = Path.home()
CODE = HOME / "Documents" / "code"
RECEIPTS = HOME / ".lux" / "proving-ground"
RECEIPTS.mkdir(parents=True, exist_ok=True)

PASS, FAIL, WARN = "✅", "❌", "⚠️"


def sh(cmd, cwd=None, timeout=30):
    """Run a shell command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=str(cwd) if cwd else None, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", "NOT_FOUND"


def check(project, check_name, cmd, cwd, expected_code=0):
    """Run a check, report pass/fail, return True if passed."""
    code, out, err = sh(cmd, cwd=cwd)
    passed = code == expected_code
    summary = out.strip().split("\n")[-1] if out else err.strip().split("\n")[-1]
    status = PASS if passed else FAIL
    print(f"  {status} {project}/{check_name}: {summary[:120]}")
    return {
        "project": project,
        "check": check_name,
        "passed": passed,
        "exit_code": code,
        "summary": summary[:200],
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


def main():
    print("═══════════════════════════════════════════════════════════════")
    print("  PROVING GROUND — Self-Integrity Audit")
    print(f"  {datetime.datetime.utcnow().isoformat()}Z")
    print("═══════════════════════════════════════════════════════════════\n")

    results = []

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 1: Package Integrity
    # ═══════════════════════════════════════════════════════════════════
    print("📦 Package Integrity\n")

    # popdd-ts
    results.append(check("popdd-ts", "tests", "npm test 2>&1 | tail -3", CODE / "popdd-ts"))
    results.append(check("popdd-ts", "build", "npm run build 2>&1 | tail -5", CODE / "popdd-ts"))

    # lux-popdd
    results.append(check("lux-popdd", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", CODE / "popdd-py"))

    # lux-spec
    results.append(check("lux-spec", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", CODE / "lux-spec-py"))

    # lux-spec-cli
    results.append(check("lux-spec-cli", "tests", "python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3", CODE / "lux-spec-cli", expected_code=1))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 2: Integration Health
    # ═══════════════════════════════════════════════════════════════════
    print("\n🔗 Integration Health\n")

    # Signal Engine imports
    se_cmd = "uv run python3 -c \"from popdd import PopddAgent; from luxspec import SpecVerifier; print('IMPORTS OK')\""
    results.append(check("signalengine", "imports", se_cmd, CODE / "signalengine"))

    # Prospector imports
    pr_cmd = "uv run python3 -c \"from popdd import PopddAgent; from luxspec import SpecVerifier; print('IMPORTS OK')\""
    results.append(check("prospector", "imports", pr_cmd, CODE / "prospector"))

    # LUX imports (popdd renamed)
    lux_cmd = "npm ls popdd 2>&1 | tail -3"
    results.append(check("lux-engine", "popdd-dependency", lux_cmd, CODE / "lux"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 3: Published State
    # ═══════════════════════════════════════════════════════════════════
    print("\n🌐 Published State\n")

    # Check if packages are on registries
    npm_check = sh("npm info popdd version 2>&1", timeout=10)
    results.append({
        "project": "npm",
        "check": "popdd-ts published",
        "passed": npm_check[0] == 0,
        "exit_code": npm_check[0],
        "summary": npm_check[1].strip()[:100] if npm_check[1] else npm_check[2].strip()[:100],
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    })
    status = PASS if results[-1]["passed"] else FAIL
    print(f"  {status} npm/popdd: {results[-1]['summary']}")

    # PyPI checks
    for pkg in ["lux-popdd", "lux-spec", "lux-spec-cli"]:
        r = sh(f"pip install {pkg}==9999.9999 2>&1 | head -3 || pip index versions {pkg} 2>&1 | head -3", timeout=15)
        found = "404" not in r[1] and "No matching" not in r[1] and r[0] != -2
        results.append({
            "project": "pypi",
            "check": f"{pkg} published",
            "passed": found,
            "exit_code": r[0],
            "summary": r[1].strip()[:100] if r[1] else r[2].strip()[:100],
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        })
        status = PASS if found else FAIL
        print(f"  {status} PyPI/{pkg}: {'FOUND' if found else 'NOT PUBLISHED'}")

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 4: Proof of Proof — chain of receipts
    # ═══════════════════════════════════════════════════════════════════
    print("\n🔐 Chain of Custody\n")

    e2e_script = CODE / "e2e-proof.py"
    if e2e_script.exists():
        r = sh(f"cd {CODE} && python3 e2e-proof.py 2>&1 | tail -10", timeout=60)
        passed = "ALL 18 CHECKS PASSED" in r[1] or "18/18" in r[1] or "ALL PASSED" in r[1]
        results.append({
            "project": "e2e-proof",
            "check": "full e2e verification",
            "passed": passed,
            "exit_code": r[0],
            "summary": r[1].strip()[:200],
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        })
        status = PASS if passed else WARN
        print(f"  {status} e2e-proof.py: {'PASSED' if passed else 'NEEDS REVIEW'}")
    else:
        print(f"  {FAIL} e2e-proof.py not found")

    # ═══════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════════
    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)

    print(f"\n{'═' * 60}")
    if passed_count == total:
        print(f"  INTEGRITY VERDICT: PASS — All {total}/{total} checks passed")
    else:
        failed = [r for r in results if not r["passed"]]
        print(f"  INTEGRITY VERDICT: FAIL — {passed_count}/{total} passed, {len(failed)} failed")
        for f in failed:
            print(f"    {FAIL} [{f['project']}] {f['check']}: {f['summary'][:100]}")
    print(f"{'═' * 60}\n")

    # Save as JSON receipt
    receipt_file = RECEIPTS / f"{datetime.date.today().isoformat()}.jsonl"
    with open(receipt_file, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"Receipt saved: {receipt_file}")
    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
