#!/usr/bin/env python3
"""CI watchdog — probe GitHub Actions status across all tracked repos.

A no-agent cron script. Output policy:
    exit 0, stdout empty  → all CI green AND unchanged → silence
    exit 0, stdout text   → new failures or status changes → delivered to user
    exit 1                → probe crashed → alert

Uses gh CLI for GitHub data. Falls back to local git if gh unavailable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DIGEST_DIR = Path.home() / ".hermes/cache/ci-watchdog"
DIGEST_DIR.mkdir(parents=True, exist_ok=True)

REPOS = {
    "Prospector": Path.home() / "Documents/code/prospector",
    "Signal Engine": Path.home() / "Documents/code/signalengine",
    "Haworks": Path.home() / "Documents/code/haworks-platform",
    "TIE": Path.home() / "Documents/code/introduction-exchange",
}

# Repos without CI workflows or not yet tracked
SKIP_IF_MISSING_WORKFLOW = {"TIE"}


def gh_run_status(repo_path: Path) -> dict | None:
    """Get the latest CI run status via gh CLI."""
    if not shutil.which("gh"):
        return None
    result = subprocess.run(
        ["gh", "run", "list", "--limit", "1", "--json",
         "name,status,conclusion,headBranch,createdAt,databaseId,url"],
        capture_output=True, text=True, cwd=repo_path, timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
        return runs[0] if runs else None
    except (json.JSONDecodeError, IndexError):
        return None


def local_git_status(repo_path: Path) -> dict:
    """Fallback: check local git state when gh CLI unavailable."""
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=repo_path, timeout=10,
    ).stdout.strip()

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=repo_path, timeout=10,
    ).stdout.strip()

    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=repo_path, timeout=10,
    ).stdout.strip()

    commit_ts = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "HEAD"],
        capture_output=True, text=True, cwd=repo_path, timeout=10,
    ).stdout.strip()

    return {
        "branch": branch,
        "sha": sha,
        "dirty_count": len(dirty.splitlines()) if dirty else 0,
        "last_commit_age_h": (
            (datetime.now().timestamp() - int(commit_ts)) / 3600
            if commit_ts else None
        ),
    }


def probe() -> tuple[list[str], list[str]]:
    issues: list[str] = []
    deltas: list[str] = []

    for name, repo_path in REPOS.items():
        if not repo_path.is_dir():
            deltas.append(f"{name}=MISSING")
            continue

        workflows = list(repo_path.glob(".github/workflows/*.yml"))
        if not workflows and name not in SKIP_IF_MISSING_WORKFLOW:
            issues.append(f"{name}: no CI workflows found")
            deltas.append(f"{name}=no-ci")
            continue

        run = gh_run_status(repo_path)
        local = local_git_status(repo_path)

        if run:
            status = run.get("conclusion", run.get("status", "unknown"))
            age_str = run.get("createdAt", "")
            try:
                created = datetime.fromisoformat(age_str.replace("Z", "+00:00"))
                age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600
            except (ValueError, TypeError):
                age_h = None

            branch = run.get("headBranch", "?")
            deltas.append(
                f"{name}={status}:{run.get('databaseId','?')}:"
                f"{branch}:{age_h:.0f}h" if age_h else f"?h"
            )

            if status == "failure":
                age_label = f"{age_h:.0f}h ago" if age_h is not None else "?"
                issues.append(
                    f"🔴 *{name}* · CI `failure` · {age_label}\n"
                    f"   `{branch}` · #{run.get('databaseId', '?')}\n"
                    f"   Run: {run.get('url', 'N/A')}\n"
                    f"   local: dirty({local['dirty_count']}) · "
                    f"sha `{local['sha']}`"
                )
            elif status in ("cancelled", "skipped"):
                issues.append(f"⚠️ *{name}* · CI `{status}`")
        else:
            # gh unavailable — fall back to local state only
            if local["dirty_count"] > 20:
                issues.append(
                    f"🟡 *{name}* · local dirty({local['dirty_count']}) · "
                    f"sha `{local['sha']}` · no gh CLI"
                )
            deltas.append(
                f"{name}=local:dirty({local['dirty_count']}):"
                f"{local['last_commit_age_h']:.0f}h" if local['last_commit_age_h'] else "?"
            )

    return issues, deltas


def main() -> int:
    issues, deltas = probe()
    digest = hashlib.sha256("|".join(deltas).encode()).hexdigest()[:12]

    digest_file = DIGEST_DIR / "ci-digest.txt"
    prev = digest_file.read_text().strip() if digest_file.exists() else ""

    if prev == digest and not issues:
        return 0  # Silent — all healthy AND unchanged

    digest_file.write_text(digest)

    if issues:
        print("🔴 *CI watchdog — regressions found*")
        for i in issues:
            print()
            print(i)
    else:
        print(f"✅ CI watchdog: {len(REPOS)} repos healthy ({digest})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
