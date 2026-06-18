#!/usr/bin/env python3
"""Continuous Health Watchdog.
Runs every 15 minutes via cron. Checks every subsystem and generates alert if thresholds breached.
Does NOT send to user directly — writes to alert log. Strategist audit reads it and escalates.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
ALERT_THRESHOLDS = {
    "cron_stale_hours": 26,          # Alert if cron job hasn't run in 26+ hours
    "uncommitted_files_max": 50,      # Alert if >50 uncommitted files
    "gateway_down_minutes": 5,        # Alert if gateway hasn't responded in 5+ min
    "disk_usage_percent_max": 90,     # Alert if disk >90%
    "idle_learning_errors_max": 3,    # Alert if idle-learning errored 3+ consecutive times
}

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run(cmd, timeout=10):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", -1
    except Exception as e:
        return f"(error: {e})", -1

def check_cron_health():
    """Check every cron job: is it running? Are any stale?"""
    alerts = []
    jobs_path = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_path.exists():
        return ["cron/jobs.json not found"]
    
    with open(jobs_path) as f:
        data = json.load(f)
    
    now = time.time()
    for j in data.get("jobs", []):
        name = j.get("name", "?")
        enabled = j.get("enabled", False)
        state = j.get("state", "?")
        last_raw = j.get("last_run_at")
        status = j.get("last_status")
        error = j.get("last_error")

        # Not running
        if enabled and state == "scheduled" and status is None:
            # Never run — new job, normal
            continue
        
        # Errored last run
        if status == "error":
            alerts.append(f"CRON_ERROR: {name} errored: {str(error)[:80]}")
        
        # Stale (hasn't run in threshold hours)
        if enabled and last_raw:
            try:
                last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
                elapsed = (time.time() - last.timestamp()) / 3600
                if elapsed > ALERT_THRESHOLDS["cron_stale_hours"]:
                    alerts.append(f"CRON_STALE: {name} not run in {elapsed:.0f}h (threshold: {ALERT_THRESHOLDS['cron_stale_hours']}h)")
            except (ValueError, TypeError):
                alerts.append(f"CRON_PARSE: {name} has unparseable last_run_at: {last_raw[:30]}")

    return alerts

def check_git_health():
    """Check for uncommitted changes and broken state."""
    alerts = []
    out, code = run("cd ~/.hermes && git status --porcelain", timeout=10)
    if code != 0:
        alerts.append(f"GIT_ERROR: git status failed with code {code}: {out[:100]}")
        return alerts
    
    count = len([l for l in out.split("\n") if l.strip()]) if out else 0
    if count > ALERT_THRESHOLDS["uncommitted_files_max"]:
        alerts.append(f"GIT_DIRTY: {count} uncommitted files (threshold: {ALERT_THRESHOLDS['uncommitted_files_max']})")
    return alerts

def check_gateway():
    """Check gateway is alive. Uses process check, not HTTP (gateway doesn't serve HTTP health)."""
    alerts = []
    out, code = run("ps aux | grep 'hermes_cli.main gateway' | grep -v grep | wc -l | tr -d ' '", timeout=5)
    if out and out.strip() == "0":
        alerts.append("GATEWAY_DOWN: no gateway process running")
    else:
        # Also check for recent log activity (last 5 min)
        try:
            log = Path(HERMES_HOME) / "logs" / "gateway.log"
            if log.exists():
                mtime = log.stat().st_mtime
                minutes_idle = (time.time() - mtime) / 60
                if minutes_idle > 30:
                    alerts.append(f"GATEWAY_IDLE: gateway log not updated in {minutes_idle:.0f} minutes")
        except OSError:
            pass
    return alerts

def check_disk():
    """Check disk usage."""
    alerts = []
    out, code = run("df -h / | tail -1 | awk '{print $5}' | tr -d '%'", timeout=5)
    if out and out.strip():
        try:
            pct = int(out.strip())
            if pct > ALERT_THRESHOLDS["disk_usage_percent_max"]:
                alerts.append(f"DISK_HIGH: disk at {pct}% (threshold: {ALERT_THRESHOLDS['disk_usage_percent_max']}%)")
        except ValueError:
            pass
    return alerts

def check_idle_learning():
    """Check if idle-learning has been erroring repeatedly."""
    alerts = []
    jobs_path = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_path.exists():
        return alerts
    with open(jobs_path) as f:
        data = json.load(f)
    
    idle_job = None
    for j in data.get("jobs", []):
        if "idle" in j.get("name", "").lower():
            idle_job = j
            break
    
    if idle_job and idle_job.get("last_status") == "error":
        alerts.append(f"IDLE_ERROR: idle-learning failed on last run: {str(idle_job.get('last_error',''))[:100]}")
    
    return alerts

def check_policy_firings():
    """Check if any critical policies have 0 firings after creation."""
    alerts = []
    pdir = HERMES_HOME / "policies"
    if not pdir.exists():
        return alerts
    
    for fname in sorted(os.listdir(pdir)):
        if not fname.endswith(".json"):
            continue
        fpath = pdir / fname
        if not fpath.is_file():
            continue
        with open(fpath) as f:
            try:
                p = json.load(f)
            except json.JSONDecodeError:
                continue
        pid = p.get("id", "")
        if p.get("status") not in ("active", "provisional"):
            continue
        if p.get("hits", 0) > 0:
            continue
        created = p.get("created") or p.get("created_at", "")
        if not created:
            continue
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - created_dt).days
            if days >= 1 and p.get("hits", 0) == 0:
                alerts.append(f"POLICY_NEVER_FIRED: {pid} has 0 hits after {days} days")
        except (ValueError, TypeError):
            continue
    return alerts

def main():
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    (HERMES_HOME / "logs" / "alerts").mkdir(parents=True, exist_ok=True)
    
    all_alerts = []
    all_alerts.extend(check_cron_health())
    all_alerts.extend(check_git_health())
    all_alerts.extend(check_gateway())
    all_alerts.extend(check_disk())
    all_alerts.extend(check_idle_learning())
    all_alerts.extend(check_policy_firings())

    entry = {
        "timestamp": iso_now(),
        "alert_count": len(all_alerts),
        "alerts": all_alerts,
        "healthy": len(all_alerts) == 0,
    }
    
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    if all_alerts:
        # Only push to user if this is a NEW alert (not the same as last run)
        new_alerts = []
        try:
            with open(ALERT_LOG) as f:
                lines = f.readlines()
            if len(lines) >= 2:
                prev = json.loads(lines[-2].strip())
                prev_set = set(prev.get("alerts", []))
                current_set = set(all_alerts)
                new_alerts = list(current_set - prev_set)
        except (json.JSONDecodeError, IndexError, OSError):
            new_alerts = all_alerts
        
        if new_alerts:
            print(f"⚠️  NEW — {len(new_alerts)} issue(s):")
            for a in new_alerts:
                print(f"   ❗ {a}")
        else:
            print(f"⚠️  {len(all_alerts)} known issue(s) — no change")
        
        # Auto-heal (runs regardless of new/known)
        healer = HERMES_HOME / "scripts" / "self-healer.py"
        if healer.exists():
            out, code = run(f"{sys.executable} {healer} " + " ".join(f'"{a}"' for a in all_alerts), timeout=30)
            if out:
                print(out)
    else:
        print("✅ All subsystems healthy")
    
    return 0 if entry["healthy"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
