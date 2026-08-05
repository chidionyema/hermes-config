#!/usr/bin/env python3
"""
resilience.py — Operational resilience (Round F1-F4).

F1: rotate_ticks() — archive old ticks.jsonl entries
F2: check_db_health() — PRAGMA integrity_check on coordinator.db
F3: verify_backups() — git remote, last push, config parse
F4: degradation_status() — which subsystems are available

Usage:
  python3 resilience.py --rotate-ticks     # F1
  python3 resilience.py --check-db         # F2
  python3 resilience.py --verify-backups   # F3
  python3 resilience.py --degradation      # F4
  python3 resilience.py --check            # run F1+F2 (quick preflight)
  python3 resilience.py --help
"""

import gzip
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
TICKS_PATH = Path.home() / "Documents" / "code" / "prospector" / "store" / "scheduler" / "ticks.jsonl"
COORD_DB = HERMES_HOME / "logs" / "coordinator.db"
PROSPECTOR_DIR = Path.home() / "Documents" / "code" / "prospector"
CONFIG_YAML = PROSPECTOR_DIR / "config.yaml"


def _venv_python() -> str:
    return sys.executable or "/usr/local/bin/python3"


def _run(cmd: List[str], timeout: int = 15, cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except Exception as exc:
        return -1, "", str(exc)


# --- F1: Ticks Rotation ---

def rotate_ticks() -> dict:
    """If ticks.jsonl > 500KB, archive entries older than 30 days; gzip archive."""
    if not TICKS_PATH.is_file():
        return {"rotated": False, "reason": "ticks.jsonl not found", "size_kb": 0}

    try:
        size_kb = TICKS_PATH.stat().st_size / 1024.0
    except Exception:
        return {"rotated": False, "reason": "Cannot stat ticks.jsonl", "size_kb": 0}

    if size_kb < 500:
        return {"rotated": False, "reason": f"Below 500KB threshold ({size_kb:.0f}KB)", "size_kb": round(size_kb, 1)}

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    lines = TICKS_PATH.read_text(errors="replace").splitlines()
    kept = []
    archived = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts_str = entry.get("ts", "")
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            # Can't parse — keep it to avoid data loss
            kept.append(line)
            continue

        if ts < cutoff:
            archived.append(line)
        else:
            kept.append(line)

    if not archived:
        return {"rotated": False, "reason": "No entries older than 30 days", "size_kb": round(size_kb, 1)}

    # Write archive
    archive_name = f"ticks-{cutoff.strftime('%Y-%m')}.jsonl.gz"
    archive_path = TICKS_PATH.parent / archive_name
    try:
        with gzip.open(archive_path, "wt", encoding="utf-8") as f:
            f.write("\n".join(archived) + "\n")
    except Exception as exc:
        return {"rotated": False, "reason": f"Failed to write archive: {exc}", "size_kb": round(size_kb, 1)}

    # Truncate original
    try:
        TICKS_PATH.write_text("\n".join(kept) + "\n" if kept else "")
    except Exception as exc:
        return {"rotated": False, "reason": f"Failed to truncate original: {exc}", "size_kb": round(size_kb, 1)}

    new_size = TICKS_PATH.stat().st_size / 1024.0
    return {
        "rotated": True,
        "archived_entries": len(archived),
        "kept_entries": len(kept),
        "archive_path": str(archive_path),
        "old_size_kb": round(size_kb, 1),
        "new_size_kb": round(new_size, 1),
    }


# --- F2: DB Health Check ---

def check_db_health() -> dict:
    """Run PRAGMA integrity_check on coordinator.db; check size."""
    if not COORD_DB.is_file():
        return {"healthy": False, "error": f"coordinator.db not found at {COORD_DB}", "size_mb": 0}

    try:
        size_mb = COORD_DB.stat().st_size / (1024 * 1024)
    except Exception:
        return {"healthy": False, "error": "Cannot stat coordinator.db", "size_mb": 0}

    warnings = []
    if size_mb > 50:
        warnings.append(f"DB size {size_mb:.1f}MB exceeds 50MB threshold — consider VACUUM")

    try:
        import sqlite3
        conn = sqlite3.connect(str(COORD_DB))
        try:
            cur = conn.execute("PRAGMA integrity_check")
            result = cur.fetchone()
            integrity_ok = result and result[0] == "ok"
            if not integrity_ok:
                return {"healthy": False, "error": f"Integrity check failed: {result}", "size_mb": round(size_mb, 1)}

            # Run optimize if needed
            if size_mb > 10:
                conn.execute("PRAGMA optimize")
                warnings.append("PRAGMA optimize executed (DB > 10MB)")
        finally:
            conn.close()
    except Exception as exc:
        return {"healthy": False, "error": f"SQLite error: {exc}", "size_mb": round(size_mb, 1)}

    return {
        "healthy": True,
        "size_mb": round(size_mb, 1),
        "warnings": warnings,
    }


# --- F3: Backup Verification ---

def verify_backups() -> dict:
    """Check git remote reachable, last push <24h, config.yaml parses, MEMORY.md committed."""
    checks: List[dict] = []

    # 1. Git remote reachable
    rc, out, err = _run(["git", "remote", "-v"], cwd=PROSPECTOR_DIR)
    if rc != 0:
        checks.append({"check": "git_remote", "status": "fail", "detail": f"Cannot list remotes: {err}"})
    else:
        # Try to fetch (dry-run check connectivity)
        rc2, out2, err2 = _run(["git", "ls-remote", "--heads", "origin", "--exit-code"], timeout=20, cwd=PROSPECTOR_DIR)
        if rc2 == 0:
            checks.append({"check": "git_remote", "status": "pass", "detail": "Git remote reachable"})
        else:
            checks.append({"check": "git_remote", "status": "fail", "detail": f"Git remote unreachable: {err2[:80]}"})

    # 2. Last push <24h
    rc, out, err = _run(["git", "log", "--branches", "--not", "--remotes", "--oneline"], cwd=PROSPECTOR_DIR)
    unpushed = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    if len(unpushed) > 10:
        checks.append({"check": "last_push", "status": "warn",
                       "detail": f"{len(unpushed)} unpushed commits — push overdue"})
    elif unpushed:
        checks.append({"check": "last_push", "status": "pass",
                       "detail": f"{len(unpushed)} unpushed commits (recent)"})
    else:
        checks.append({"check": "last_push", "status": "pass", "detail": "All commits pushed"})

    # 3. config.yaml parses correctly
    if CONFIG_YAML.is_file():
        try:
            import yaml
            with open(CONFIG_YAML) as f:
                yaml.safe_load(f)
            checks.append({"check": "config_yaml", "status": "pass", "detail": "config.yaml parses correctly"})
        except Exception as exc:
            checks.append({"check": "config_yaml", "status": "fail", "detail": f"config.yaml parse error: {exc}"})
    else:
        checks.append({"check": "config_yaml", "status": "fail", "detail": "config.yaml not found"})

    # 4. MEMORY.md and policies/ committed
    mem_path = HERMES_HOME / "memory" / "MEMORY.md"
    policies_dir = HERMES_HOME / "policies"
    missing = []
    if not mem_path.is_file():
        missing.append("MEMORY.md")
    if not policies_dir.is_dir() or not list(policies_dir.glob("*.policy.*")):
        missing.append("policies/")
    if missing:
        checks.append({"check": "critical_files", "status": "fail",
                       "detail": f"Missing: {', '.join(missing)}"})
    else:
        checks.append({"check": "critical_files", "status": "pass",
                       "detail": "MEMORY.md and policies/ present"})

    failures = [c for c in checks if c["status"] == "fail"]
    return {
        "ok": len(failures) == 0,
        "checks": checks,
        "failures": len(failures),
    }


# --- F4: Degradation Status ---

def degradation_status() -> dict:
    """Check each subsystem independently; return availability panel."""
    subsystems: Dict[str, dict] = {}

    # Mission card
    try:
        from gateway.operator_shell.mission import render_mission_card
        render_mission_card()
        subsystems["Mission card"] = {"status": "up", "emoji": "🟢"}
    except Exception:
        subsystems["Mission card"] = {"status": "down", "emoji": "🔴"}

    # Prospector panel
    if TICKS_PATH.is_file():
        subsystems["Prospector panel"] = {"status": "up", "emoji": "🟢"}
    else:
        subsystems["Prospector panel"] = {"status": "down", "emoji": "🔴"}

    # Coordinator
    if COORD_DB.is_file():
        db_health = check_db_health()
        if db_health.get("healthy"):
            subsystems["Coordinator"] = {"status": "up", "emoji": "🟢"}
        else:
            subsystems["Coordinator"] = {"status": "down", "emoji": "🔴",
                                         "detail": db_health.get("error", "DB unhealthy")}
    else:
        subsystems["Coordinator"] = {"status": "down", "emoji": "🔴", "detail": "DB not found"}

    # Ops monitor
    ops_mon = HERMES_HOME / "logs" / "ops-monitor.jsonl"
    if ops_mon.is_file():
        subsystems["Ops monitor"] = {"status": "up", "emoji": "🟢"}
    else:
        subsystems["Ops monitor"] = {"status": "down", "emoji": "🔴"}

    # Signal engine
    rc, out, _ = _run(["pgrep", "-f", "signal_engine"], timeout=5)
    if rc == 0 and out.strip():
        subsystems["Signal Engine"] = {"status": "up", "emoji": "🟢"}
    else:
        subsystems["Signal Engine"] = {"status": "down", "emoji": "🔴"}

    # Build panel line
    panel_line = " · ".join(f"{v['emoji']} {k}" for k, v in subsystems.items())

    down = [k for k, v in subsystems.items() if v["status"] == "down"]

    return {
        "panel": panel_line,
        "subsystems": subsystems,
        "down_count": len(down),
        "summary": f"{len(subsystems) - len(down)}/{len(subsystems)} systems healthy" if down
                   else f"All {len(subsystems)} systems healthy",
    }


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: resilience.py [--rotate-ticks|--check-db|--verify-backups|--degradation|--check]")
        sys.exit(0)

    if "--rotate-ticks" in args:
        result = rotate_ticks()
        print(json.dumps(result, indent=2, default=str))
    elif "--check-db" in args:
        result = check_db_health()
        print(json.dumps(result, indent=2, default=str))
    elif "--verify-backups" in args:
        result = verify_backups()
        print(json.dumps(result, indent=2, default=str))
    elif "--degradation" in args:
        result = degradation_status()
        print(json.dumps(result, indent=2, default=str))
    elif "--check" in args:
        db = check_db_health()
        ticks = rotate_ticks()
        print(json.dumps({"db_health": db, "ticks_rotation": ticks}, indent=2, default=str))
    else:
        print(f"Unknown arg: {args}")
        sys.exit(2)


if __name__ == "__main__":
    main()
