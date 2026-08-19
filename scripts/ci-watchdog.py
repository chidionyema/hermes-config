#!/usr/bin/env python3
"""CI watchdog — what is actually blocking the estate's pull requests.

A no-agent cron script (`cron/jobs.json` -> ci-watchdog-daily -> ci-watchdog.sh).

Output policy:
    exit 0, stdout empty  -> nothing changed since the last run -> silence
    exit 0, stdout text   -> delivered to Telegram
    exit 1                -> the probe is blind; that is an alert, never silence

The logic lives in ``ci_watchdog_core.py`` so it can be tested without GitHub.
This file is the part that talks to ``gh``. See that module's docstring for the
four defects in the version this replaces.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_watchdog_core import (  # noqa: E402
    MAX_LOG_READS,
    ProbeBlind,
    active_repos,
    build_report,
    classify_pr,
    describe_failure,
    stalled_checks,
    trim,
)

HERMES = Path.home() / ".hermes"
PROJECTS = HERMES / "projects.json"
DIGEST_FILE = HERMES / "cache/ci-watchdog/ci-digest.txt"

# How many failing checks to open per pull request before giving up on
# finding a real assertion. Three covers an aggregator plus the job under it.
_CHECKS_PER_PR = 3


def _gh(args: list[str], cwd: str | None = None, timeout: int = 60) -> str | None:
    """Run gh and return stdout, or None if it failed. Never raises."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           cwd=cwd, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def _gh_json(args: list[str], cwd: str | None = None, timeout: int = 60):
    out = _gh(args, cwd=cwd, timeout=timeout)
    if out is None:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _main_check_failures(repo_dir: str) -> list[tuple[str, str]]:
    """Failing check runs on the default branch's head commit.

    Asked of the COMMIT, not of `gh run list`. The run list is ordered by time
    across every workflow, so on a repo with an auto-merge workflow the newest
    run is usually that one and its conclusion is `skipped` — which is how the
    previous watchdog reported a red main as "skipped".
    """
    head = _gh(["api", "repos/{owner}/{repo}/commits/main", "--jq", ".sha"], cwd=repo_dir)
    if not head:
        return []
    runs = _gh_json(
        ["api", f"repos/{{owner}}/{{repo}}/commits/{head.strip()}/check-runs",
         "--jq", "[.check_runs[] | {name, conclusion, id}]"],
        cwd=repo_dir,
    ) or []
    return [(c["name"], "failed") for c in runs if c.get("conclusion") == "failure"]


def _explain_one_check(repo_dir: str, check: dict) -> str | None:
    """Why one failing check run failed, or None if it cannot say."""
    job_id = str(check.get("detailsUrl", "")).rstrip("/").rsplit("/", 1)[-1]
    if not job_id.isdigit():
        return None
    job = _gh_json(["api", f"repos/{{owner}}/{{repo}}/actions/jobs/{job_id}"],
                   cwd=repo_dir) or {}
    annotations = _gh_json(
        ["api", f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations"],
        cwd=repo_dir) or []
    log_text = ""
    if any(s.get("conclusion") == "failure" for s in (job.get("steps") or [])):
        log_text = _gh(["api", f"repos/{{owner}}/{{repo}}/actions/jobs/{job_id}/logs"],
                       cwd=repo_dir, timeout=90) or ""
    return describe_failure(job, annotations, log_text)


def _explain_pr(repo_dir: str, pr: dict) -> str | None:
    """Open the failing checks for one PR and say what broke, in words.

    It tries more than one check on purpose. A repo with an aggregator job — on
    prospector it is `ci-ok`, "Every job either passed or was not needed" — will
    list that aggregator as a failing check alongside the job that actually
    broke. The aggregator's log contains no assertion, so stopping at the first
    failing check reports a summary of the failure instead of its cause.
    """
    failing = [c for c in (pr.get("statusCheckRollup") or [])
               if c.get("conclusion") == "FAILURE"]
    if not failing:
        return None
    fallback = None
    for check in failing[:_CHECKS_PER_PR]:
        why = _explain_one_check(repo_dir, check)
        if why and "no assertion found" not in why:
            return why
        fallback = fallback or why or f"check `{check.get('name', '?')}` failed"

    # Nothing in the logs named a cause. Before falling back to the aggregator's
    # own headline, say whether a job was cancelled — on this estate that is the
    # usual answer and it points at a push, not at a test.
    stalled = stalled_checks(pr)
    if stalled:
        return ("no test failed; " + ", ".join(stalled[:3])
                + " — a push cancelled this run")
    return fallback


def gather(key: str, repo_dir: str) -> dict:
    """Everything the report needs about one repo."""
    if not shutil.which("gh"):
        return {"error": "gh CLI is not installed"}

    prs = _gh_json(
        ["pr", "list", "--limit", "60", "--json",
         "number,title,isDraft,mergeable,statusCheckRollup"],
        cwd=repo_dir,
    )
    if prs is None:
        return {"error": "gh could not list pull requests (auth? network?)"}

    rows = []
    opened = 0
    for pr in prs:
        state = classify_pr(pr)
        why = None
        if state == "FAIL" and opened < MAX_LOG_READS:
            why = _explain_pr(repo_dir, pr)
            opened += 1
        rows.append({"number": pr["number"], "title": pr.get("title", ""),
                     "state": state, "why": why})
    return {"main_failures": _main_check_failures(repo_dir), "prs": rows}


def main() -> int:
    try:
        repos = active_repos(PROJECTS)
        lines, deltas = build_report(repos, gather)
    except ProbeBlind as e:
        print(f"\U0001f7e0 *CI watchdog is blind* — {e}")
        return 1
    except Exception as e:  # a crash must alert, not go quiet
        print(f"\U0001f7e0 *CI watchdog crashed* — {type(e).__name__}: {e}")
        return 1

    digest = hashlib.sha256("|".join(deltas).encode()).hexdigest()[:12]
    DIGEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    previous = DIGEST_FILE.read_text().strip() if DIGEST_FILE.exists() else ""
    DIGEST_FILE.write_text(digest)

    red = any(line.startswith(("\U0001f534", "\U0001f7e1")) for line in lines)
    if digest == previous and not red:
        return 0

    print("*CI watchdog — " + ("what is blocking the queue*" if red else "all clear*"))
    print()
    print(trim(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
