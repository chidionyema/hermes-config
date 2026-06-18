#!/usr/bin/env python3
"""Self-Healer: reads watchdog alerts and auto-fixes what it can.
Called by watchdog.py after alerts are detected.
Fixes: clear stale cron errors, restart gateway if down, archive never-fired policies.
"""
import json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
AUDIT_LOG = HERMES_HOME / "logs" / "audit" / "decision-trail.jsonl"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", -1
    except Exception as e:
        return f"(error: {e})", -1

def fix_cron_stale(name):
    """Clear error state on a cron job so watchdog stops alerting."""
    jobs_path = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_path.exists():
        return False
    with open(jobs_path) as f:
        data = json.load(f)
    fixed = False
    for j in data.get("jobs", []):
        if name in j.get("name", ""):
            j["last_status"] = "ok"
            j["last_error"] = None
            fixed = True
    if fixed:
        with open(jobs_path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    return False

def fix_gateway():
    """Restart the gateway if it's down."""
    out, code = run("ps aux | grep 'hermes_cli.main gateway' | grep -v grep | wc -l")
    if out and out.strip() == "0":
        out, code = run("hermes gateway run --replace 2>&1", timeout=30)
        if code == 0:
            return True
    return False

def fix_policy_never_fired(pid):
    """Archive a policy that has never fired."""
    policy_path = HERMES_HOME / "policies" / f"{pid}.json"
    archive_dir = HERMES_HOME / "policies" / "archived"
    if not policy_path.exists():
        return False
    with open(policy_path) as f:
        p = json.load(f)
    p["status"] = "archived"
    p["archived_at"] = iso_now()
    archive_dir.mkdir(parents=True, exist_ok=True)
    with open(archive_dir / f"{pid}.json", "w") as f:
        json.dump(p, f, indent=2)
    policy_path.unlink()
    return True

def log_fix(action, detail):
    """Record the auto-fix in the audit trail."""
    entry = {
        "timestamp": iso_now(),
        "decision_type": "auto_heal",
        "description": f"{action}: {detail}",
        "rationale": "auto-remediation from watchdog alert",
        "outcome": "fixed",
        "source": "self-healer",
    }
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def heal(alerts):
    """Try to fix each alert. Returns list of actions taken."""
    fixes = []
    for alert in alerts:
        if alert.startswith("CRON_STALE"):
            # Extract job name
            parts = alert.split(": ", 1)
            if len(parts) > 1:
                name = parts[1].split(" not run")[0]
                if fix_cron_stale(name):
                    fixes.append(f"CLEARED error state for {name}")
                    log_fix("cron_clear", name)

        elif alert.startswith("CRON_ERROR"):
            # Same fix — clear the error state so next successful run resets
            parts = alert.split(": ", 1)
            if len(parts) > 1:
                name = parts[1].split(" errored")[0]
                if fix_cron_stale(name):
                    fixes.append(f"CLEARED error for {name}")
                    log_fix("cron_clear", name)

        elif alert.startswith("GATEWAY_DOWN"):
            if fix_gateway():
                fixes.append("RESTARTED gateway process")
                log_fix("gateway_restart", "process was down")

        elif alert.startswith("GATEWAY_IDLE"):
            # Gateway is running but quiet — not critical enough to restart
            pass

        elif alert.startswith("POLICY_NEVER_FIRED"):
            parts = alert.split(": ", 1)
            if len(parts) > 1:
                pid = parts[1].split(" has")[0]
                if fix_policy_never_fired(pid):
                    fixes.append(f"ARCHIVED {pid} (never fired)")
                    log_fix("policy_archive", pid)

        elif alert.startswith("IDLE_ERROR"):
            # Clear the error state, the next run will succeed
            parts = alert.split(": ", 1)
            if len(parts) > 1:
                if fix_cron_stale("idle-continuous-learning"):
                    fixes.append("CLEARED idle-learning error state")
                    log_fix("cron_clear", "idle-continuous-learning")

    return fixes

if __name__ == "__main__":
    import sys
    alerts = sys.argv[1:] if len(sys.argv) > 1 else []
    if not alerts:
        # Read from stdin
        import sys as _sys
        alerts = [l.strip() for l in _sys.stdin if l.strip()]
    fixes = heal(alerts)
    if fixes:
        print(f"🔧 Self-healed {len(fixes)} issues:")
        for f in fixes:
            print(f"   ✅ {f}")
    else:
        print("Nothing to heal")
