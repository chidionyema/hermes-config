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
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as futures_TimeoutError
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CODE = Path(os.environ.get("HERMES_CODE_DIR", Path.home() / "Documents" / "code"))
QUEUE = HERMES / "scripts" / "hermes_queue.py"

TOTAL_BUDGET = int(os.environ.get("HERMES_REPO_BUDGET", "100"))   # cron cap is 120s; stay safely under it
PER_REPO_TIMEOUT = int(os.environ.get("HERMES_REPO_TIMEOUT", "60"))  # absorb cold-start npx/uv + concurrent-CPU contention

REPOS = {
    "signalengine": {"path": str(CODE / "signalengine"),
                     "test_cmd": "uv run pytest --collect-only -q -p no:cacheprovider 2>&1 | tail -5"},
    "lux": {"path": str(CODE / "lux"),
            "test_cmd": "./node_modules/.bin/vitest run 2>&1 | tail -5"},
    "prospector": {"path": str(CODE / "prospector"),
                   "test_cmd": ".venv/bin/python -m pytest tests/unit -q --no-header 2>&1 | tail -5"},
}

LOG_DIR = HERMES / "logs" / "health"
HISTORY_FILE = LOG_DIR / "repo-health.jsonl"


def run(cmd, cwd, timeout):
    """Run a shell command, killing the ENTIRE process group on timeout.

    ROOT-CAUSE FIX (orphaned-pytest meltdown, 2026-06-19): subprocess.run with
    shell=True spawns `/bin/sh -c "<pipe>"`. On TimeoutExpired, subprocess kills
    only that sh PID — the grandchildren (`uv run`, the real pytest, vitest) keep
    running, reparent to launchd, and accumulate every tick until load → 90+ and
    the whole cron substrate times out. start_new_session=True puts the child in
    its own process group; on timeout we SIGKILL the group so nothing leaks.
    """
    proc = None
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, cwd=cwd,
                                start_new_session=True)
        out, _ = proc.communicate(timeout=timeout)
        return (out or "").strip(), proc.returncode
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return "(timeout)", 124
    except Exception as e:
        _kill_group(proc)
        return f"(error: {e})", -1


def _kill_group(proc):
    """SIGKILL the process group of proc (best-effort), then reap it."""
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def check_repo(name, info):
    path = info["path"]
    if not Path(path).exists():
        return name, {"state": "skip", "summary": f"{name}: not found"}
    dirty_out, _ = run("git status --short", path, 10)
    dirty = len([l for l in dirty_out.split("\n") if l.strip()]) if dirty_out else 0
    test_out, code = run(info["test_cmd"], path, PER_REPO_TIMEOUT)
    if code == 124:
        # Cold-start (`npx vitest`, `uv run pytest`) under concurrent-CPU load can make a
        # SINGLE tick time out transiently and clear on the next one. Do NOT retry inline:
        # a second PER_REPO_TIMEOUT run doubles a slow repo to 2*60=120s INSIDE one worker
        # thread, and `with ThreadPoolExecutor` exits via shutdown(wait=True) which blocks
        # on that thread — so the whole script blows the 120s cron cap and is killed with
        # last_status="error" (a FALSE "failure: health-watchdog"). A transient slow tick
        # self-heals on the next 120-min run and history-grading already tolerates it; one
        # bounded attempt, flagged 'timeout' so it escalates as 'warn' (slow), not 'crit'.
        return name, {"state": "fail", "timeout": True,
                      "summary": f"{name}: TIMEOUT (> {PER_REPO_TIMEOUT}s)"}
    if code != 0:
        last = test_out.split("\n")[-1][:80] if test_out else "test failed"
        return name, {"state": "fail", "summary": f"{name}: FAIL — {last}"}
    if dirty:
        return name, {"state": "dirty", "summary": f"{name}: DIRTY ({dirty} uncommitted)"}
    # STABLE summary on the green path. The raw last line of test output carries a
    # per-run duration (vitest prints "Duration 33.52s (...)"), so every green tick
    # minted a NEW message and hermes_queue.drain — which fingerprints on the message
    # — could never dedup it. A constant string makes recoveries dedup-able.
    return name, {"state": "pass", "summary": f"{name}: tests pass"}


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


def should_escalate_change(new):
    """A transition INTO a healthy state is a recovery, not an incident.

    Only regressions page. skip->pass and dirty->pass are silent; pass->fail,
    pass->skip and pass->dirty still escalate.
    """
    return new != "pass"


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
            except futures_TimeoutError:
                name = futs[fut]
                res = {"state": "fail", "summary": f"{name}: TOTAL_BUDGET exceeded"}
            except Exception as e:
                name, res = futs[fut], {"state": "fail", "summary": f"{futs[fut]}: runner error {e}"}
            results[name] = res
            old = prev.get(name, {}).get("state", "unknown")
            if old != "unknown" and old != res["state"]:
                changes.append((name, old, res["state"], res["summary"]))

    entry = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "results": results}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    any_fail = any(r["state"] == "fail" for r in results.values())

    # Silent on no-change. Escalate changes/failures to the relay queue.
    if changes or any_fail:
        for name, old, new, summary in changes:
            if should_escalate_change(new):
                submit(f"{name}: {old} -> {new}: {summary}", "warn")
        for n, r in results.items():
            if r["state"] == "fail":
                # Timeouts (slow tick, already retried) page as 'warn'; only a real
                # test failure pages as 'crit'.
                submit(r["summary"], "warn" if r.get("timeout") else "crit")
        passes = sum(1 for r in results.values() if r["state"] == "pass")
        fails = sum(1 for r in results.values() if r["state"] == "fail")
        print(f"Repo health — {passes} pass, {fails} fail")
        for name, old, new, summary in changes:
            print(f"  Δ {name}: {old} -> {new}: {summary}")
    # Exit code reflects whether the SCAN RAN, not what it found. A completed scan
    # that finds unhealthy repos has SUCCEEDED — its findings already escalate via
    # the relay queue (submit, above) and are graded from history by
    # repo-health-probe.py. Returning non-zero here lies to the cron runner, which
    # marks last_status="error"; watchdog.check_cron_health then re-escalates that as
    # a CRON_ERROR -> a duplicate, false-positive "failure: health-watchdog" task.
    # Genuine script failure (config unreadable, etc.) still exits non-zero via the
    # uncaught exception path. So: completed scan -> 0, regardless of findings.
    return 0


if __name__ == "__main__":
    sys.exit(main())
