#!/usr/bin/env python3
"""Multi-repo health check. Runs every 2h via cron.
Only reports when state CHANGES (pass→fail, new dirty files).
Silent on no-change to avoid Telegram noise.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

REPOS = {
    "signalengine": {
        "path": str(Path.home() / "Documents" / "code" / "signalengine"),
        "test_cmd": "uv run pytest -q --no-header --tb=line -p no:cacheprovider 2>&1 | tail -5",
        "timeout": 120,
    },
    "lux": {
        "path": str(Path.home() / "Documents" / "code" / "lux"),
        "test_cmd": "npx jest --passWithNoTests --silent 2>&1 | tail -5",
        "timeout": 120,
    },
    "prospector": {
        "path": str(Path.home() / "Documents" / "code" / "prospector"),
        "test_cmd": ".venv/bin/python -m pytest -q --no-header 2>&1 | tail -5",
        "timeout": 120,
    },
}

LOG_DIR = Path.home() / ".hermes" / "logs" / "health"
HISTORY_FILE = LOG_DIR / "repo-health.jsonl"

def run(cmd, cwd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", -1
    except Exception as e:
        return f"(error: {e})", -1

def check_repo(name, info):
    """Returns (state: str, summary: str). State is 'pass', 'fail', or 'dirty'."""
    path = info["path"]
    if not Path(path).exists():
        return "skip", f"{name}: not found"
    
    # Git status
    dirty_out, _ = run("git status --short", path, 10)
    dirty_count = len([l for l in dirty_out.split("\n") if l.strip()]) if dirty_out else 0
    
    # Test run (with timeout)
    test_out, test_code = run(info["test_cmd"], path, info.get("timeout", 60))
    
    if test_code != 0:
        state = "fail"
        summary = test_out.split("\n")[-1][:80] if test_out else "test failed"
        return state, f"{name}: FAIL — {summary}"
    elif dirty_count > 0:
        state = "dirty"
        return state, f"{name}: DIRTY ({dirty_count} uncommitted)"
    else:
        state = "pass"
        passed = test_out.split("\n")[-1][:80] if test_out else "all pass"
        return state, f"{name}: {passed}"

def load_history():
    if not HISTORY_FILE.exists():
        return {}
    with open(HISTORY_FILE) as f:
        lines = f.readlines()
    if not lines:
        return {}
    try:
        return json.loads(lines[-1].strip())
    except (json.JSONDecodeError, IndexError):
        return {}

def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    prev_state = load_history()
    
    results = {}
    changes = []
    
    for name, info in sorted(REPOS.items()):
        state, summary = check_repo(name, info)
        results[name] = {"state": state, "summary": summary}
        
        prev = prev_state.get(name, {}).get("state", "unknown")
        if prev != state and prev != "unknown":
            changes.append(f"  {prev} → {state}: {summary}")
    
    # Always log current state
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    # Only output to stdout (→Telegram) if something changed or errored
    any_fail = any(r.get("state") == "fail" for r in results.values())
    any_dirty = any(r.get("state") == "dirty" for r in results.values())
    
    if changes or any_fail:
        print(f"\u26a0\ufe0f  Repo health — {sum(1 for r in results.values() if r['state']=='pass')} pass, {sum(1 for r in results.values() if r['state']=='fail')} fail")
        for name, r in sorted(results.items()):
            icon = "\u2705" if r["state"] == "pass" else "\u274c" if r["state"] == "fail" else "\ud83d\udfe0" if r["state"] == "dirty" else "\u26a0\ufe0f"
            print(f"  {icon} {r['summary']}")
        if changes:
            print(f"\nChanges since last check:")
            for c in changes:
                print(c)
        return 1 if any_fail else 0
    else:
        # Silent — nothing changed, all healthy
        return 0

if __name__ == "__main__":
    sys.exit(main())
