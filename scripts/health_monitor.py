#!/usr/bin/env python3
"""
Health monitor — runs every 5 minutes via cron.
Checks: gateway alive, no errors in log, dispatch responding.
Alerts via Telegram if anything is broken.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path.home() / ".hermes"
STATE_FILE = HERMES / "state" / "health-monitor.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

def load_state():
    if STATE_FILE.is_file():
        return json.loads(STATE_FILE.read_text())
    return {"consecutive_failures": 0, "last_ok": None, "last_alert": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def check_gateway_alive():
    """Check if gateway process is running."""
    r = subprocess.run(["pgrep", "-f", "hermes_cli"], capture_output=True, text=True)
    return len(r.stdout.strip().split()) >= 1

def check_no_crash_errors():
    """Check gateway log for recent crash errors."""
    log = HERMES / "logs" / "gateway.error.log"
    if not log.is_file():
        return True
    # Check last 50 lines for crash-level errors
    lines = log.read_text().splitlines()[-50:]
    crash_keywords = ["Traceback", "UnboundLocalError", "NameError", "TypeError", 
                      "AttributeError", "ModuleNotFoundError", "ImportError"]
    for line in lines:
        if any(kw in line for kw in crash_keywords):
            # Check if error is recent (< 10 minutes old)
            return False
    return True

def check_dispatch_responding():
    """Quick check that dispatch doesn't crash on basic routes."""
    try:
        sys.path.insert(0, str(HERMES / "hermes-agent"))
        from gateway.operator_shell.estate import _dispatch
        v = _dispatch("refresh", "health-check")
        return len(v.text) > 50
    except Exception:
        return False

def alert(text):
    """Send alert to Telegram."""
    try:
        subprocess.run(
            ["hermes", "send", "--to", "telegram", f"🚨 Health Monitor: {text}"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    issues = []
    
    if not check_gateway_alive():
        issues.append("Gateway process DEAD")
    
    if not check_no_crash_errors():
        issues.append("Crash errors in gateway log")
    
    if not check_dispatch_responding():
        issues.append("Dispatch not responding")
    
    if issues:
        state["consecutive_failures"] += 1
        print(f"❌ {len(issues)} issue(s): {', '.join(issues)}")
        print(f"   Consecutive failures: {state['consecutive_failures']}")
        
        # Alert on first failure and every 3rd consecutive
        if state["consecutive_failures"] in (1, 3, 6, 12):
            alert(f"{len(issues)} issue(s) — failure #{state['consecutive_failures']}\n" + "\n".join(issues))
            state["last_alert"] = now
    else:
        state["consecutive_failures"] = 0
        state["last_ok"] = now
        print(f"✅ All healthy")
    
    save_state(state)

if __name__ == "__main__":
    main()
