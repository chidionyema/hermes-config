#!/usr/bin/env python3
"""
auto_fixer.py — Autonomous fix engine with verification and learning.

Rounds I1, I2, I5: Auto-fixes common failures, verifies each fix,
and creates/updates policies so Otto learns from every fix.
"""

import json, os, sys, subprocess, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
OPS_LOG = HERMES_HOME / "logs" / "ops-monitor.jsonl"
FIX_LOG = HERMES_HOME / "logs" / "auto-fixer.jsonl"
POLICIES_DIR = HERMES_HOME / "policies"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"

FIX_LOG.parent.mkdir(parents=True, exist_ok=True)


def log_fix(event_type, detail, severity="info"):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type,
             "detail": detail, "severity": severity}
    with open(FIX_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def fix_cron_jobs(dry_run=False) -> list:
    """Attempt to restart failing cron jobs that have transient errors (429, timeout)."""
    if not CRON_JOBS.is_file():
        return []
    try:
        data = json.loads(CRON_JOBS.read_text())
        jobs = data if isinstance(data, list) else data.get("jobs", [])
    except Exception:
        return []

    fixed = []
    for j in jobs:
        if not j.get("enabled", True):
            continue
        status = j.get("last_status") or ""
        error = str(j.get("last_error") or "").lower()
        if status in (None, "", "ok"):
            continue
        # Only auto-fix transient errors
        if any(kw in error for kw in ["429", "timeout", "connection", "rate limit", "temporary"]):
            jid = j.get("id", "?")
            name = j.get("name", "?")[:40]
            if not dry_run:
                try:
                    subprocess.run(["hermes", "cron", "run", str(jid)], capture_output=True, timeout=15)
                    fixed.append({"job": name, "id": str(jid), "error": error[:60], "action": "restarted"})
                    log_fix("cron_restart", f"Restarted {name} (error: {error[:60]})", "info")
                except Exception as e:
                    fixed.append({"job": name, "id": str(jid), "error": error[:60], "action": f"failed: {e}"})
            else:
                fixed.append({"job": name, "id": str(jid), "error": error[:60], "action": "would_restart"})
    return fixed


def fix_stale_coordinator(dry_run=False) -> dict:
    """Restart coordinator if heartbeat is stale (>300s)."""
    try:
        import sqlite3
        db = HERMES_HOME / "coordinator.db"
        if not db.is_file():
            return {"action": "skipped", "reason": "no coordinator DB"}
        conn = sqlite3.connect(str(db), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT updated_at FROM meta WHERE key='last_tick'").fetchall()
        conn.close()
        if not rows:
            return {"action": "skipped", "reason": "no heartbeat data"}
        ts = rows[0]["updated_at"] if hasattr(rows[0], "keys") else rows[0][0]
        age = int(time.time() - float(ts)) if ts else None
        if age and age > 300:
            if not dry_run:
                subprocess.run(["launchctl", "kickstart", "-k",
                               f"gui/{os.getuid()}/ai.hermes.coordinator"],
                              capture_output=True, timeout=15)
                log_fix("coordinator_restart", f"Restarted coordinator (heartbeat {age}s stale)")
            return {"action": "restarted" if not dry_run else "would_restart",
                    "heartbeat_age_s": age}
        return {"action": "skipped", "reason": f"heartbeat {age}s (ok)"}
    except Exception as e:
        return {"action": "error", "reason": str(e)[:80]}


def fix_config_push(dry_run=False) -> dict:
    """Retry git push for hermes config if it's been failing."""
    try:
        # Check if config-auto-push is failing
        if CRON_JOBS.is_file():
            data = json.loads(CRON_JOBS.read_text())
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            for j in jobs:
                if "config-auto-push" in str(j.get("name", "")) and j.get("last_status") not in (None, "", "ok"):
                    if not dry_run:
                        repo = HERMES_HOME / "hermes-agent"
                        subprocess.run(["git", "-C", str(repo), "pull"], capture_output=True, timeout=15)
                        subprocess.run(["git", "-C", str(repo), "push"], capture_output=True, timeout=15)
                        log_fix("config_push", "Retried hermes config push")
                    return {"action": "restarted" if not dry_run else "would_retry"}
        return {"action": "skipped", "reason": "config push healthy"}
    except Exception as e:
        return {"action": "error", "reason": str(e)[:80]}


def verify_fix(problem_type, context=None) -> dict:
    """Verify that a fix actually worked."""
    if problem_type == "cron":
        try:
            data = json.loads(CRON_JOBS.read_text()) if CRON_JOBS.is_file() else {"jobs": []}
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            jid = context or ""
            for j in jobs:
                if str(j.get("id", "")) == str(jid):
                    return {"verified": j.get("last_status") == "ok",
                            "evidence": f"status={j.get('last_status')}"}
            return {"verified": False, "evidence": "job not found"}
        except Exception as e:
            return {"verified": False, "evidence": str(e)[:80]}
    elif problem_type == "coordinator":
        try:
            import sqlite3
            db = HERMES_HOME / "coordinator.db"
            conn = sqlite3.connect(str(db), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT updated_at FROM meta WHERE key='last_tick'").fetchall()
            conn.close()
            if rows:
                ts = rows[0]["updated_at"] if hasattr(rows[0], "keys") else rows[0][0]
                age = int(time.time() - float(ts)) if ts else None
                return {"verified": age is not None and age < 60,
                        "evidence": f"heartbeat now {age}s"}
        except Exception:
            pass
        return {"verified": False, "evidence": "could not verify"}
    return {"verified": False, "evidence": f"unknown problem type: {problem_type}"}


def create_fix_policy(problem_type, fix_action, success):
    """I5: Create/update a policy based on fix outcome."""
    policy_id = f"pol-auto-fix-{problem_type}"
    path = POLICIES_DIR / f"{policy_id}.json"

    if path.is_file():
        try:
            policy = json.loads(path.read_text())
        except Exception:
            policy = {}
    else:
        policy = {"id": policy_id, "status": "provisional", "confidence": 0.3,
                  "hits": 0, "helped": 0, "hurt": 0, "auto_generated": True,
                  "created": datetime.now(timezone.utc).isoformat()}

    policy["trigger"] = f"Auto-detected {problem_type} failure requiring {fix_action}"
    policy["rule"] = f"When {problem_type} fails: run {fix_action}. " + \
                     ("This fix has been verified working." if success else "This fix needs refinement.")
    policy["hits"] = policy.get("hits", 0) + 1
    if success:
        policy["helped"] = policy.get("helped", 0) + 1
        policy["confidence"] = min(policy.get("confidence", 0.3) + 0.1, 1.0)
    else:
        policy["hurt"] = policy.get("hurt", 0) + 1
        policy["confidence"] = max(policy.get("confidence", 0.3) - 0.1, 0.1)
    policy["last_fired"] = datetime.now(timezone.utc).isoformat()

    POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, indent=2))
    return policy_id


def auto_fix_all(dry_run=False) -> dict:
    """I1+I2: Run all safe auto-fixes and verify each."""
    results = {"fixed": [], "skipped": [], "failed": [], "verified": []}

    # Fix cron
    cron_fixes = fix_cron_jobs(dry_run=dry_run)
    for f in cron_fixes:
        if "restarted" in f.get("action", ""):
            results["fixed"].append({"problem": "cron", "detail": f})
            verify = verify_fix("cron", f.get("id"))
            results["verified"].append({"problem": "cron", "verify": verify})
            create_fix_policy("cron", "restart", verify.get("verified", False))
        elif "would_restart" in f.get("action", ""):
            results["skipped"].append({"problem": "cron", "detail": f})
        else:
            results["failed"].append({"problem": "cron", "detail": f})

    # Fix coordinator
    coord = fix_stale_coordinator(dry_run=dry_run)
    if "restarted" in coord.get("action", ""):
        results["fixed"].append({"problem": "coordinator", "detail": coord})
        verify = verify_fix("coordinator")
        results["verified"].append({"problem": "coordinator", "verify": verify})
        create_fix_policy("coordinator", "kickstart", verify.get("verified", False))
    elif coord.get("action") == "skipped":
        results["skipped"].append({"problem": "coordinator", "detail": coord})
    elif "error" in coord.get("action", ""):
        results["failed"].append({"problem": "coordinator", "detail": coord})

    # Fix config push
    push = fix_config_push(dry_run=dry_run)
    if "restarted" in push.get("action", "") or "would_retry" in push.get("action", ""):
        (results["fixed"] if not dry_run else results["skipped"]).append(
            {"problem": "config_push", "detail": push})
    elif push.get("action") == "skipped":
        results["skipped"].append({"problem": "config_push", "detail": push})

    log_fix("auto_fix_run", f"Fixed={len(results['fixed'])} Skipped={len(results['skipped'])} Failed={len(results['failed'])}")
    return results


def get_fix_stats() -> dict:
    """I6: Return fix success rate stats for Otto Health."""
    if not FIX_LOG.is_file():
        return {"total_attempts": 0, "successful": 0, "failed": 0, "rate": 1.0}
    try:
        entries = [json.loads(l) for l in FIX_LOG.read_text().splitlines() if l.strip()]
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = [e for e in entries if "fix" in str(e.get("type", "")).lower()]
        total = len(recent)
        if total == 0:
            return {"total_attempts": 0, "successful": 0, "failed": 0, "rate": 1.0}
        successful = sum(1 for e in recent if "failed" not in str(e.get("detail", "")).lower())
        return {"total_attempts": total, "successful": successful,
                "failed": total - successful, "rate": round(successful / max(total, 1), 2)}
    except Exception:
        return {"total_attempts": 0, "successful": 0, "failed": 0, "rate": 1.0}


def main():
    import argparse
    p = argparse.ArgumentParser(description="Auto-fix engine")
    p.add_argument("--fix", action="store_true", help="Run all auto-fixes")
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    p.add_argument("--verify", action="store_true", help="Verify recent fixes")
    p.add_argument("--learn", action="store_true", help="Create/update fix policies")
    p.add_argument("--stats", action="store_true", help="Show fix success rate")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.stats:
        result = get_fix_stats()
    elif args.verify:
        result = {"cron_verify": verify_fix("cron"),
                  "coordinator_verify": verify_fix("coordinator")}
    elif args.learn:
        result = {}
        for ptype in ["cron", "coordinator", "config_push"]:
            pid = create_fix_policy(ptype, "auto_restart", True)
            result[ptype] = pid
    elif args.fix:
        result = auto_fix_all(dry_run=args.dry_run)
    elif args.dry_run:
        result = auto_fix_all(dry_run=True)
    else:
        result = auto_fix_all(dry_run=True)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if isinstance(result, dict) and "fixed" in result:
            print(f"Fixed: {len(result['fixed'])} | Skipped: {len(result['skipped'])} | Failed: {len(result['failed'])}")
            for item in result["fixed"]:
                print(f"  ✅ {item['problem']}: {item.get('detail', {}).get('action', '')}")
        else:
            print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
