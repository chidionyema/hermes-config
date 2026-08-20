#!/usr/bin/env python3
"""
Self-improvement loop closer — in-process, no subprocess shelling.

Imports and calls all pipeline functions directly:
- gap-finding → auto-close gaps
- self-regression → auto-fix failures  
- meta-improver → measure velocity, track outcomes
- policy effectiveness measurement
- weekly digest push

Runs hourly via cron. Zero subprocess overhead.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SCRIPTS = HERMES / "scripts"
META_DIR = HERMES / "logs" / "meta-improver"
CHANGE_OUTCOMES = META_DIR / "change-outcomes.jsonl"

# Ensure scripts path for imports
sys.path.insert(0, str(SCRIPTS))


import importlib.util

def _import_script(name: str):
    """Import a script module by filename (handles hyphens)."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_gap_finding_and_close() -> dict:
    """Find gaps and auto-close them — all in-process."""
    gf = _import_script("gap-finding")
    corpus = gf.load_corpus()
    injection_log = gf.load_injection_log()
    skills = gf.scan_skills()
    policy_domains = gf.scan_policy_domains()
    failure_domains = gf.extract_failure_domains(corpus, injection_log)
    gaps = gf.find_gaps(failure_domains, policy_domains, skills, corpus)
    result = gf.auto_close_gaps(gaps)
    
    # Report gaps found
    uncovered = [g for g in gaps if not g.get("has_policy") and not g.get("has_skill")]
    weak = [g for g in gaps if g.get("has_policy") or g.get("has_skill")]
    result["gaps_found"] = len(gaps)
    result["uncovered"] = len(uncovered)
    result["weak_coverage"] = len(weak)
    return result


def run_self_regression_and_fix() -> dict:
    """Run regression tests, auto-fix failures — with circuit breaker."""
    # Check circuit breaker before attempting
    from circuit_breaker import get_breaker, CircuitBreakerOpen
    cb = get_breaker("self_improve")
    
    try:
        # This will raise CircuitBreakerOpen if circuit is open
        @cb
        def _do_fix():
            return _run_regression_and_fix_inner()
        return _do_fix()
    except CircuitBreakerOpen as e:
        return {"passed": 0, "failed": 0, "auto_fixed": False, "blocked": str(e)}

def _run_regression_and_fix_inner() -> dict:
    sr = _import_script("self-regression")
    af = _import_script("auto_fixer")

    corpus = sr.load_corpus()
    passed, failed, results = sr.run_regression(corpus)
    
    result = {"passed": passed, "failed": failed, "auto_fixed": False}
    
    if failed > 0:
        fix_result = af.auto_fix_all(dry_run=False)
        result["auto_fixed"] = True
        result["fixes_applied"] = fix_result.get("fixes_applied", 0)
    
    return result


def run_meta_improver() -> dict:
    """Measure velocity, track outcomes, apply improvements — all in-process."""
    META_DIR.mkdir(parents=True, exist_ok=True)
    
    # Ensure change-outcomes.jsonl exists
    if not CHANGE_OUTCOMES.is_file():
        CHANGE_OUTCOMES.write_text("")
    
    # Track outcome from last cycle
    outcome = track_outcome()
    
    # Run meta-improver analysis
    try:
        mi = _import_script("meta-improver")
        cfg = mi.load_config()
        policies = mi.load_policies()
        metrics = mi.load_metrics(n=10)
        
        # Compute improvement velocity
        if len(metrics) >= 2:
            recent = metrics[-5:] if len(metrics) >= 5 else metrics
            if len(recent) >= 2:
                first = recent[0].get("health_score", 0.5)
                last = recent[-1].get("health_score", 0.5)
                velocity = (last - first) / max(len(recent) - 1, 1)
            else:
                velocity = 0.0
        else:
            velocity = 0.0
        
        # Log metric
        mi.append_metric({
            "ts": mi.iso_now(),
            "health_score": outcome.get("health_score", 0.5),
            "velocity": round(velocity, 4),
            "policies_active": len(policies),
            "change_id": mi.timestamp_id(),
        })
        
        return {
            "velocity": round(velocity, 4),
            "health_score": outcome.get("health_score", 0.5),
            "policies_active": len(policies),
            "metrics_count": len(metrics) + 1,
        }
    except Exception as e:
        return {"error": str(e)}


def track_outcome() -> dict:
    """Track current health + policy state to change-outcomes."""
    sys.path.insert(0, str(HERMES / "hermes-agent"))
    from gateway.operator_shell.otto_health import _compute_score, _count_policies
    
    score = _compute_score()
    pcounts = _count_policies()
    
    # Load previous for delta
    prev_score = score["score"]
    if CHANGE_OUTCOMES.is_file():
        lines = CHANGE_OUTCOMES.read_text().splitlines()
        for line in reversed(lines):
            if not line.strip(): continue
            try:
                prev = json.loads(line)
                if "health_score" in prev:
                    prev_score = prev["health_score"]
                    break
            except json.JSONDecodeError: pass
    
    delta = score["score"] - prev_score
    
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "health_score": score["score"],
        "delta": round(delta, 4),
        "breakdown": score["breakdown"],
        "active_policies": pcounts["active"],
        "policies_created_this_week": pcounts["created_this_week"],
        "injections": score["raw"].get("total_injections", 0),
        "firings": score["raw"].get("total_firings", 0),
    }
    
    with open(CHANGE_OUTCOMES, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    return entry


def measure_policy_effectiveness() -> dict:
    """Per-policy effectiveness using OutcomeTracker — all in-process."""
    from outcome_tracker import OutcomeTracker
    
    tracker = OutcomeTracker(HERMES)
    ostats = tracker.stats(window_days=7)
    per_domain = ostats.get("per_domain", {})
    
    policies_dir = HERMES / "policies"
    if not policies_dir.is_dir():
        return {"effective": 0, "total": 0, "rate": 0.0}
    
    effective = 0
    total = 0
    policy_results = []
    
    for f in policies_dir.glob("*.json"):
        try:
            p = json.loads(f.read_text())
            if p.get("status") != "active": continue
            total += 1
            
            domains = p.get("domain", [])
            if isinstance(domains, str): domains = [domains]
            
            covers_improving = False
            for d in domains:
                if d in per_domain:
                    ds = per_domain[d]
                    if ds.get("success_rate", 0) > 0.5:
                        covers_improving = True
                        break
            
            if covers_improving:
                effective += 1
                policy_results.append({"id": p.get("id", "?"), "effective": True})
        except Exception: pass
    
    rate = effective / max(total, 1)
    
    # Log
    with open(CHANGE_OUTCOMES, "a") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "policy_effectiveness",
            "effective": effective, "total": total, "rate": round(rate, 3),
        }) + "\n")
    
    return {"effective": effective, "total": total, "rate": round(rate, 3)}


def push_weekly_digest() -> dict:
    """Push weekly digest to Telegram on Mondays — in-process."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 0:
        return {"pushed": False, "reason": "not Monday"}
    
    sys.path.insert(0, str(HERMES / "hermes-agent"))
    from gateway.operator_shell.health_panel import render_weekly_digest
    text, buttons = render_weekly_digest()
    
    # Send via hermes CLI (only subprocess — unavoidable for Telegram send)
    import subprocess
    r = subprocess.run(
        ["hermes", "send", "--to", "telegram", text],
        capture_output=True, text=True, timeout=30,
    )
    return {"pushed": r.returncode == 0, "text_length": len(text)}


def run_cycle(hourly: bool = False, daily: bool = False) -> dict:
    """Run a full self-improvement cycle. Returns results dict."""
    start = time.time()
    results = {}
    
    # Hourly: gap-finding + meta-improver
    print("[gap-finding] ", end="", flush=True)
    results["gaps"] = run_gap_finding_and_close()
    print(f"{results['gaps'].get('gaps_found',0)} gaps, "
          f"{results['gaps'].get('auto_closed',0)} closed, "
          f"{results['gaps'].get('shadow',0)} shadow")
    
    print("[meta-improver] ", end="", flush=True)
    results["meta"] = run_meta_improver()
    v = results["meta"].get("velocity", 0)
    direction = "📈" if v > 0.01 else ("📉" if v < -0.01 else "➡️")
    print(f"velocity {v:+.4f} {direction}, "
          f"health {results['meta'].get('health_score', '?')}")
    
    if daily:
        print("[regression] ", end="", flush=True)
        results["regression"] = run_self_regression_and_fix()
        print(f"{results['regression']['passed']} pass, "
              f"{results['regression']['failed']} fail"
              f"{', auto-fixed' if results['regression'].get('auto_fixed') else ''}")
        
        print("[effectiveness] ", end="", flush=True)
        results["effectiveness"] = measure_policy_effectiveness()
        print(f"{results['effectiveness']['effective']}/{results['effectiveness']['total']} "
              f"({results['effectiveness']['rate']:.0%})")
        
        print("[digest] ", end="", flush=True)
        results["digest"] = push_weekly_digest()
        print("pushed" if results["digest"].get("pushed") else "skipped")
    
    results["elapsed"] = round(time.time() - start, 2)

    # Record the cycle, then grade the loop itself. Until 2026-08-20 this function printed
    # its result and wrote it nowhere, so 244 cycles found 1723 gaps, closed 0, and nothing
    # anywhere could see the series that would have said so. See rsi_loop_guard.
    try:
        import rsi_loop_guard
        rsi_loop_guard.record_cycle(results)
        health = rsi_loop_guard.check()
        results["loop_health"] = health
        if not health["healthy"]:
            for problem in health["problems"]:
                print(f"[loop-guard] UNHEALTHY: {problem}")
            try:
                from estate_alert import send_operator_alert
                send_operator_alert(
                    "\U0001f9e0 Self-improvement loop unhealthy\n\n"
                    + "\n\n".join(health["problems"]),
                    debounce_key="rsi-loop-guard",
                    # 12h, not the 300s default. This condition clears over DAYS as
                    # capability-domain outcomes accrue, and the cycle runs hourly, so
                    # the default would send the same sentence 24 times a day.
                    debounce_s=43200,
                )
            except Exception as e:
                sys.stderr.write(f"[loop-guard] alert failed: {e}\n")
        else:
            print("[loop-guard] OK")
    except Exception as e:
        sys.stderr.write(f"[loop-guard] unavailable: {e}\n")

    return results


def main():
    import argparse
    p = argparse.ArgumentParser(description="Self-improvement loop closer (in-process)")
    p.add_argument("--hourly", action="store_true")
    p.add_argument("--daily", action="store_true")
    p.add_argument("--all", action="store_true")
    args = p.parse_args()
    
    hourly = args.hourly or args.all or (not args.daily)
    daily = args.daily or args.all
    
    print(f"=== Cycle: {datetime.now(timezone.utc).isoformat()} ===\n")
    results = run_cycle(hourly=hourly, daily=daily)
    print(f"\n=== Complete ({results['elapsed']}s) ===")


if __name__ == "__main__":
    main()
