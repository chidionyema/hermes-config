#!/usr/bin/env python3
"""
diagnostics.py — Active diagnosis engine (Round E1-E4).

E1: diagnose_moat() — why is the moat down?
E2: diagnose_engine() — why is the signal engine down?
E3: credit_fix_guide() — step-by-step credit fix with URLs
E4: full_diagnostic() — report card across all subsystems

Usage:
  python3 diagnostics.py --diagnose       # E4: full diagnostic
  python3 diagnostics.py --moat           # E1: moat diagnosis
  python3 diagnostics.py --engine         # E2: engine diagnosis
  python3 diagnostics.py --fix-credits    # E3: credit fix guide
  python3 diagnostics.py --help
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"
OPS_MONITOR = HERMES_HOME / "logs" / "ops-monitor.jsonl"
TICKS_PATH = Path.home() / "Documents" / "code" / "prospector" / "store" / "scheduler" / "ticks.jsonl"
PROSPECTOR_PAUSE = Path.home() / "Documents" / "code" / "prospector" / "store" / "scheduler" / "PAUSE"


def _venv_python() -> str:
    return sys.executable or "/usr/local/bin/python3"


def _safe_read(path: Path) -> List[str]:
    try:
        if not path.is_file():
            return []
        return path.read_text(errors="replace").splitlines()
    except Exception:
        return []


def _safe_read_jsonl(path: Path) -> List[dict]:
    try:
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except Exception:
        return []


def _run(cmd: List[str], timeout: int = 15) -> Tuple[int, str, str]:
    """Run a command; return (exit_code, stdout, stderr). Never crashes."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except Exception as exc:
        return -1, "", str(exc)


# --- E1: Diagnose Moat ---

def diagnose_moat() -> dict:
    """Check network, API availability, and credits — why is the moat down?"""
    checks: List[dict] = []

    # 1. Network: ping api.cursor.sh and api.anthropic.com
    for host, label in [("api.cursor.sh", "cursor_api"), ("api.anthropic.com", "claude_api")]:
        rc, out, err = _run(["ping", "-c", "1", "-W", "3", host], timeout=10)
        if rc == 0:
            checks.append({"check": "network", "status": "pass", "detail": f"{host} reachable"})
        else:
            checks.append({"check": "network", "status": "fail",
                           "detail": f"{host} unreachable: {err or out}"})
            break  # only need one network check
    else:
        checks.append({"check": "network", "status": "pass", "detail": "Cursor and Anthropic APIs reachable"})

    # 2. Check ticks for API errors
    ticks = _safe_read_jsonl(TICKS_PATH)
    has_cursor_fail = False
    has_claude_fail = False
    last_cursor_err = ""
    last_claude_err = ""

    for tick in reversed(ticks[-20:] if len(ticks) >= 20 else ticks):
        err = tick.get("error") or ""
        if "cursor" in err.lower():
            has_cursor_fail = True
            if not last_cursor_err:
                last_cursor_err = err[:120]
        if "claude" in err.lower() or "anthropic" in err.lower():
            has_claude_fail = True
            if not last_claude_err:
                last_claude_err = err[:120]

    # Cursor API check
    if has_cursor_fail:
        if "402" in last_cursor_err or "usage limit" in last_cursor_err.lower():
            checks.append({"check": "cursor_api", "status": "fail",
                           "detail": "HTTP 402: usage limit reached"})
        elif "exhausted" in last_cursor_err.lower() or "ProviderExhausted" in last_cursor_err:
            checks.append({"check": "cursor_api", "status": "fail",
                           "detail": "Provider exhausted after retries"})
        else:
            checks.append({"check": "cursor_api", "status": "fail",
                           "detail": f"Error: {last_cursor_err[:80]}"})
    else:
        checks.append({"check": "cursor_api", "status": "pass", "detail": "No recent Cursor API errors"})

    # Claude API check
    if has_claude_fail:
        if "400" in last_claude_err or "credit balance" in last_claude_err.lower():
            checks.append({"check": "claude_api", "status": "fail",
                           "detail": "HTTP 400: credit balance too low"})
        elif "exhausted" in last_claude_err.lower():
            checks.append({"check": "claude_api", "status": "fail",
                           "detail": "Claude provider exhausted"})
        else:
            checks.append({"check": "claude_api", "status": "fail",
                           "detail": f"Error: {last_claude_err[:80]}"})
    else:
        checks.append({"check": "claude_api", "status": "pass", "detail": "No recent Claude API errors"})

    # Determine root cause
    failures = [c for c in checks if c["status"] == "fail"]
    all_down = len(failures) >= 2
    cursor_down = any("cursor" in c.get("check", "") for c in failures)
    claude_down = any("claude" in c.get("check", "") for c in failures)

    if all_down:
        root_cause = "Both Cursor and Claude credits exhausted"
        fix = ("1. Top up Cursor at cursor.sh/account\n"
               "2. Add Anthropic credits at console.anthropic.com\n"
               "3. Run `otto diagnose moat` to verify")
    elif cursor_down:
        root_cause = "Cursor API unavailable or credits exhausted"
        fix = "Top up Cursor at cursor.sh/account, then run `otto diagnose moat` to verify"
    elif claude_down:
        root_cause = "Claude API unavailable or credits exhausted"
        fix = "Add Anthropic credits at console.anthropic.com, then run `otto diagnose moat` to verify"
    elif not failures:
        root_cause = "No API issues detected"
        fix = "Moat appears healthy. Check Prospector daemon: `prospector daemons`"
        return {"status": "up", "checks": checks, "root_cause": root_cause, "fix": fix}
    else:
        root_cause = "Network connectivity issue"
        fix = "Check internet connection and DNS, then retry"

    status = "down" if failures else "degraded"
    return {
        "status": status,
        "checks": checks,
        "root_cause": root_cause,
        "fix": fix,
    }


# --- E2: Diagnose Engine ---

def diagnose_engine() -> dict:
    """Check if the signal engine daemon is running and healthy."""
    checks: List[dict] = []

    # 1. Check if signal engine process is running
    rc, out, err = _run(["pgrep", "-f", "signal_engine"], timeout=5)
    if rc == 0 and out.strip():
        checks.append({"check": "process", "status": "pass", "detail": f"Signal engine running (PID: {out.strip().split()[0]})"})
    else:
        checks.append({"check": "process", "status": "fail", "detail": "Signal engine daemon not running"})

    # 2. Check if launchctl has it loaded
    rc, out, err = _run(["launchctl", "list"], timeout=5)
    has_signal = "signal" in out.lower() or "trading" in out.lower()
    checks.append({"check": "launchd", "status": "pass" if has_signal else "warn",
                   "detail": "Signal engine loaded in launchctl" if has_signal else "Signal engine not found in launchctl"})

    # 3. Check exchange API connectivity
    rc, out, err = _run(["curl", "-s", "--connect-timeout", "5", "--max-time", "10", "https://api-paper.alpaca.markets/v2/clock"], timeout=15)
    if rc == 0 and out:
        checks.append({"check": "exchange_api", "status": "pass", "detail": "Alpaca paper API reachable"})
    else:
        checks.append({"check": "exchange_api", "status": "fail", "detail": f"Exchange API unreachable: {err[:80]}"})

    # 4. Check signal engine log for errors
    signal_log = HERMES_HOME / "logs" / "signal-engine.log"
    log_lines = _safe_read(signal_log)[-20:]
    recent_errors = [l for l in log_lines if "ERROR" in l.upper() or "CRITICAL" in l.upper()]
    if recent_errors:
        checks.append({"check": "logs", "status": "fail",
                       "detail": f"{len(recent_errors)} recent errors in signal engine log"})
    else:
        checks.append({"check": "logs", "status": "pass", "detail": "No recent signal engine errors"})

    failures = [c for c in checks if c["status"] == "fail"]
    return {
        "status": "down" if len(failures) >= 2 else ("degraded" if failures else "up"),
        "checks": checks,
        "suggestion": ("Run `restart signal engine` to attempt recovery." if failures
                        else "Signal engine appears healthy."),
    }


# --- E3: Credit Fix Guide ---

def credit_fix_guide() -> dict:
    """Determine which providers are exhausted and return fix steps."""
    lines = _safe_read(ERROR_LOG)[-200:]
    ops = _safe_read_jsonl(OPS_MONITOR)

    cursor_exhausted = False
    claude_exhausted = False

    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in ("cursor",)) and any(kw in lower for kw in ("usage limit", "exhausted", "402")):
            cursor_exhausted = True
        if any(kw in lower for kw in ("claude", "anthropic")) and any(kw in lower for kw in ("credit", "exhausted", "400", "balance")):
            claude_exhausted = True

    # Also check ops-monitor
    for entry in ops:
        detail = (entry.get("detail") or "").lower()
        if "cursor" in detail and any(kw in detail for kw in ("exhaust", "limit", "usage")):
            cursor_exhausted = True
        if ("claude" in detail or "anthropic" in detail) and any(kw in detail for kw in ("exhaust", "credit", "balance")):
            claude_exhausted = True

    steps = []
    providers = []
    estimated_cost = 0
    estimated_time = "2 minutes"

    if cursor_exhausted:
        providers.append("Cursor")
        steps.append({
            "step": 1,
            "provider": "Cursor",
            "action": "Go to cursor.sh/account",
            "url": "https://cursor.sh/account",
            "detail": "Top up your Cursor subscription or usage credits.",
        })
        estimated_cost += 20

    if claude_exhausted:
        providers.append("Claude/Anthropic")
        steps.append({
            "step": len(steps) + 1,
            "provider": "Claude (Anthropic)",
            "action": "Go to console.anthropic.com",
            "url": "https://console.anthropic.com",
            "detail": "Add credits or check your API billing status.",
        })
        estimated_cost += 25

    if not providers:
        steps.append({
            "step": 1,
            "provider": "None detected",
            "action": "No obvious credit exhaustion found",
            "url": "",
            "detail": "Check errors.log and ops-monitor.jsonl for other failure causes.",
        })
        estimated_time = "unknown"

    return {
        "providers_exhausted": providers,
        "steps": steps,
        "estimated_cost_usd": estimated_cost,
        "estimated_time": estimated_time,
        "note": "After topping up, run `otto diagnose moat` to verify recovery.",
    }


# --- E4: Full Diagnostic ---

def full_diagnostic() -> dict:
    """Run all diagnostic checks; return report card."""
    report = {
        "moat": diagnose_moat(),
        "engine": diagnose_engine(),
    }

    # Additional checks
    checks: List[dict] = []

    # Cron health
    cron_jobs = HERMES_HOME / "cron" / "jobs.json"
    try:
        if cron_jobs.is_file():
            data = json.loads(cron_jobs.read_text())
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            failing = [j for j in jobs if j.get("enabled", True) and j.get("last_status") not in (None, "", "ok")]
            if failing:
                checks.append({"check": "cron", "status": "fail", "detail": f"{len(failing)} cron jobs failing"})
            else:
                checks.append({"check": "cron", "status": "pass", "detail": f"{len(jobs)} cron jobs healthy"})
        else:
            checks.append({"check": "cron", "status": "warn", "detail": "No cron jobs file"})
    except Exception:
        checks.append({"check": "cron", "status": "warn", "detail": "Could not check cron"})

    # Daemons check via launchctl
    rc, out, _ = _run(["launchctl", "list"], timeout=5)
    hermes_daemons = [l for l in out.splitlines() if "hermes" in l.lower()]
    if hermes_daemons:
        checks.append({"check": "daemons", "status": "pass", "detail": f"{len(hermes_daemons)} Hermes daemons loaded"})
    else:
        checks.append({"check": "daemons", "status": "fail", "detail": "No Hermes daemons found in launchctl"})

    # Prospector pause status
    if PROSPECTOR_PAUSE.is_file():
        checks.append({"check": "prospector", "status": "warn", "detail": "Prospector is PAUSED"})
    else:
        checks.append({"check": "prospector", "status": "pass", "detail": "Prospector scheduler active"})

    # Credit status from moat diagnosis
    moat_checks = report["moat"].get("checks", [])
    for mc in moat_checks:
        if mc["check"] in ("cursor_api", "claude_api"):
            checks.append({"check": mc["check"], "status": mc["status"], "detail": mc["detail"]})

    fail_count = sum(1 for c in checks if c["status"] == "fail")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    total = fail_count + warn_count + pass_count

    # Build summary line
    parts = []
    if fail_count:
        parts.append(f"🔴 {fail_count} failures")
    if warn_count:
        parts.append(f"🟡 {warn_count} warning{'s' if warn_count > 1 else ''}")
    parts.append(f"🟢 {pass_count} healthy")

    report["checks"] = checks
    report["summary_line"] = ", ".join(parts)
    report["total"] = total
    report["fail_count"] = fail_count
    report["warn_count"] = warn_count
    report["pass_count"] = pass_count

    return report


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: diagnostics.py [--diagnose|--moat|--engine|--fix-credits]")
        sys.exit(0)

    if "--diagnose" in args or "--full" in args:
        result = full_diagnostic()
        print(json.dumps(result, indent=2, default=str))
    elif "--moat" in args:
        result = diagnose_moat()
        print(json.dumps(result, indent=2, default=str))
    elif "--engine" in args:
        result = diagnose_engine()
        print(json.dumps(result, indent=2, default=str))
    elif "--fix-credits" in args:
        result = credit_fix_guide()
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Unknown arg: {args}")
        sys.exit(2)


if __name__ == "__main__":
    main()
