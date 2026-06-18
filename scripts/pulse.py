#!/usr/bin/env python3
"""
Otto Pulse — lightweight status dashboard generator.
Runs every 15 minutes via cron (no_agent mode).
Silent when everything is green. Surfaces alerts when something breaks.

Output: a compact Telegram-friendly status message.
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

REPOS = {
    "Signal": {"path": os.path.expanduser("~/Documents/code/signalengine"), "test_cmd": "uv run pytest -q -m 'not slow' --no-header --tb=line -p no:cacheprovider 2>&1 | tail -3"},
    "Prospector": {"path": os.path.expanduser("~/Documents/code/prospector"), "test_cmd": ".venv/bin/python -m pytest -q --no-header --ignore=tests/test_ui_theme.py 2>&1 | tail -3"},
    "Prospector .NET": {"path": os.path.expanduser("~/Documents/code/prospector/store_platform"), "test_cmd": "dotnet test src/Store.Tests/ --no-build --no-restore 2>&1 | tail -2"},
    "LUX": {"path": os.path.expanduser("~/Documents/code/lux"), "test_cmd": "npx jest --passWithNoTests --silent 2>&1 | tail -3"},
}

def run(cmd, cwd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.stdout.strip() or r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return str(e), -1

def check_repo(name, info):
    out, code = run(info["test_cmd"], info["path"])
    # check git status for uncommitted
    git_out, _ = run("git status --short", info["path"], timeout=10)
    uncommitted = len([l for l in git_out.split("\n") if l.strip()])
    
    # parse pass/fail from output
    if code != 0 and "TIMEOUT" not in out:
        return "❌", out[:200], uncommitted
    elif "TIMEOUT" in out:
        return "⏳", "timed out", uncommitted
    elif "failed" in out.lower() or "error" in out.lower():
        # check if it's a real failure or just warnings
        fail_count = 0
        for line in out.split("\n"):
            if "failed" in line.lower() and "warning" not in line.lower():
                try:
                    fail_count += int(line.split("failed")[0].strip().split()[-1])
                except:
                    fail_count += 1
        if fail_count > 0:
            return "❌", out[:200], uncommitted
        return "✅", "pass", uncommitted
    else:
        return "✅", "pass", uncommitted


results = []
any_failure = False

for name, info in REPOS.items():
    status, detail, uncommitted = check_repo(name, info)
    if status != "✅":
        any_failure = True
    results.append({"name": name, "status": status, "uncommitted": uncommitted})

# Build output
now = datetime.now().strftime("%H:%M")

# Only emit if there's a failure — stay silent when green
if any_failure:
    lines = [f"⚠️ **Pulse {now}**"]
    for r in results:
        icon = r["status"]
        extra = f" (+{r['uncommitted']} unstaged)" if r["uncommitted"] > 5 else ""
        if r["status"] != "✅":
            lines.append(f"{icon} {r['name']}{extra}")
    print("\n".join(lines))
    sys.exit(0)

# Every 4th check, emit a heartbeat so user knows it's alive
# Use minute count to decide
minute = datetime.now().minute
if minute % 60 < 5:  # first 5 min of each hour
    parts = []
    for r in results:
        extra = " +{}".format(r["uncommitted"]) if r["uncommitted"] > 0 else ""
        parts.append("{}{}".format(r["status"], extra))
    print("🟢 Pulse {} — {}".format(now, " · ".join(parts)))

# Otherwise, silent
