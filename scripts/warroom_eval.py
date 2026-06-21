#!/usr/bin/env python3
"""warroom_eval.py — SwingArena CI Duel Evaluation Harness.

Reverts local code files in signalengine to pre-fix states, captures test failures,
runs Single Model vs War Room Council head-to-head, and evaluates correctness via pytest.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import route as RT
from warroom import run_council, extract_code

REPO_PATH = "/Users/chidionyema/documents/code/signalengine"
EVAL_DIR = os.path.expanduser("~/.hermes/meta/warrooms/eval")
LATEST_REPORT_PATH = os.path.join(EVAL_DIR, "LATEST.md")


def find_swing_targets(count: int = 10) -> list[dict]:
    """Dynamically find fix commits in signalengine that modified both code and test files."""
    cmd = ["git", "log", "--grep=fix", "--oneline", "-n", "100"]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_PATH)
    commits = []
    for line in res.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})
            
    targets = []
    for c in commits:
        if len(targets) >= count:
            break
        # Get diff files
        diff_cmd = ["git", "diff", "--name-only", f"{c['hash']}~1", c["hash"]]
        diff_res = subprocess.run(diff_cmd, capture_output=True, text=True, cwd=REPO_PATH)
        files = [f.strip() for f in diff_res.stdout.strip().split("\n") if f.strip()]
        
        src_files = [f for f in files if (f.startswith("signal_engine/") or f.startswith("api/")) and f.endswith(".py")]
        test_files = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
        
        # Fallback search if no test file is directly in diff
        if src_files and not test_files:
            for src in src_files:
                base = os.path.splitext(os.path.basename(src))[0]
                potential = [
                    f"tests/test_{base}.py",
                    f"tests/test_{base}_tz.py",
                    f"tests/test_{base}_timestamps.py"
                ]
                for p in potential:
                    if os.path.exists(os.path.join(REPO_PATH, p)):
                        test_files.append(p)
                        break
                        
        if src_files and test_files:
            targets.append({
                "commit": c["hash"],
                "message": c["message"],
                "code_file": src_files[0],
                "test_file": test_files[0]
            })
            
    return targets


def run_test_suite(test_file: str) -> tuple[bool, str]:
    """Run pytest inside the virtual environment for a specific test file."""
    cmd = [os.path.join(REPO_PATH, ".venv/bin/pytest"), test_file]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_PATH)
    passed = res.returncode == 0
    output = res.stderr or res.stdout
    return passed, output


def revert_code_file(commit: str, code_file: str, code_abs_path: str) -> None:
    # Check if the file existed in the commit's parent
    check_cmd = ["git", "cat-file", "-e", f"{commit}~1:{code_file}"]
    res = subprocess.run(check_cmd, capture_output=True, cwd=REPO_PATH)
    if res.returncode == 0:
        subprocess.run(["git", "checkout", f"{commit}~1", "--", code_file], cwd=REPO_PATH)
    else:
        # File did not exist in parent commit (was newly created)
        if os.path.exists(code_abs_path):
            os.remove(code_abs_path)


def evaluate_target(idx: int, target: dict) -> dict:
    commit = target["commit"]
    msg = target["message"]
    code_file = target["code_file"]
    test_file = target["test_file"]
    
    code_abs_path = os.path.join(REPO_PATH, code_file)
    print(f"[{idx+1}] Evaluating target {commit}: {msg[:50]}...")
    
    # 1. Revert code file to pre-fix state
    revert_code_file(commit, code_file, code_abs_path)
    
    # Read pre-fix buggy file content
    pre_fix_content = ""
    if os.path.exists(code_abs_path):
        with open(code_abs_path, "r", encoding="utf-8") as f:
            pre_fix_content = f.read()
        
    # Run test suite to capture baseline failure trace
    _, baseline_trace = run_test_suite(test_file)
    baseline_trace_clean = baseline_trace[-1000:]  # keep trailing output
    
    # --- CONTROL: Single Frontier Model ---
    prompt_single = (
        f"You are a software engineering agent. Solve the following bug:\n"
        f"Bug Description: {msg}\n\n"
        f"Here is the content of the file that has the bug:\n"
        f"--- START CODE ---\n{pre_fix_content}\n--- END CODE ---\n\n"
        f"Here is the test failure output:\n"
        f"--- START TEST FAILURE ---\n{baseline_trace_clean}\n--- END TEST FAILURE ---\n\n"
        f"Provide the corrected, full python code of the file. Output the final python code inside a standard ```python ... ``` block."
    )
    
    single_passed = False
    try:
        single_res = RT.route("executor", prompt_single, timeout=60)
        single_code = extract_code(single_res.text)
        if single_code:
            # Apply single model patch
            os.makedirs(os.path.dirname(code_abs_path), exist_ok=True)
            with open(code_abs_path, "w", encoding="utf-8") as f:
                f.write(single_code)
            # Run test suite
            single_passed, single_trace = run_test_suite(test_file)
            if not single_passed:
                print(f"❌ [DEBUG] Single Model patch failed on {test_file}. Traceback:\n{single_trace}\n")
    except Exception as e:
        print(f"❌ [DEBUG] Single Model execution failed: {e}")
        
    # Restore file for Test run
    subprocess.run(["git", "checkout", "HEAD", "--", code_file], cwd=REPO_PATH)
    
    # --- TEST: War Room Council ---
    # Revert code file again
    revert_code_file(commit, code_file, code_abs_path)
    
    prompt_council = (
        f"We must patch the file to resolve this bug. Solve it and output the final, corrected python code:\n"
        f"Bug Description: {msg}\n\n"
        f"Here is the content of the file that has the bug:\n"
        f"--- START CODE ---\n{pre_fix_content}\n--- END CODE ---\n\n"
        f"Here is the test failure output:\n"
        f"--- START TEST FAILURE ---\n{baseline_trace_clean}\n--- END TEST FAILURE ---\n\n"
        f"Output the final python code of the corrected file inside a standard ```python ... ``` block."
    )
    
    council_passed = False
    dissent = 0.0
    try:
        council_res = run_council(prompt_council, ground="GROUND TRUTH: SWINGARENA CI DUEL MODE.")
        council_code = extract_code(council_res["decision"])
        dissent = council_res["dissent_coefficient"]
        if council_code:
            # Apply council patch
            os.makedirs(os.path.dirname(code_abs_path), exist_ok=True)
            with open(code_abs_path, "w", encoding="utf-8") as f:
                f.write(council_code)
            # Run test suite
            council_passed, council_trace = run_test_suite(test_file)
            if not council_passed:
                print(f"❌ [DEBUG] Council patch failed on {test_file}. Traceback:\n{council_trace}\n")
    except Exception as e:
        print(f"❌ [DEBUG] Council execution failed: {e}")
        
    # Restore file to clean state
    subprocess.run(["git", "checkout", "HEAD", "--", code_file], cwd=REPO_PATH)
    
    print(f"  Target {commit}: Single Passed = {single_passed} | Council Passed = {council_passed} | Dissent = {dissent:.2f}")
    
    return {
        "commit": commit,
        "message": msg,
        "code_file": code_file,
        "test_file": test_file,
        "single_ok": single_passed,
        "council_ok": council_passed,
        "dissent": dissent
    }


def make_ascii_bar(val: float, max_len: int = 20) -> str:
    filled = int(val * max_len)
    return "[" + "█" * filled + " " * (max_len - filled) + "]"


def main() -> int:
    print("🚀 Starting SwingArena CI Duel Evaluation...")
    targets = find_swing_targets(count=5)
    print(f"Found {len(targets)} valid historical bugs in git history.")
    
    if not targets:
        print("❌ No valid targets found.")
        return 1
        
    results = []
    # Run sequentially to prevent workspace lock/git checkout collisions
    for idx, t in enumerate(targets):
        results.append(evaluate_target(idx, t))
        
    total = len(results)
    single_correct = sum(1 for r in results if r["single_ok"])
    council_correct = sum(1 for r in results if r["council_ok"])
    
    single_acc = single_correct / total
    council_acc = council_correct / total
    
    low_dissent_runs = [r for r in results if r["dissent"] < 0.3]
    med_dissent_runs = [r for r in results if 0.3 <= r["dissent"] <= 0.6]
    high_dissent_runs = [r for r in results if r["dissent"] > 0.6]
    
    def cat_acc(runs):
        if not runs:
            return 0.0
        return sum(1 for r in runs if r["council_ok"]) / len(runs)
        
    low_acc = cat_acc(low_dissent_runs)
    med_acc = cat_acc(med_dissent_runs)
    high_acc = cat_acc(high_dissent_runs)
    
    # Generate Report
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(LATEST_REPORT_PATH, "w") as f:
        f.write("# SwingArena CI Duel Evaluation Report\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Repository:** `signalengine`\n")
        f.write(f"**Methodology:** Historically reverted Git commits resolved live via Pytest execution.\n\n")
        
        f.write("## Comparative Accuracy\n\n")
        f.write("| Condition | Score | Accuracy | Performance Bar |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write(f"| Single Frontier Model | {single_correct}/{total} | {single_acc*100:.1f}% | {make_ascii_bar(single_acc)} |\n")
        f.write(f"| **War Room Council** | **{council_correct}/{total}** | **{council_acc*100:.1f}%** | **{make_ascii_bar(council_acc)}** |\n\n")
        
        f.write("## Dissent-to-Accuracy Ratio Analysis\n\n")
        f.write("| Dissent Level | Runs | Accuracy | Stability Chart |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write(f"| Low Dissent (< 0.3) | {len(low_dissent_runs)} | {low_acc*100:.1f}% | {make_ascii_bar(low_acc)} |\n")
        f.write(f"| Medium Dissent (0.3 - 0.6) | {len(med_dissent_runs)} | {med_acc*100:.1f}% | {make_ascii_bar(med_acc)} |\n")
        f.write(f"| High Dissent (> 0.6) | {len(high_dissent_runs)} | {high_acc*100:.1f}% | {make_ascii_bar(high_acc)} |\n\n")
        
        f.write("## Per-Commit Results\n\n")
        f.write("| Commit | Message | Code File | Test File | Single Model | War Room | Dissent |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for r in results:
            single_status = "🟢 Pass" if r["single_ok"] else "🔴 Fail"
            council_status = "🟢 Pass" if r["council_ok"] else "🔴 Fail"
            f.write(f"| `{r['commit']}` | {r['message']} | `{r['code_file']}` | `{r['test_file']}` | {single_status} | {council_status} | {r['dissent']:.2f} |\n")
            
    print(f"🎉 Evaluation report saved successfully to {LATEST_REPORT_PATH}")
    return 0 if council_acc >= single_acc else 1


if __name__ == "__main__":
    raise SystemExit(main())
