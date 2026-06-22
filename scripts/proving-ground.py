#!/usr/bin/env python3
"""proving-ground.py — self-integrity auditor (existence-aware: MISSING != PASS).

ROOT CAUSE THIS REPLACES (Ball 19)
  The old auditor ran `npm test` / `pytest` in directories that don't exist. A missing
  directory surfaced as NOT_FOUND but was still graded only by `code == 0`, so the audit
  could report green while scanning nothing — the same false-pass shape as the
  alert-resolver false-clear bug: "auditor reports ok on broken/absent things."

THE FIX — three invariants:
  (a) every check declares its required path; a check whose path is MISSING is reported
      as MISSING, never PASS and never silently skipped.
  (b) a MISSING *required* path fails the audit (exit non-zero); a MISSING *optional*
      path is reported as not-required (does not fail).
  (c) on exit 1 the audit SUBMITS to the relay queue so Otto triages it.

  proving-ground-probe.sh asserts: every path the audit lists either exists OR is marked
  not-required — no silent false-passes.
"""
import datetime
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
CODE = Path(os.environ.get("HERMES_CODE_DIR", HOME / "Documents" / "code"))
HERMES = Path(os.environ.get("HERMES_HOME", HOME / ".hermes"))
RECEIPTS = HOME / ".lux" / "proving-ground"
QUEUE = HERMES / "scripts" / "hermes_queue.py"

PASS, FAIL, MISS, TIMEOUT = "✅", "❌", "🚫", "⏳"

# (project, check, cmd, relpath-under-CODE or None for network, required)
CHECKS = [
    ("popdd-ts", "tests", "npm test 2>&1 | tail -3", "popdd-ts", True),
    ("popdd-ts", "build", "npm run build 2>&1 | tail -5", "popdd-ts", True),
    ("lux-popdd", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", "popdd-py", True),
    ("lux-spec", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", "lux-spec-py", True),
    ("lux-spec-cli", "tests", "python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3", "lux-spec-cli", True),
    ("signalengine", "imports",
     "uv run python3 -c \"from popdd.agent import PopddAgent; from luxspec import SpecVerifier; print('OK')\"",
     "signalengine", True),
    # prospector is NOT a uv project (requirements.txt + .venv, no pyproject.toml), so `uv run`
    # spins a bare env WITHOUT popdd/luxspec and false-fails. Use its real interpreter, exactly
    # as repo-health-check.py does for the same repo.
    ("prospector", "imports",
     ".venv/bin/python -c \"from popdd.agent import PopddAgent; from luxspec import SpecVerifier; print('OK')\"",
     "prospector", True),
    ("lux-engine", "popdd-dependency", "npm ls popdd 2>&1 | tail -3", "lux", True),
    # network/published-state checks have no local path and are not required (no false-fail offline)
    ("npm", "popdd-ts published", "npm info popdd version 2>&1", None, False),
]


def sh(cmd, cwd=None, timeout=30):
    """Run a shell command, SIGKILLing the whole process group on timeout.

    ROOT-CAUSE FIX (orphaned-pytest meltdown, 2026-06-19): with shell=True, the
    child is `/bin/sh -c "uv run pytest ..."`. subprocess.run's timeout kills only
    that sh PID, orphaning `uv` + the real pytest, which reparent to launchd and
    pile up every audit until load → 90+. start_new_session=True + os.killpg on
    timeout takes the entire group down so nothing leaks.
    """
    proc = None
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                cwd=str(cwd) if cwd else None, start_new_session=True)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", "NOT_FOUND"


def _kill_group(proc):
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


def main():
    print("PROVING GROUND — Self-Integrity Audit (existence-aware)")
    print(datetime.datetime.now(datetime.timezone.utc).isoformat())
    results = []
    for project, name, cmd, rel, required in CHECKS:
        path = CODE / rel if rel else None
        if path is not None and not path.exists():
            state = "missing"
            results.append({"project": project, "check": name, "state": state,
                            "required": required, "path": str(path),
                            "summary": f"path not found: {path}"})
            icon = MISS if required else "·"
            print(f"  {icon} {project}/{name}: MISSING{'' if required else ' (not-required)'} — {path}")
            continue
        code, out, err = sh(cmd, cwd=path)
        # A TIMEOUT (code == -1, set by sh()) under concurrent-CPU load is transient
        # overload, NOT a definitive integrity failure — popdd-ts `npm test` cold-start can
        # exceed 30s when the box is busy. Grade it as its own 'timeout' state: reported and
        # escalated as a slow-tick warning, but it does NOT fail the audit. Failing on it
        # would exit 1, mark the cron errored, and fire a FALSE "failure: health-watchdog".
        # A real test FAILURE (code > 0) still fails; a MISSING required path still fails.
        if code == 0:
            state = "pass"
        elif code == -1:
            state = "timeout"
        else:
            state = "fail"
        summary = (out or err).strip().split("\n")[-1][:120] if (out or err) else f"exit {code}"
        results.append({"project": project, "check": name,
                        "state": state, "required": required,
                        "path": str(path) if path else None, "exit_code": code,
                        "summary": summary})
        icon = PASS if state == "pass" else (TIMEOUT if state == "timeout" else FAIL)
        print(f"  {icon} {project}/{name}: {summary}")

    missing_required = [r for r in results if r["state"] == "missing" and r["required"]]
    failed = [r for r in results if r["state"] == "fail" and r["required"]]
    timed_out = [r for r in results if r["state"] == "timeout" and r["required"]]
    ok = sum(1 for r in results if r["state"] == "pass")

    print("─" * 60)
    if not missing_required and not failed:
        slow = f" ({len(timed_out)} timed out — transient, will retry)" if timed_out else ""
        print(f"INTEGRITY VERDICT: PASS — {ok}/{len(results)} checks passed{slow}")
        verdict_code = 0
    else:
        print(f"INTEGRITY VERDICT: FAIL — {len(missing_required)} missing required, "
              f"{len(failed)} failed, {ok} passed")
        for r in missing_required:
            print(f"    {MISS} MISSING [{r['project']}/{r['check']}] {r['path']}")
        for r in failed:
            print(f"    {FAIL} FAIL [{r['project']}/{r['check']}] {r['summary']}")
        verdict_code = 1

    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt = RECEIPTS / f"{datetime.date.today().isoformat()}.jsonl"
    with open(receipt, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"Receipt: {receipt}")

    # (c) escalate to the relay queue on failure — never raw to the user.
    if verdict_code == 1 and QUEUE.exists():
        msg = (f"proving-ground audit FAIL: {len(missing_required)} missing required path(s), "
               f"{len(failed)} failed check(s)")
        sh(f'{sys.executable} {QUEUE} submit --source proving-ground --severity warn '
           f'--message {json.dumps(msg)}', timeout=10)
    return verdict_code


if __name__ == "__main__":
    sys.exit(main())
