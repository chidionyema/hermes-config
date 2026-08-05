#!/usr/bin/env python3
"""cross_project.py — Estate-wide health, correlation, and dependency map. Rounds K1-K3."""
import json, os, sys, subprocess
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

def estate_health_score():
    """K1: 0-100 health score across all projects."""
    scores = {}
    # Prospector
    try:
        ticks = Path.home()/"Documents/code/prospector/store/scheduler/ticks.jsonl"
        if ticks.is_file():
            lines = ticks.read_text().splitlines()
            recent = lines[-10:]
            errors = sum(1 for ln in recent if '"error": "' in ln)
            scores["prospector"] = max(0, 100 - errors * 10)
        else:
            scores["prospector"] = 50
    except: scores["prospector"] = 0

    # Signal Engine
    try:
        r = subprocess.run(["pgrep", "-f", "signal.engine"], capture_output=True, timeout=5)
        scores["signal_engine"] = 100 if r.returncode == 0 else 0
    except: scores["signal_engine"] = 50

    # Hermes
    try:
        cron = HERMES_HOME/"cron"/"jobs.json"
        if cron.is_file():
            data = json.loads(cron.read_text())
            jobs = data if isinstance(data, list) else data.get("jobs",[])
            failing = sum(1 for j in jobs if j.get("enabled",True) and j.get("last_status") not in (None,"","ok"))
            scores["hermes"] = max(0, 100 - failing * 20)
        else:
            scores["hermes"] = 70
    except: scores["hermes"] = 0

    # TIE
    try:
        tie_plist = Path.home()/"Library/LaunchAgents/com.tie.ai-review.plist"
        scores["tie"] = 80 if tie_plist.is_file() else 40
    except: scores["tie"] = 40

    total = sum(scores.values())
    count = len(scores)
    overall = round(total / max(count, 1))
    return {"overall": overall, "breakdown": scores,
            "timestamp": datetime.now(timezone.utc).isoformat()}

def correlate_estate():
    """K2: Find clusters of failures with shared root cause."""
    clusters = []
    try:
        ops = HERMES_HOME/"logs"/"ops-monitor.jsonl"
        if ops.is_file():
            entries = [json.loads(l) for l in ops.read_text().splitlines() if l.strip()]
            recent = [e for e in entries[-50:] if e.get("severity") in ("warning","error")]
            if len(recent) >= 3:
                types = set(e.get("type","") for e in recent)
                clusters.append({"time_window": "recent", "failure_types": list(types),
                                 "count": len(recent),
                                 "shared_cause": "API credits" if any("credit" in str(e).lower() or "moat" in str(e).lower() for e in recent) else "multiple"})
    except: pass
    return {"clusters": clusters}

def dependency_map():
    """K3: What depends on what, and what's blocking what."""
    deps = {
        "prospector": {"depends_on": ["cursor_cli", "claude_cli", "api_credits"],
                       "status": "unknown", "blocked_by": []},
        "signal_engine": {"depends_on": ["tcc_permission", "exchange_api", "account_balance"],
                          "status": "unknown", "blocked_by": []},
        "hermes": {"depends_on": ["telegram_api", "github", "coordinator_db"],
                   "status": "unknown", "blocked_by": []},
        "otto": {"depends_on": ["hermes", "claude_api", "minimax_api"],
                 "status": "unknown", "blocked_by": []},
    }
    # Check prospector moat
    try:
        ticks = Path.home()/"Documents/code/prospector/store/scheduler/ticks.jsonl"
        if ticks.is_file():
            lines = ticks.read_text().splitlines()
            recent = lines[-5:]
            if sum(1 for ln in recent if '"error": "' in ln) >= 3:
                deps["prospector"]["status"] = "blocked"
                deps["prospector"]["blocked_by"] = ["cursor_credits", "claude_credits"]
            else:
                deps["prospector"]["status"] = "healthy"
    except: pass
    return {"dependencies": deps, "timestamp": datetime.now(timezone.utc).isoformat()}

def main():
    import argparse
    p = argparse.ArgumentParser(description="Cross-project intelligence")
    p.add_argument("--health", action="store_true")
    p.add_argument("--correlate", action="store_true")
    p.add_argument("--dependencies", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.health: result = estate_health_score()
    elif args.correlate: result = correlate_estate()
    elif args.dependencies: result = dependency_map()
    else: result = estate_health_score()
    if args.json: print(json.dumps(result, indent=2, default=str))
    else: print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__": main()
