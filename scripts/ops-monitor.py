#!/usr/bin/env python3
"""
ops-monitor.py — Operational health monitor (Phase 2/3 recursive self-improvement).

Runs during idle learning (Phase 2.5, between gap-finding and self-regression).
Checks the estate for known failure patterns and applies operational policies.

What it does:
1. Reads Prospector ticks → if moat is failing, applies pol-ops-prospector-moat
2. Checks API credit logs → if providers are exhausted, applies pol-ops-api-credits
3. Checks cron job health → if jobs are failing, applies pol-ops-cron-health
4. Logs every check so Otto can measure its own effectiveness
5. When it discovers a NEW pattern (no policy exists yet), proposes a policy

This is the bridge between "Otto has policies" and "Otto actively monitors and acts."
Without this, the policies exist on disk but never influence behavior.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PROSPECTOR_TICKS = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
PROSPECTOR_PAUSE = Path.home() / "Documents/code/prospector/store/scheduler/PAUSE"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
POLICIES_DIR = HERMES_HOME / "policies"
ALERT_LOG = HERMES_HOME / "logs" / "ops-monitor.jsonl"
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"


def log_event(event_type: str, detail: str, severity: str = "info"):
    """Append to the ops-monitor log."""
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "detail": detail,
        "severity": severity,
    }
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def check_prospector_moat() -> dict:
    """Check if the Prospector moat is healthy. Returns status dict."""
    if not PROSPECTOR_TICKS.is_file():
        return {"healthy": True, "reason": "no ticks file"}

    try:
        lines = PROSPECTOR_TICKS.read_text().splitlines()
        recent = lines[-10:] if len(lines) >= 10 else lines

        total = 0
        errors = 0
        last_error = None
        consecutive_errors = 0
        max_consecutive = 0

        for ln in reversed(recent):
            try:
                t = json.loads(ln)
                total += 1
                if t.get("error"):
                    errors += 1
                    consecutive_errors += 1
                    max_consecutive = max(max_consecutive, consecutive_errors)
                    if last_error is None:
                        last_error = str(t.get("error") or "")[:100]
                else:
                    consecutive_errors = 0
            except Exception:
                continue

        is_paused = PROSPECTOR_PAUSE.is_file()

        result = {
            "healthy": errors < 3 or (errors < len(recent) * 0.5),
            "total_checked": total,
            "errors": errors,
            "consecutive_errors": max_consecutive,
            "last_error": last_error,
            "paused": is_paused,
        }

        # Apply policy: auto-pause after 5+ consecutive failures
        if max_consecutive >= 5 and not is_paused:
            PROSPECTOR_PAUSE.parent.mkdir(parents=True, exist_ok=True)
            PROSPECTOR_PAUSE.touch()
            log_event(
                "moat_auto_pause",
                f"Auto-paused Prospector after {max_consecutive} consecutive moat failures. "
                f"Last error: {last_error}",
                "warning",
            )
            result["action_taken"] = "auto_paused"

        # Auto-resume: if moat is healthy and PAUSE exists, clear it
        if errors == 0 and is_paused and max_consecutive == 0:
            PROSPECTOR_PAUSE.unlink()
            log_event(
                "moat_auto_resume",
                f"Auto-resumed Prospector — moat is healthy after {total} clean ticks",
                "info",
            )
            result["action_taken"] = "auto_resumed"
            # Notify
            try:
                subprocess.run(
                    ["hermes", "send", "--to", "telegram",
                     "🟢 Prospector auto-resumed — moat is healthy. Generation can continue."],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass

        # Alert on 3+ consecutive failures
        if max_consecutive >= 3 and max_consecutive < 5:
            log_event(
                "moat_degraded",
                f"Prospector moat degraded: {max_consecutive} consecutive failures, "
                f"{errors}/{total} recent ticks failed",
                "warning",
            )
        # Push notification via hermes send for critical events
        if max_consecutive >= 3:
            try:
                msg = f"🔴 Prospector moat {'auto-paused' if max_consecutive >= 5 else 'degraded'}: {max_consecutive} consecutive failures. Last: {str(last_error or '')[:80]}"
                subprocess.run(
                    ["hermes", "send", "--to", "telegram", msg],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass

        return result

    except Exception as e:
        return {"healthy": False, "reason": f"probe failed: {e}"}


def check_api_credits() -> dict:
    """Check recent error logs for API credit exhaustion patterns."""
    if not ERROR_LOG.is_file():
        return {"healthy": True, "reason": "no error log"}

    try:
        lines = ERROR_LOG.read_text().splitlines()
        recent = lines[-500:] if len(lines) >= 500 else lines
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%d")

        credit_hits = {
            "anthropic_credit_low": 0,
            "cursor_exhausted": 0,
            "token_limit_429": 0,
        }

        for line in recent:
            line_lower = line.lower()
            if cutoff not in line[:20]:
                continue
            if "credit balance is too low" in line_lower:
                credit_hits["anthropic_credit_low"] += 1
            if "usage limit" in line_lower and "cursor" in line_lower:
                credit_hits["cursor_exhausted"] += 1
            if "429" in line and "token" in line_lower:
                credit_hits["token_limit_429"] += 1

        issues = {k: v for k, v in credit_hits.items() if v > 0}
        healthy = len(issues) == 0

        if not healthy:
            issue_list = ", ".join(f"{k}: {v}x" for k, v in issues.items())
            log_event(
                "api_credit_warning",
                f"API credit issues in last 6h: {issue_list}",
                "warning",
            )

        return {"healthy": healthy, "issues": issues}

    except Exception as e:
        return {"healthy": False, "reason": f"probe failed: {e}"}


def check_cron_health() -> dict:
    """Check cron job health. Returns status dict."""
    if not CRON_JOBS.is_file():
        return {"healthy": True, "reason": "no cron config"}

    try:
        data = json.loads(CRON_JOBS.read_text())
        jobs = data if isinstance(data, list) else data.get("jobs", [])

        failing = []
        disabled_with_error = []

        for j in jobs:
            status = j.get("last_status") or ""
            enabled = j.get("enabled", True)
            name = j.get("name", "?")[:40]

            if not enabled and status not in (None, "", "ok"):
                disabled_with_error.append({"name": name, "status": status})

            if enabled and status not in (None, "", "ok"):
                failing.append({
                    "name": name,
                    "status": status,
                    "error": str(j.get("last_error") or "")[:60],
                })

        healthy = len(failing) == 0

        if failing:
            fail_names = ", ".join(j["name"][:30] for j in failing[:3])
            log_event(
                "cron_failures",
                f"{len(failing)} cron jobs failing: {fail_names}",
                "warning" if len(failing) < 3 else "error",
            )

        if disabled_with_error:
            log_event(
                "cron_orphans",
                f"{len(disabled_with_error)} disabled cron jobs with error status — invisible orphans",
                "warning",
            )

        return {
            "healthy": healthy,
            "total": len(jobs),
            "failing": failing,
            "disabled_with_error": disabled_with_error,
        }

    except Exception as e:
        return {"healthy": False, "reason": f"probe failed: {e}"}


def propose_policy(domain: str, finding: str, evidence: str):
    """When Otto discovers a pattern with no policy, propose one."""
    policy_id = f"pol-auto-{domain}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

    existing = set()
    if POLICIES_DIR.is_dir():
        for f in POLICIES_DIR.iterdir():
            if f.suffix == ".json":
                try:
                    p = json.loads(f.read_text())
                    existing.add(p.get("trigger", ""))
                except Exception:
                    pass

    # Don't create duplicates
    if finding[:80] in existing:
        return None

    policy = {
        "id": policy_id,
        "status": "provisional",
        "trigger": finding[:200],
        "rule": f"Auto-detected pattern: {finding[:200]}. Monitor and alert if it recurs.",
        "scope": {"domain": f"operations/{domain}", "auto_generated": True},
        "confidence": 0.3,
        "hits": 0,
        "helped": 0,
        "hurt": 0,
        "created": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence[:300],
    }

    path = POLICIES_DIR / f"{policy_id}.json"
    path.write_text(json.dumps(policy, indent=2))
    log_event("policy_proposed", f"New policy {policy_id}: {finding[:100]}", "info")
    return policy_id


def run_all_checks():
    """Run all operational checks. Called by idle-learning pipeline."""
    results = {
        "moat": check_prospector_moat(),
        "credits": check_api_credits(),
        "cron": check_cron_health(),
    }

    # Check if any policy actions were taken
    actions = []
    for check_name, result in results.items():
        if result.get("action_taken"):
            actions.append(f"{check_name}: {result['action_taken']}")

    # Propose policies for new patterns
    proposed = []
    if not results["moat"]["healthy"] and results["moat"].get("consecutive_errors", 0) >= 3:
        pid = propose_policy(
            "prospector-moat",
            f"Prospector moat failing: {results['moat'].get('consecutive_errors')} consecutive errors",
            f"Detected {results['moat'].get('errors')} errors in {results['moat'].get('total_checked')} ticks",
        )
        if pid:
            proposed.append(pid)

    if not results["credits"]["healthy"]:
        issues = results["credits"].get("issues", {})
        pid = propose_policy(
            "api-credits",
            f"API credit exhaustion detected: {json.dumps(issues)}",
            f"Found credit issues in error logs",
        )
        if pid:
            proposed.append(pid)

    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "results": {
            k: {"healthy": v.get("healthy"), "detail": str(v)[:200]}
            for k, v in results.items()
        },
        "actions_taken": actions,
        "policies_proposed": proposed,
    }

    return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Operational health monitor")
    parser.add_argument("--check", choices=["moat", "credits", "cron", "all"],
                        default="all", help="Which check to run")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.check == "moat":
        result = check_prospector_moat()
    elif args.check == "credits":
        result = check_api_credits()
    elif args.check == "cron":
        result = check_cron_health()
    else:
        result = run_all_checks()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if isinstance(result, dict) and "results" in result:
            for k, v in result["results"].items():
                status = "🟢" if v["healthy"] else "🔴"
                print(f"  {status} {k}: {v['detail'][:80]}")
            if result["actions_taken"]:
                print(f"  ⚡ Actions: {', '.join(result['actions_taken'])}")
            if result["policies_proposed"]:
                print(f"  📝 Proposed: {', '.join(result['policies_proposed'])}")
        else:
            print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
