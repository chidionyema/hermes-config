#!/usr/bin/env python3
"""
Status engine — background cache for all project status data.

Runs every 60 seconds (or on demand). Pre-computes everything Home needs:
git status, CI status, commit age, branch names, health scores.

Home panel reads from cache — always <50ms, never blocks on git.

Commercial-grade: fast, reliable, no I/O on the render path.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

HERMES = Path.home() / ".hermes"
CODE = Path.home() / "Documents" / "code"
CACHE_FILE = HERMES / "state" / "status-cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_cache() -> dict:
    """Load cached status. Always fast, never blocks."""
    if CACHE_FILE.is_file():
        try:
            return json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"projects": {}, "health": {}, "updated_at": None}


def save_cache(data: dict):
    """Atomically write cache."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(CACHE_FILE)


def _git(cmd: list, repo: Path, timeout: int = 5) -> str:
    """Run a git command, return stdout or empty string on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo)] + cmd,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _gh_ci(repo: Path, timeout: int = 10) -> str:
    """Get latest CI status via gh CLI."""
    if not (repo / ".github" / "workflows").is_dir():
        return ""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "-R", str(repo), "-L", "1",
             "--json", "conclusion,status,displayTitle"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(repo),
        )
        if r.returncode != 0:
            return ""
        runs = json.loads(r.stdout)
        if not runs:
            return "no_runs"
        run = runs[0]
        conc = run.get("conclusion") or run.get("status") or "?"
        if conc == "success": return "pass"
        if conc in ("failure", "timed_out", "cancelled"): return "fail"
        if conc in ("in_progress", "queued", "waiting"): return "running"
        return conc
    except Exception:
        return ""


def refresh_all():
    """Refresh all project status in background. Called by cron every 60s."""
    cache = load_cache()
    
    # Load project registry
    reg_file = HERMES / "projects.json"
    if not reg_file.is_file():
        return
    
    projects = json.loads(reg_file.read_text()).get("projects", [])
    
    for p in projects:
        key = p["key"]
        primary = CODE / p.get("primary_repo", key)
        
        if not primary.is_dir():
            cache["projects"][key] = {"status": "missing", "name": p["name"]}
            continue
        
        # Collect all git/CI data in parallel-ish (sequential but fast per repo)
        branch = _git(["branch", "--show-current"], primary)
        status = _git(["status", "--porcelain"], primary)
        commit_ts = _git(["log", "-1", "--format=%ct"], primary)
        
        # Parse commit age
        age_str = "—"
        if commit_ts:
            try:
                age_s = max(0, int(time.time()) - int(commit_ts))
                if age_s < 3600: age_str = f"{age_s//60}m"
                elif age_s < 86400: age_str = f"{age_s//3600}h"
                elif age_s < 604800: age_str = f"{age_s//86400}d"
                else: age_str = f"{age_s//604800}w"
            except ValueError:
                pass
        
        git_state = "dirty" if status and len(status) > 0 else ("clean" if branch else "empty")
        ci = _gh_ci(primary)
        
        # Severity classification
        if ci == "fail":
            severity = "critical"
            emoji = "🔴"
        elif p.get("risk") in ("money", "identity") and (git_state == "dirty" or "w" in age_str):
            severity = "critical"
            emoji = "🔴"
        elif git_state == "dirty" and p.get("type") == "client":
            severity = "watch"
            emoji = "🟡"
        elif age_str.endswith("w") and p.get("status") == "active":
            severity = "watch"
            emoji = "🟡"
        else:
            severity = "clear"
            emoji = "🟢"
        
        cache["projects"][key] = {
            "key": key,
            "name": p["name"],
            "type": p.get("type", "product"),
            "status": p.get("status", "active"),
            "risk": p.get("risk", "low"),
            "git": git_state,
            "branch": branch,
            "commit_age": age_str,
            "ci": ci,
            "severity": severity,
            "emoji": emoji,
            "repos": len(p.get("repos", [primary.name])),
            "description": p.get("description", "")[:80],
        }
    
    # Health score
    try:
        sys.path.insert(0, str(HERMES / "hermes-agent"))
        from gateway.operator_shell.otto_health import _compute_score
        score = _compute_score()
        cache["health"] = {
            "score": score["score"],
            "score_pct": int(score["score"] * 100),
            "breakdown": score["breakdown"],
            "raw": score["raw"],
        }
    except Exception:
        cache["health"] = {"score": 0.5, "score_pct": 50, "breakdown": {}, "raw": {}}
    
    save_cache(cache)
    return cache


def get_cached_home_text() -> str:
    """Build Home text from cache. No I/O, no git, always <10ms."""
    cache = load_cache()
    projects = cache.get("projects", {})
    health = cache.get("health", {})
    updated = cache.get("updated_at", "never")
    
    critical = []
    watch = []
    clear = []
    
    for key, p in sorted(projects.items()):
        sev = p.get("severity", "clear")
        if sev == "critical": critical.append(p)
        elif sev == "watch": watch.append(p)
        else: clear.append(p)
    
    se = "🟢" if health.get("score", 0) >= 0.7 else ("🟡" if health.get("score", 0) >= 0.4 else "🔴")
    lines = [
        f"🏠 *Otto*",
        f"{se} {health.get('score_pct', '?')}% · {len(projects)} projects · refreshed {_time_ago(updated)}",
        "",
    ]
    
    if critical:
        lines.append("*🔴 Needs attention*")
        for p in critical:
            f = " 🔐" if p.get("risk") in ("money", "identity") else ""
            lines.append(f"• *{p['name']}*{f} — {_detail(p)}")
    
    if watch:
        lines.append("")
        lines.append("*🟡 Watch*")
        for p in watch[:3]:
            f = " 🔐" if p.get("risk") in ("money", "identity") else ""
            lines.append(f"• *{p['name']}*{f} — {_detail(p)}")
    
    if clear:
        names = ", ".join(p["name"] for p in clear[:8])
        lines.append("")
        lines.append(f"*🟢 Clear* — {names}")
    
    # Self-improvement section
    h = health
    if h:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"{se} *Learning:* {h.get('score_pct','?')}% · "
                    f"{h.get('raw',{}).get('policies_created_this_week','?')} policies · "
                    f"{h.get('raw',{}).get('total_injections','?')} injections")
        bd = h.get("breakdown", {})
        lines.append(f"   Fixes: {h.get('raw',{}).get('auto_fixes','?')} · "
                    f"Firings: {h.get('raw',{}).get('total_firings','?')} · "
                    f"Cron: {int(bd.get('cron_health',0)*100)}%")
    
    from gateway.operator_shell.panel_chrome import with_nav
    lines.append("")
    lines.append("💡 *Try:* `what's broken` · `deploy <project>` · `health` · `help`")
    
    # Buttons
    ButtonRow = list
    buttons = []
    row = []
    for p in critical[:4]:
        row.append((f"🔴 {p['name'][:14]}", f"estate:project:{p['key']}"))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    
    buttons.append([("🛠 Fix All", "estate:fix_all"), ("📊 Projects", "estate:find")])
    buttons.append([("🧠 Health", "estate:health"), ("📱 Dashboard", "estate:dashboard")])
    buttons = with_nav(buttons)
    
    return "\n".join(lines), buttons


def _detail(p: dict) -> str:
    """Human-readable status detail from cached data."""
    parts = []
    if p.get("ci") == "fail": parts.append("CI failing")
    elif p.get("ci") == "pass": parts.append("CI passing")
    if p.get("git") == "dirty": parts.append("uncommitted")
    parts.append(p.get("commit_age", "—"))
    if p.get("risk") in ("money", "identity"): parts.append(f"{p['risk']} project")
    return " · ".join(parts)


def _time_ago(iso_str: str) -> str:
    """Human-readable time ago from ISO timestamp."""
    if not iso_str or iso_str == "never":
        return "never"
    try:
        ts = datetime.fromisoformat(iso_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = max(0, (datetime.now(timezone.utc) - ts).total_seconds())
        if age < 60: return "just now"
        if age < 3600: return f"{int(age//60)}m ago"
        if age < 86400: return f"{int(age//3600)}h ago"
        return f"{int(age//86400)}d ago"
    except Exception:
        return "unknown"


def main():
    import argparse
    p = argparse.ArgumentParser(description="Status engine")
    p.add_argument("--refresh", action="store_true", help="Refresh cache now")
    p.add_argument("--daemon", action="store_true", help="Run as background daemon (every 60s)")
    p.add_argument("--home", action="store_true", help="Print cached Home text")
    args = p.parse_args()
    
    if args.refresh:
        start = time.time()
        refresh_all()
        print(f"✅ Cache refreshed ({time.time() - start:.1f}s)")
    elif args.daemon:
        print("Status engine daemon — refreshing every 60s")
        while True:
            try:
                start = time.time()
                refresh_all()
                elapsed = time.time() - start
                sleep_time = max(5, 60 - elapsed)
                print(f"  Refreshed ({elapsed:.1f}s) — next in {sleep_time:.0f}s")
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  ⚠️ Refresh failed: {e}")
                time.sleep(30)
    elif args.home:
        text, buttons = get_cached_home_text()
        print(text)


if __name__ == "__main__":
    main()
