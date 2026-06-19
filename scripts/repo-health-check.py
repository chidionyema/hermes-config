#!/usr/bin/env python3
"""Multi-repo health check — PARALLEL, budgeted (Ball: 5c).

ROOT CAUSE THIS REPLACES: 3 repos were checked SERIALLY, each with a 120s test
timeout, under a 120s cron cap — so a single slow repo blew the whole cron budget
and the later repos never ran. This rewrite:
  - runs every repo CONCURRENTLY (wall-clock = slowest repo, not the sum),
  - declares a hard TOTAL BUDGET under the cron cap and a strict per-repo timeout,
  - keeps the state file + silent-on-no-change contract,
  - escalates changes/failures to the relay queue (deliver:local) instead of raw stdout.
Missing repos are reported as 'skip' (existence-aware — never a false 'pass').
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as futures_TimeoutError
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CODE = Path(os.environ.get("HERMES_CODE_DIR", Path.home() / "Documents" / "code"))
QUEUE = HERMES / "scripts" / "hermes_queue.py"

TOTAL_BUDGET = int(os.environ.get("HERMES_REPO_BUDGET", "25"))   # < 30s; cron has 120s but we don't need all of it
PER_REPO_TIMEOUT = int(os.environ.get("HERMES_REPO_TIMEOUT", "20"))  # hard cap so the sum can't bust TOTAL_BUDGET

REPOS = {
    "signalengine": {"path": str(CODE / "signalengine"),
                     "test_cmd": "uv run pytest -q --no-header --tb=line -p no:cacheprovider 2>&1 | tail -5"},
    "lux": {"path": str(CODE / "lux"),
            "test_cmd": "npx jest --passWithNoTests --silent 2>&1 | tail -5"},
    "prospector": {"path": str(CODE / "prospector"),
                   "test_cmd": ".venv/bin/python -m pytest -q --no-header 2>&1 | tail -5"},
}

LOG_DIR = HERMES / "logs" / "health"
HISTORY_FILE = LOG_DIR / "repo-health.jsonl"


def run(cmd, cwd, timeout):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", 124
    except Exception as e:
        return f"(error: {e})", -1


def check_repo(name, info):
    path = info["path"]
    if not Path(path).exists():
        return name, {"state": "skip", "summary": f"{name}: not found"}
    dirty_out, _ = run("git status --short", path, 10)
    dirty = len([l for l in dirty_out.split("\n") if l.strip()]) if dirty_out else 0
    test_out, code = run(info["test_cmd"], path, PER_REPO_TIMEOUT)
    if code == 124:
        return name, {"state": "fail", "summary": f"{name}: TIMEOUT (> {PER_REPO_TIMEOUT}s)"}
    if code != 0:
        last = test_out.split("\n")[-1][:80] if test_out else "test failed"
        return name, {"state": "fail", "summary": f"{name}: FAIL — {last}"}
    if dirty:
        return name, {"state": "dirty", "summary": f"{name}: DIRTY ({dirty} uncommitted)"}
    last = test_out.split("\n")[-1][:80] if test_out else "all pass"
    return name, {"state": "pass", "summary": f"{name}: {last}"}


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    try:
        lines = HISTORY_FILE.read_text().splitlines()
        return json.loads(lines[-1]) if lines else {}
    except (OSError, json.JSONDecodeError, IndexError):
        return {}


def submit(msg, severity):
    if QUEUE.exists():
        run(f'{sys.executable} {QUEUE} submit --source repo-health --severity {severity} '
            f'--message {json.dumps(msg)}', None, 10)


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    prev = load_history().get("results", {})
    results, changes = {}, []

    # Parallel: wall-clock is the slowest repo, bounded by TOTAL_BUDGET.
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(len(REPOS), 1)) as ex:
        futs = {ex.submit(check_repo, n, i): n for n, i in REPOS.items()}
        for fut in futs:
            remaining = max(1, TOTAL_BUDGET - (time.monotonic() - t_start))
            try:
                name, res = fut.result(timeout=remaining)
            except futures.TimeoutError:
                name = futs[fut]
                res = {"state": "fail", "summary": f"{name}: TOTAL_BUDGET exceeded"}
            except Exception as e:
                name, res = futs[fut], {"state": "fail", "summary": f"{futs[fut]}: runner error {e}"}
            results[name] = res
            old = prev.get(name, {}).get("state", "unknown")
            if old != "unknown" and old != res["state"]:
                changes.append(f"{name}: {old} -> {res['state']}: {res['summary']}")

    entry = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "results": results}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    any_fail = any(r["state"] == "fail" for r in results.values())

    # Silent on no-change. Escalate changes/failures to the relay queue.
    if changes or any_fail:
        for c in changes:
            submit(c, "warn")
        for n, r in results.items():
            if r["state"] == "fail":
                submit(r["summary"], "crit")
        passes = sum(1 for r in results.values() if r["state"] == "pass")
        fails = sum(1 for r in results.values() if r["state"] == "fail")
        print(f"Repo health — {passes} pass, {fails} fail")
        for c in changes:
            print(f"  Δ {c}")
        return 1 if any_fail else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
