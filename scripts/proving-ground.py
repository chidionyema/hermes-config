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
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
CODE = Path(os.environ.get("HERMES_CODE_DIR", HOME / "Documents" / "code"))
HERMES = Path(os.environ.get("HERMES_HOME", HOME / ".hermes"))
RECEIPTS = HOME / ".lux" / "proving-ground"
QUEUE = HERMES / "scripts" / "hermes_queue.py"

PASS, FAIL, MISS = "✅", "❌", "🚫"

# (project, check, cmd, relpath-under-CODE or None for network, required)
CHECKS = [
    ("popdd-ts", "tests", "npm test 2>&1 | tail -3", "popdd-ts", True),
    ("popdd-ts", "build", "npm run build 2>&1 | tail -5", "popdd-ts", True),
    ("lux-popdd", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", "popdd-py", True),
    ("lux-spec", "tests", "uv run pytest -q --tb=short 2>&1 | tail -3", "lux-spec-py", True),
    ("lux-spec-cli", "tests", "python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3", "lux-spec-cli", True),
    ("signalengine", "imports",
     "uv run python3 -c \"from popdd import PopddAgent; from luxspec import SpecVerifier; print('OK')\"",
     "signalengine", True),
    ("prospector", "imports",
     "uv run python3 -c \"from popdd import PopddAgent; from luxspec import SpecVerifier; print('OK')\"",
     "prospector", True),
    ("lux-engine", "popdd-dependency", "npm ls popdd 2>&1 | tail -3", "lux", True),
    # network/published-state checks have no local path and are not required (no false-fail offline)
    ("npm", "popdd-ts published", "npm info popdd version 2>&1", None, False),
]


def sh(cmd, cwd=None, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", "NOT_FOUND"


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
        passed = code == 0
        summary = (out or err).strip().split("\n")[-1][:120] if (out or err) else f"exit {code}"
        results.append({"project": project, "check": name,
                        "state": "pass" if passed else "fail", "required": required,
                        "path": str(path) if path else None, "exit_code": code,
                        "summary": summary})
        print(f"  {PASS if passed else FAIL} {project}/{name}: {summary}")

    missing_required = [r for r in results if r["state"] == "missing" and r["required"]]
    failed = [r for r in results if r["state"] == "fail" and r["required"]]
    ok = sum(1 for r in results if r["state"] == "pass")

    print("─" * 60)
    if not missing_required and not failed:
        print(f"INTEGRITY VERDICT: PASS — {ok}/{len(results)} checks passed")
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
