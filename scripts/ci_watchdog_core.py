#!/usr/bin/env python3
"""The CI watchdog's logic, separated from its I/O so it can be tested.

Why this file exists. The watchdog it replaces did three things wrong, all of
them measured on 2026-08-19:

1. Its repo list was a hardcoded dict of four. Two of those four had no
   directory on this machine, and two were projects the founder archived the
   same day. The curated list lives in ``~/.hermes/projects.json``; reading it
   here is what makes archiving a project actually reach the watchdog.

2. It asked ``gh run list --limit 1``, which returns the newest run of ANY
   workflow on ANY branch. On prospector that is the auto-merge workflow, whose
   conclusion is ``skipped``, so the watchdog reported "Prospector CI skipped"
   while main was red and 27 pull requests were open. The question "is main
   green" is answered by the check runs on main's head commit, and nothing else.

3. When it found a failure it printed a URL. A URL is a pointer to the evidence,
   not the evidence. This version opens the failing job and prints the assertion,
   because the founder should not have to click to learn which test broke.

And one thing it did dangerously: with every repo missing it printed
``CI watchdog: 4 repos healthy``. A probe that can see nothing must say so
loudly, never green. ``build_report`` raises rather than return a healthy
verdict it cannot support.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# How many red pull requests get their log opened. Downloading a job log is the
# expensive part of this probe, so it is bounded — and the bound is REPORTED,
# because a silent cap reads as "that was all of them".
MAX_LOG_READS = 5

# Telegram rejects a message over 4096 characters outright, so the report is
# trimmed with a line that says how much was dropped.
MAX_MESSAGE_CHARS = 3500

_ASSERT_PATTERNS = (
    re.compile(r"^E\s+(assert .*)$", re.M),
    re.compile(r"^E\s+(\w*(?:Error|Exception).*)$", re.M),
    re.compile(r"^(FAILED \S+.*)$", re.M),
    re.compile(r"^\s*(error(?:\[\w+\])?:\s+.+)$", re.M | re.I),
)


class ProbeBlind(RuntimeError):
    """The probe cannot see the thing it exists to watch."""


def active_repos(projects_file: Path) -> dict[str, str]:
    """The curated project roster: ``{key: absolute repo path}``.

    Only rows the coordinator would treat as active are returned, and only ones
    that are really a git checkout — an active row pointing at nothing is the
    defect ``tests/test_projects.py::test_an_active_project_points_at_a_real_checkout``
    already refuses, so it must not silently become a watchdog target here.
    """
    data = json.loads(Path(projects_file).read_text())
    out: dict[str, str] = {}
    for row in data.get("projects", []):
        active = row.get("active")
        if active is None:
            active = row.get("status", "active") == "active"
        if not active:
            continue
        repo = os.path.expanduser(row.get("repo") or "")
        if repo and os.path.isdir(os.path.join(repo, ".git")):
            out[row["key"]] = repo
    return out


def classify_pr(pr: dict) -> str:
    """RUNNING / FAIL / PASS / NONE for one pull request's checks."""
    checks = [c for c in (pr.get("statusCheckRollup") or [])
              if c.get("__typename") == "CheckRun" or "conclusion" in c]
    if not checks:
        return "NONE"
    if any(c.get("status") not in (None, "COMPLETED") for c in checks):
        return "RUNNING"
    if any(c.get("conclusion") == "FAILURE" for c in checks):
        return "FAIL"
    return "PASS"


def stalled_checks(pr: dict) -> list[str]:
    """Checks that were cancelled or timed out rather than failing a test.

    This exists because of the estate's most common red pull request. Measured
    on prospector #450 on 2026-08-19: `python` is CANCELLED, every other job is
    green, and the aggregator `ci-ok` is the only check whose conclusion is
    FAILURE. A watchdog that looks only at FAILURE therefore reports the
    aggregator's own headline — "Every job either passed or was not needed" —
    which names nothing. The cancellation is the story: `.github/workflows/ci.yml`
    sets cancel-in-progress for every ref that is not main, so one agent's push
    kills another agent's in-flight run.
    """
    out = []
    for c in pr.get("statusCheckRollup") or []:
        if c.get("conclusion") in ("CANCELLED", "TIMED_OUT", "STALE"):
            name = c.get("name") or c.get("context") or "?"
            out.append(f"{name} {str(c['conclusion']).lower()}")
    return out


def first_failure_line(log_text: str) -> str | None:
    """The first line of a job log that names what broke.

    Ordered by how specific the pattern is: a pytest ``E assert`` beats a bare
    ``error:`` from a build tool, because the first one names the test's own
    claim and the second names whatever printed last.
    """
    for pattern in _ASSERT_PATTERNS:
        m = pattern.search(log_text)
        if m:
            return " ".join(m.group(1).split())[:180]
    return None


def describe_failure(job: dict, annotations: list[dict], log_text: str) -> str:
    """One line saying why a check failed — content, never a URL.

    The `no failing step` branch is not a fallback, it is the common case here.
    Measured 2026-08-19 by a peer session across nine prospector pull requests:
    the job fails with every step green and the annotation reads "The self-hosted
    runner lost communication with the server". Reporting that as a test failure
    sent one session hunting a bug that did not exist, so it gets its own line.
    """
    failed_steps = [s.get("name") for s in (job.get("steps") or [])
                    if s.get("conclusion") == "failure"]
    if not failed_steps:
        note = ""
        for a in annotations or []:
            msg = (a.get("message") or "").strip()
            if msg:
                note = " ".join(msg.split())[:180]
                break
        return f"infrastructure, not tests — no step failed. {note}".strip()
    line = first_failure_line(log_text or "")
    if line:
        return f"step `{failed_steps[0]}` — {line}"
    return f"step `{failed_steps[0]}` — no assertion found in the log"


def build_report(repos: dict[str, str], gather) -> tuple[list[str], list[str]]:
    """Render the report. *gather* returns one repo's measured state.

    Raises ProbeBlind when there is nothing to grade, so an empty roster or a
    missing ``gh`` can never be printed as good news.
    """
    if not repos:
        raise ProbeBlind(
            "no active project names a git checkout — projects.json is empty, "
            "archived, or its repo paths are wrong"
        )

    lines: list[str] = []
    deltas: list[str] = []
    for key, path in sorted(repos.items()):
        state = gather(key, path)
        if state.get("error"):
            lines.append(f"\U0001f7e1 *{key}* — cannot read: {state['error']}")
            deltas.append(f"{key}=unreadable")
            continue

        main_red = state.get("main_failures") or []
        prs = state.get("prs") or []
        counts = {"FAIL": 0, "RUNNING": 0, "PASS": 0, "NONE": 0}
        for pr in prs:
            counts[pr["state"]] = counts.get(pr["state"], 0) + 1

        deltas.append(
            f"{key}=main:{'red' if main_red else 'green'}"
            f":f{counts['FAIL']}:r{counts['RUNNING']}:p{counts['PASS']}"
        )

        if main_red:
            lines.append(f"\U0001f534 *{key}* · main is RED")
            for name, why in main_red[:3]:
                lines.append(f"   `{name}` — {why}")
        if counts["PASS"]:
            lines.append(
                f"✅ *{key}* · {counts['PASS']} PR(s) green and ready to merge: "
                + ", ".join(f"#{p['number']}" for p in prs if p["state"] == "PASS")
            )
        if counts["RUNNING"]:
            lines.append(
                f"⏳ *{key}* · {counts['RUNNING']} PR(s) still running — "
                "do not push to these, it cancels the run"
            )
        if counts["FAIL"]:
            lines.append(f"\U0001f534 *{key}* · {counts['FAIL']} PR(s) red:")
            explained = [p for p in prs if p["state"] == "FAIL" and p.get("why")]
            for p in explained:
                lines.append(f"   #{p['number']} {p['title'][:50]} — {p['why']}")
            unexplained = counts["FAIL"] - len(explained)
            if unexplained > 0:
                lines.append(
                    f"   …and {unexplained} more not opened "
                    f"(cap is {MAX_LOG_READS} log reads per repo)"
                )
        if not main_red and not prs:
            lines.append(f"✅ *{key}* · main green, no open PRs")

    return lines, deltas


def trim(lines: list[str], limit: int = MAX_MESSAGE_CHARS) -> str:
    """Join *lines*, saying out loud how many were dropped to fit."""
    body = "\n".join(lines)
    if len(body) <= limit:
        return body
    kept: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > limit - 60:
            kept.append(f"\n…{len(lines) - i} more line(s) trimmed to fit Telegram.")
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)
