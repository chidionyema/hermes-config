"""The CI watchdog must name a cause, and must never look green while blind.

The version replaced on 2026-08-19 failed both. It carried a hardcoded list of
four repos, two of which had no directory on this machine, and with every repo
missing it printed `CI watchdog: 4 repos healthy`. It also asked
`gh run list --limit 1`, which on prospector returns the auto-merge workflow, so
it reported `CI skipped` while main was red and 27 pull requests were open.

Each test below is one of those defects.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path.home() / ".hermes" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ci_watchdog_core import (  # noqa: E402
    ProbeBlind,
    active_repos,
    build_report,
    classify_pr,
    describe_failure,
    first_failure_line,
    stalled_checks,
    trim,
)


# ── The roster comes from projects.json, not from a constant ────────────────

def _projects_file(tmp_path, rows):
    f = tmp_path / "projects.json"
    f.write_text(json.dumps({"projects": rows}))
    return f


def _git_checkout(tmp_path, name):
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    return str(d)


def test_only_active_rows_with_a_real_checkout_are_watched(tmp_path):
    live = _git_checkout(tmp_path, "live")
    rows = [
        {"key": "live", "status": "active", "repo": live},
        {"key": "archived", "status": "archived", "repo": live},
        {"key": "phantom", "status": "active", "repo": str(tmp_path / "nope")},
        {"key": "norepo", "status": "active"},
    ]
    assert active_repos(_projects_file(tmp_path, rows)) == {"live": live}


def test_an_explicit_active_key_wins_over_status(tmp_path):
    """`scripts/coordinator.py::_project_is_active` gives `active` precedence."""
    live = _git_checkout(tmp_path, "live")
    rows = [{"key": "live", "status": "archived", "active": True, "repo": live}]
    assert active_repos(_projects_file(tmp_path, rows)) == {"live": live}


# ── A blind probe alerts; it never reports health ──────────────────────────

def test_an_empty_roster_is_an_alert_not_a_green_line():
    """The exact defect: `CI watchdog: 4 repos healthy` with four repos missing."""
    with pytest.raises(ProbeBlind):
        build_report({}, lambda k, p: {})


def test_a_repo_it_cannot_read_is_reported_not_skipped():
    lines, deltas = build_report({"p": "/tmp/p"}, lambda k, p: {"error": "gh not installed"})
    assert any("cannot read" in ln for ln in lines)
    assert "p=unreadable" in deltas
    assert not any("healthy" in ln or "all clear" in ln for ln in lines)


# ── The cause, in words, not a URL ─────────────────────────────────────────

def test_a_job_with_no_failing_step_is_called_infrastructure():
    """Measured across nine prospector PRs: every step green, the job failed.

    Reporting that as a test failure sent one session hunting a bug that was
    never there.
    """
    job = {"steps": [{"name": "checkout", "conclusion": "success"}]}
    annotations = [{"message": "The self-hosted runner lost communication with the server."}]
    out = describe_failure(job, annotations, "")
    assert "infrastructure" in out
    assert "self-hosted runner lost communication" in out


def test_a_failing_step_reports_the_assertion_from_the_log():
    job = {"steps": [{"name": "pytest", "conclusion": "failure"}]}
    log = "some noise\nE       assert 11 >= 20\nmore noise\n"
    out = describe_failure(job, [], log)
    assert "pytest" in out
    assert "assert 11 >= 20" in out


def test_an_exception_line_is_found_when_there_is_no_assert():
    assert "ValueError: bad tier" in (
        first_failure_line("junk\nE   ValueError: bad tier\n") or "")


def test_no_assertion_in_the_log_says_so_rather_than_inventing_one():
    job = {"steps": [{"name": "build", "conclusion": "failure"}]}
    assert "no assertion found" in describe_failure(job, [], "all quiet here")


# ── A cancelled job is the estate's most common red PR ─────────────────────

def test_a_cancelled_check_is_named():
    """prospector #450: python CANCELLED, everything else green, ci-ok FAILURE.

    Only `ci-ok` has conclusion FAILURE, so a watchdog reading FAILURE alone
    reports the aggregator's headline and names nothing.
    """
    pr = {"statusCheckRollup": [
        {"name": "python", "status": "COMPLETED", "conclusion": "CANCELLED"},
        {"name": "engine", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "ci-ok", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]}
    assert stalled_checks(pr) == ["python cancelled"]


# ── Never advise action on a run that is still going ───────────────────────

def test_a_running_check_outranks_a_failed_one():
    """Merging or pushing against a live run cancels it. RUNNING must win."""
    pr = {"statusCheckRollup": [
        {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None},
        {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]}
    assert classify_pr(pr) == "RUNNING"


def test_a_pr_with_no_checks_is_not_called_green():
    assert classify_pr({"statusCheckRollup": []}) == "NONE"


def test_the_running_line_warns_against_pushing():
    lines, _ = build_report({"p": "/tmp/p"}, lambda k, path: {
        "main_failures": [],
        "prs": [{"number": 1, "title": "t", "state": "RUNNING", "why": None}],
    })
    assert any("cancels the run" in ln for ln in lines)


# ── No silent truncation ───────────────────────────────────────────────────

def test_trimming_says_how_much_it_dropped():
    lines = [f"line {i} " + "x" * 80 for i in range(200)]
    out = trim(lines, limit=500)
    assert len(out) <= 500
    assert "more line(s) trimmed" in out


def test_the_log_read_cap_is_reported_not_hidden():
    """A cap nobody is told about reads as 'that was all of them'."""
    prs = [{"number": n, "title": "t", "state": "FAIL",
            "why": "boom" if n < 3 else None} for n in range(8)]
    lines, _ = build_report({"p": "/tmp/p"},
                            lambda k, path: {"main_failures": [], "prs": prs})
    assert any("more not opened" in ln for ln in lines)


# ── main is graded on main's head commit, not on the newest run ────────────

def test_a_red_main_is_reported_with_the_check_names():
    lines, deltas = build_report({"p": "/tmp/p"}, lambda k, path: {
        "main_failures": [("smoke", "failed"), ("lighthouse", "failed")],
        "prs": [],
    })
    assert any("main is RED" in ln for ln in lines)
    assert any("smoke" in ln for ln in lines)
    assert "p=main:red:f0:r0:p0" in deltas


# ── The script itself must still parse and expose its entry point ──────────

def test_the_watchdog_script_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile",
                        str(SCRIPTS / "ci-watchdog.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_wrapper_allows_enough_time_to_open_a_log():
    """The wrapper capped the probe at 30s; opening job logs takes longer.

    A cap below the work it wraps turns every run into `CI watchdog crashed`.
    """
    body = (SCRIPTS / "ci-watchdog.sh").read_text()
    import re
    m = re.search(r"timeout (\d+) python3", body)
    assert m, "the wrapper no longer bounds the probe at all"
    assert int(m.group(1)) >= 120, f"probe timeout is {m.group(1)}s, too short to open a log"
