#!/usr/bin/env python3
"""
POPDD Test Runner — drop-in template

Runs any test command and signs the result into a POPDD chain.
Demonstrates POPDD integration in any project that has a Python venv.

Usage:
    # 1. Install lux-popdd:
    #    pip install -e ../popdd-py     OR    pip install lux-popdd
    #
    # 2. Customize TEST_COMMAND below for your project
    #
    # 3. Run:
    #    python scripts/popdd_verify.py
    #
    # Output: a signed chain in .lux/receipts/test-<pid>.jsonl

Customize the TEST_COMMAND and AGENT_ID constants for your project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Allow importing popdd from a sibling checkout during development.
# Remove this if you install lux-popdd via pip.
#
# The script lives at <project>/scripts/popdd_verify.py, so:
#   Path(__file__).parent       = <project>/scripts/
#   Path(__file__).parent.parent = <project>/
#   Path(__file__).parent.parent.parent = <parent of project>/
#
# Common layouts:
#   Sibling repos:  both in ~/Documents/code/  →  parent.parent.parent / "popdd-py"
#   Sub-folder:     popdd-py inside the project →  parent.parent / "popdd-py"
#   Pip-installed:  remove this sys.path block entirely
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "popdd-py"))

from popdd import HmacSigner, ReceiptChain  # noqa: E402

# ─────────────────────────────────────────────────────────────────────
# CUSTOMIZE THESE FOR YOUR PROJECT
# ─────────────────────────────────────────────────────────────────────

# The command to run your project's tests. Examples:
#   ["npx", "vitest", "run", "--reporter=basic"]     # LUX (TypeScript)
#   ["uv", "run", "pytest", "-q"]                    # Signal Engine
#   [".venv/bin/python", "-m", "pytest", "-q"]       # Prospector
TEST_COMMAND = ["echo", "no tests configured — set TEST_COMMAND in this script"]

# Identify the agent in the audit trail
AGENT_ID = "my-project-pipeline"

# Where to store the signing key and the chain files
KEY_PATH = Path(".lux/keys/agent.pem")
RECEIPTS_DIR = Path(".lux/receipts")

# How long to wait for the test command to complete (seconds)
TIMEOUT = 600

# ─────────────────────────────────────────────────────────────────────
# END OF CUSTOMIZATION
# ─────────────────────────────────────────────────────────────────────


def parse_vitest_output(output: str) -> tuple[int, int]:
    """Extract passed/failed counts from a vitest summary line.

    Looks for: "Tests  359 passed | 3 skipped (362)"
    """
    passed, failed = 0, 0
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    return passed, failed


def parse_pytest_output(output: str) -> tuple[int, int]:
    """Extract passed/failed counts from a pytest summary line.

    Looks for: "===== 359 passed, 3 skipped in 4.2s ====="
    """
    passed, failed = 0, 0
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    return passed, failed


def main() -> int:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    signer = HmacSigner(HmacSigner.load_or_create_key(KEY_PATH))
    chain = ReceiptChain(signer, agent_id=AGENT_ID)

    # Step 1: pre-test receipt
    chain.append(
        action="test-run:start",
        target=AGENT_ID,
        proof={
            "verdict": "STARTED",
            "command": TEST_COMMAND,
            "pid": os.getpid(),
        },
    )

    # Step 2: run the test command
    print(f"Running: {' '.join(TEST_COMMAND)}")
    try:
        result = subprocess.run(
            TEST_COMMAND,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        chain.append(
            action="test-run:complete",
            target=AGENT_ID,
            proof={"verdict": "TIMEOUT", "timeout_seconds": TIMEOUT},
        )
        chain_path = RECEIPTS_DIR / f"test-{os.getpid()}.jsonl"
        chain.save(chain_path)
        print(f"TIMEOUT after {TIMEOUT}s. Chain: {chain_path}")
        return 1
    except FileNotFoundError as e:
        print(f"Command not found: {e}")
        return 1

    # Step 3: parse results (try both vitest and pytest formats)
    passed, failed = parse_vitest_output(output)
    if passed == 0 and failed == 0:
        passed, failed = parse_pytest_output(output)

    verdict = "PASS" if result.returncode == 0 and failed == 0 else "FAIL"

    # Step 4: post-test receipt
    chain.append(
        action="test-run:complete",
        target=AGENT_ID,
        proof={
            "verdict": verdict,
            "passed": passed,
            "failed": failed,
            "exitCode": result.returncode,
            "outputTail": output[-500:] if output else "",
        },
    )

    # Step 5: verify the chain integrity
    verify_result = chain.verify()

    # Step 6: persist
    chain_path = RECEIPTS_DIR / f"test-{os.getpid()}.jsonl"
    chain.save(chain_path)

    print()
    print("=" * 60)
    print(f"  POPDD Run Complete — {AGENT_ID}")
    print("=" * 60)
    print(f"  Test verdict:  {verdict} ({passed} passed, {failed} failed)")
    print(f"  Chain valid:   {verify_result.valid}")
    print(f"  Chain path:    {chain_path}")
    print(f"  Verifier ID:   {chain.verifier_id}")
    print("=" * 60)
    print()

    # Non-zero exit on failure so CI can use this script as a gate
    if not verify_result.valid:
        return 2
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
