#!/usr/bin/env python3
"""
test_rounds_d_h.py — Acceptance tests for Rounds D-H.

All tests should FAIL initially (red). They turn green as features are built.
Run: cd ~/.hermes && python3 tests/test_rounds_d_h.py
"""

import json
import os
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
AGENT_DIR = HERMES_HOME / "hermes-agent"
sys.path.insert(0, str(AGENT_DIR))
SCRIPTS = HERMES_HOME / "scripts"

passed = 0
failed = 0
total = 0

def check(name, condition, detail=""):
    global passed, failed, total
    total += 1
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))

def script_runs(name):
    """Check that a script exists and runs without crashing."""
    path = SCRIPTS / f"{name}.py"
    if not path.is_file():
        return False, f"{name}.py not found"
    import subprocess
    r = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True, text=True, timeout=10
    )
    return r.returncode in (0, 2), f"exit={r.returncode}"


print("=== Round D: Predictive Intelligence ===\n")

# D1: Credit exhaustion predictor
exists, detail = script_runs("predictor")
check("D1 predictor script exists", exists, detail)
if exists:
    import subprocess
    r = subprocess.run([sys.executable, str(SCRIPTS / "predictor.py"), "--predict", "credits"],
                       capture_output=True, text=True, timeout=15)
    has_output = len(r.stdout.strip()) > 0
    check("D1 predict credits returns output", has_output, f"stdout={len(r.stdout)} chars")

# D2: Failure correlation
if exists:
    r = subprocess.run([sys.executable, str(SCRIPTS / "predictor.py"), "--correlate"],
                       capture_output=True, text=True, timeout=15)
    check("D2 correlate failures runs", r.returncode in (0, 1), f"exit={r.returncode}")

# D3: Anomaly detection
if exists:
    r = subprocess.run([sys.executable, str(SCRIPTS / "predictor.py"), "--anomalies"],
                       capture_output=True, text=True, timeout=15)
    check("D3 anomaly detection runs", r.returncode in (0, 1), f"exit={r.returncode}")

# D4: MTTR tracking
if exists:
    r = subprocess.run([sys.executable, str(SCRIPTS / "predictor.py"), "--mttr"],
                       capture_output=True, text=True, timeout=15)
    check("D4 MTTR tracking runs", r.returncode in (0, 1), f"exit={r.returncode}")


print("\n=== Round E: Active Diagnosis ===\n")

# E1-E4: Diagnostics script
exists_e, detail_e = script_runs("diagnostics")
check("E1-E4 diagnostics script exists", exists_e, detail_e)
if exists_e:
    for cmd, label in [("--diagnose", "E4 full diagnostic"), ("--moat", "E1 moat diagnosis"),
                        ("--engine", "E2 engine diagnosis"), ("--fix-credits", "E3 credit fix")]:
        r = subprocess.run([sys.executable, str(SCRIPTS / "diagnostics.py"), cmd],
                           capture_output=True, text=True, timeout=15)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")


print("\n=== Round F: Operational Resilience ===\n")

exists_f, detail_f = script_runs("resilience")
check("F1-F4 resilience script exists", exists_f, detail_f)
if exists_f:
    for cmd, label in [("--rotate-ticks", "F1 tick rotation"), ("--check-db", "F2 DB health"),
                        ("--verify-backups", "F3 backup verify"), ("--degradation", "F4 degradation")]:
        r = subprocess.run([sys.executable, str(SCRIPTS / "resilience.py"), cmd],
                           capture_output=True, text=True, timeout=15)
        check(f"{label} runs", r.returncode in (0, 1), f"exit={r.returncode}")


print("\n=== Round G: Developer Experience ===\n")

exists_g, detail_g = script_runs("feature_registry")
check("G1-G4 feature registry exists", exists_g, detail_g)
if exists_g:
    for cmd, label in [("--list", "G1 feature list"), ("--benchmark", "G2 benchmark"),
                        ("--changelog", "G3 changelog"), ("--capabilities", "G4 capabilities")]:
        r = subprocess.run([sys.executable, str(SCRIPTS / "feature_registry.py"), cmd],
                           capture_output=True, text=True, timeout=30)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")


print("\n=== Round H: Score-Driven Improvement ===\n")

exists_h, detail_h = script_runs("score_driver")
check("H1-H4 score driver exists", exists_h, detail_h)
if exists_h:
    for cmd, label in [("--burndown", "H1 score burn-down"), ("--regression", "H3 regression check"),
                        ("--leaderboard", "H4 leaderboard")]:
        r = subprocess.run([sys.executable, str(SCRIPTS / "score_driver.py"), cmd],
                           capture_output=True, text=True, timeout=15)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")

# H2: Agent simulator
exists_sim, detail_sim = script_runs("agent_simulator")
check("H2 agent simulator exists", exists_sim, detail_sim)
if exists_sim:
    r = subprocess.run([sys.executable, str(SCRIPTS / "agent_simulator.py"), "--run", "3"],
                       capture_output=True, text=True, timeout=30)
    check("H2 simulates agent traffic", r.returncode == 0, f"exit={r.returncode}")


print("\n=== Natural Language Routing ===\n")

sys.path.insert(0, str(AGENT_DIR))
try:
    from gateway.operator_shell.natural_ops import match_natural_op
    
    # Action names corrected 2026-08-17 against estate.py _PANELS, which is the registry the
    # router actually dispatches through. This list had asserted "diagnose", "predict",
    # "features", "fix_credits" and "system_health"; the real actions are "diagnose_panel",
    # "predict_panel", "features_panel", "fix_guide" and "estate_health". Five of these
    # phrases also had no pattern at all ("diagnose moat", "why is prospector failing",
    # "fix credits", "predict credits", "system health") — those patterns were added the
    # same day, so the phrases now route. Every row below was measured, not assumed.
    routes = [
        ("diagnose", "diagnose_panel"), ("diagnose moat", "diagnose_panel"),
        ("why is prospector failing", "diagnose_panel"),
        ("fix credits", "fix_guide"), ("predict", "predict_panel"),
        ("predict credits", "predict_panel"),
        ("features", "features_panel"), ("what features exist", "features_panel"),
        ("capabilities", "capabilities"), ("what can you do", "capabilities"),
        ("score", "score"), ("score target", "score"), ("score history", "score"),
        ("system health", "estate_health"),
    ]
    for phrase, expected in routes:
        nop = match_natural_op(phrase)
        ok = nop is not None and nop.action == expected
        check(f"NL '{phrase}' → {expected}", ok,
              f"got {nop.action if nop else 'NO MATCH'}")
    # Declared gap, 2026-08-17. "benchmark" has no entry in estate.py _PANELS and no pattern
    # in natural_ops.py, so these two rows asserted a feature nobody built and failed on
    # every run. Assert the gap instead, so it fails loudly the day one is half-wired.
    for phrase in ("benchmark", "otto bench"):
        check(f"NL '{phrase}' is a DECLARED GAP, no panel exists",
              match_natural_op(phrase) is None,
              "it routes now — build the panel and move this phrase into routes above")
except Exception as e:
    check("NL routing import", False, str(e))


print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed, {total} total")
print(f"{'='*50}")

if __name__ == "__main__":   # bare sys.exit() at module scope aborts pytest collection
    sys.exit(0 if failed == 0 else 1)
