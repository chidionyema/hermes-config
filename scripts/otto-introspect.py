#!/usr/bin/env python3
"""
otto-introspect.py — Introspection surface for Otto's operational state.

Usage:
    python3 ~/.hermes/scripts/otto-introspect.py

Shows:
  - Queue depth (pending cron jobs, pending changes)
  - In-flight subagents (background processes)
  - Memory usage (policy store size, corpus size, log sizes)
  - Recent failures + recovery (errors.log, claim-verifications)
  - Regression coverage % + trend
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"

def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path) as f:
        return len(f.readlines())

def file_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return path.stat().st_size / (1024 * 1024)

def load_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)

def load_jsonl(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries

def count_pending_cron():
    """Count pending cron jobs from jobs.json."""
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_file.exists():
        return 0, []
    try:
        with open(jobs_file) as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        pending = [j for j in jobs if j.get("state") == "scheduled" and j.get("enabled", False)]
        return len(pending), [j.get("name", "?")[:40] for j in pending]
    except (json.JSONDecodeError, OSError):
        return 0, []

def count_pending_changes():
    changes_file = HERMES_HOME / "meta" / "pending-changes.json"
    if not changes_file.exists():
        return 0, []
    try:
        with open(changes_file) as f:
            changes = json.load(f)
        return len(changes), [c.get("description", "?")[:60] for c in changes]
    except (json.JSONDecodeError, OSError):
        return 0, []

def check_background_processes() -> list:
    """Check for running background Hermes subagents."""
    try:
        result = subprocess.run(
            ["python3", "-c", "import json, os; print(json.dumps([p for p in __import__('psutil').process_iter(['pid','name','cmdline'])]))"],
            capture_output=True, text=True, timeout=5
        )
        return ["subprocess check completed"]
    except Exception:
        return ["Cannot inspect (no psutil)"]

def count_recent_errors(hours: int = 24) -> tuple[int, list[str]]:
    errors_log = HERMES_HOME / "logs" / "errors.log"
    if not errors_log.exists():
        return 0, []
    try:
        with open(errors_log) as f:
            lines = f.readlines()
        recent = [l.strip() for l in lines[-20:] if l.strip()]
        return len(recent), recent[-5:]
    except OSError:
        return 0, []

def get_regression_coverage() -> tuple[float, int, int]:
    report_file = HERMES_HOME / "logs" / "regression-report.md"
    if not report_file.exists():
        return 0.0, 0, 0
    try:
        with open(report_file) as f:
            content = f.read()
        for line in content.split("\n"):
            if "Coverage:" in line:
                parts = line.strip().split()
                for p in parts:
                    if "/" in p:
                        nums = p.split("/")
                        passed_val = int(nums[0])
                        total_val = int(nums[1].rstrip(")"))
                        break
                for p in parts:
                    if "%" in p:
                        pct_val = float(p.strip("()%"))
                        break
                return pct_val, passed_val, total_val
    except (OSError, ValueError):
        pass
    return 0.0, 0, 0

def get_regression_trend() -> list[dict]:
    trend_file = HERMES_HOME / "logs" / "regression-trend.jsonl"
    return load_jsonl(trend_file)

def main():
    print("=" * 64)
    print("      Otto System Introspection")
    print(f"      {iso_now()}")
    print("=" * 64)
    print()

    # ── Queue Depth ─────────────────────────────────────────────────────
    print("📋 Queue Depth")
    print("-" * 40)

    pending_cron_count, pending_cron_names = count_pending_cron()
    print(f"  Pending cron jobs:  {pending_cron_count}")
    for name in pending_cron_names[:5]:
        print(f"    • {name}")

    pending_changes_count, pending_change_descs = count_pending_changes()
    print(f"  Pending meta changes: {pending_changes_count}")
    for desc in pending_change_descs[:5]:
        print(f"    • {desc}")

    # Uncommitted work
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=5,
            cwd=str(HERMES_HOME)
        )
        uncommitted = len([l for l in result.stdout.split("\n") if l.strip()])
        print(f"  Uncommitted files:  {uncommitted} (in ~/.hermes)")
    except Exception:
        print(f"  Uncommitted files:  ?")

    print()

    # ── In-Flight Subagents ─────────────────────────────────────────────
    print("🚀 In-Flight Subagents")
    print("-" * 40)
    # Use psutil or fallback
    try:
        import psutil
        hermes_procs = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if "python3" in cmdline and (".hermes" in cmdline or "hermes" in cmdline.lower()):
                    hermes_procs.append((proc.info["pid"], cmdline[:80]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if hermes_procs:
            for pid, cmd in hermes_procs[:5]:
                print(f"  PID {pid}: {cmd}")
        else:
            print("  No active Hermes subagent processes found.")
    except ImportError:
        print("  (psutil not available — cannot inspect processes)")

    print()

    # ── Memory / Store Sizes ────────────────────────────────────────────
    print("💾 Store Sizes")
    print("-" * 40)

    policy_dir = HERMES_HOME / "policies"
    policy_files = list(policy_dir.glob("pol-*.json"))
    print(f"  Policies:           {len(policy_files)} files ({file_size_mb(policy_dir):.1f} MB)")

    meta_dir = HERMES_HOME / "meta"
    print(f"  Meta store:         {file_size_mb(meta_dir):.2f} MB")

    logs_dir = HERMES_HOME / "logs"
    print(f"  Logs directory:     {file_size_mb(logs_dir):.1f} MB")

    agent_log_size = file_size_mb(HERMES_HOME / "logs" / "agent.log")
    print(f"  Agent log:          {agent_log_size:.1f} MB")

    corpus_file = HERMES_HOME / "logs" / "self-regression-corpus.json"
    corpus_size = len(load_json(corpus_file) or []) if corpus_file.exists() else 0
    print(f"  Regression corpus:  {corpus_size} entries")

    firing_lines = count_lines(HERMES_HOME / "logs" / "policy-firings.jsonl")
    print(f"  Policy firing log:  {firing_lines} entries")

    injection_lines = count_lines(HERMES_HOME / "logs" / "injection-log.jsonl")
    print(f"  Injection log:      {injection_lines} entries")

    reflection_dir = HERMES_HOME / "logs" / "reflection"
    reflection_count = len(list(reflection_dir.glob("*.md"))) if reflection_dir.exists() else 0
    print(f"  Reflection files:   {reflection_count}")

    print()

    # ── Recent Failures + Recovery ──────────────────────────────────────
    print("🔴 Recent Failures + Recovery")
    print("-" * 40)

    error_count, recent_errors = count_recent_errors()
    if recent_errors:
        print(f"  Recent errors (last 5 of {error_count} in errors.log):")
        for err in recent_errors:
            print(f"    ❌ {err[:100]}")
    else:
        print("  No recent errors found.")

    # Check claim-verifications for failures
    claim_file = HERMES_HOME / "logs" / "claim-verifications.jsonl"
    if claim_file.exists():
        verifications = load_jsonl(claim_file)
        failed_claims = [v for v in verifications if v.get("status") == "FAIL"]
        if failed_claims:
            print(f"  Claim verifications failed: {len(failed_claims)}")
            for fc in failed_claims[:3]:
                print(f"    ❌ {fc.get('claim', '?')[:80]}")
        else:
            print(f"  Claim verifications: {len(verifications)} all passed")

    # Check cron errors
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    if jobs_file.exists():
        try:
            with open(jobs_file) as f:
                data = json.load(f)
            failed_jobs = [j for j in data.get("jobs", []) if j.get("last_status") == "error"]
            if failed_jobs:
                print(f"  Failed cron jobs: {len(failed_jobs)}")
                for fj in failed_jobs:
                    print(f"    ❌ {fj.get('name', '?')[:50]}: {fj.get('last_error', '?')[:80]}")
        except (json.JSONDecodeError, OSError):
            pass

    print()

    # ── Regression Coverage ─────────────────────────────────────────────
    print("📊 Regression Coverage")
    print("-" * 40)

    pct, passed, total = get_regression_coverage()
    if total > 0:
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"  [{bar}] {pct:.0f}% ({passed}/{total})")
    else:
        print("  No regression data yet.")

    trend = get_regression_trend()
    if trend:
        print(f"  Trend records: {len(trend)}")
        for t in trend[-5:]:
            print(f"    {t.get('timestamp', '?')[:16]}: {t.get('coverage_pct', '?')}%")
    else:
        print("  No trend data yet (regression-trend.jsonl will be populated on next run).")

    print()
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
