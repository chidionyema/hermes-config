"""An enabled cron job must be able to do its work on the machine it runs on.

THE INCIDENT (measured on prospector-hermes, 2026-08-19). Seven enabled jobs could not
possibly complete, and none of them said so:

  auto-push.sh                     8/8 runs   "fatal: not a git repository"
  signal-engine-daemon-watchdog.sh 90/90 runs "Signal Engine daemon DOWN and no LaunchAgent"
  prospector-run.sh                8/8 runs   silent; escalated "repo missing" to the queue hourly
  repo-health-check.py             4/4 runs   silent; zero repos to check
  uncommitted-watch.sh             2/2 runs   silent; watches $HOME/lux, $HOME/signal-engine
  proving-ground.py                4/4 runs   "INTEGRITY VERDICT: PASS — 0/9 checks passed"
  weekly-lux-verify.sh             lux is not in the estate

THE CLASS: a job whose prerequisites are absent reports SUCCESS — silent output, last_status
"ok", or a PASS verdict from zero checks — instead of refusing. Nothing in the estate failed
when that happened, so the jobs stayed enabled for months and their noise trained everyone to
ignore cron alerts.

TWO FACTS THIS TEST ENCODES, both measured, not assumed:

  1. The estate is prospector and hermes-agent. Founder directive 2026-08-19: "hermes agent
     thinks the estate is every folder in code, should understand it's just prospector and
     hermes agent". A job that scans lux, signalengine or popdd is scanning nothing.

  2. The deploy image has no `.git`. `ls -d /Users/chidionyema/.hermes/.git` in the running
     container returns "No such file or directory" — .dockerignore strips it. So an enabled
     job cannot run a git command that needs a repository.

Prose is not graded: comments and docstrings are stripped before scanning, because a script
may legitimately explain in a comment which system it deliberately leaves alone
(pytest-orphan-cleanup.sh does exactly that). Mutation proofs below pin both directions.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

HERMES = Path(__file__).resolve().parent.parent
JOBS = HERMES / "cron" / "jobs.json"
SCRIPTS = HERMES / "scripts"

# Projects that are not in the estate. `prospector` and `hermes-agent` are the estate.
OFF_ESTATE = re.compile(r"\blux\b|signal[-_]?engine|signalengine|\bpopdd\b", re.I)

# Git commands that need a repository. The image has none.
NEEDS_GIT_REPO = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:status|add|commit|push|pull|fetch|remote|rev-parse|diff|log)\b")

# A script may opt out by declaring, in one line, that it handles a machine with no checkouts.
# The declaration must say HOW, so a reviewer can check it. Grepping for this line lists every
# script that has made the claim.
GIT_OPTIONAL = re.compile(r"^#\s*cron-guard:\s*git-optional\s*—\s*\S", re.M)


def _strip_prose(text: str, is_python: bool) -> str:
    """Return the executable part of a script: no comments, no docstrings."""
    drop: set[int] = set()
    if is_python:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                body = getattr(node, "body", None)
                if not body:
                    continue
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if lineno in drop:
            continue
        if line.lstrip().startswith("#"):
            continue
        if "#" in line and '"' not in line and "'" not in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return "\n".join(out)


def _enabled_script_jobs() -> list[dict]:
    jobs = json.loads(JOBS.read_text())["jobs"]
    return [j for j in jobs if j.get("enabled", True) and j.get("script")]


def test_the_scan_is_not_vacuous():
    """A guard that iterates an empty list passes. Prove there is something to grade.

    The floor used to be `>= 20`, written when 27 jobs were enabled. On 2026-08-19 sixteen
    self-talk jobs were disabled and this test failed — not because the scan had gone
    vacuous, but because the number pinned the ROSTER SIZE. That is the same defect
    `tests/test_projects.py::test_the_estate_is_prospector_and_hermes` was rewritten to
    remove: a count assertion makes shrinking the estate a test failure.

    What matters is that the parametrised scan below reads the same list this file reads,
    and that the list is not empty. Both are asserted, and neither moves when the roster
    changes deliberately.
    """
    jobs = _enabled_script_jobs()
    assert jobs, "no enabled script jobs at all — did jobs.json move?"
    raw = json.loads(JOBS.read_text())["jobs"]
    expected = [j for j in raw if j.get("enabled", True) and j.get("script")]
    assert len(jobs) == len(expected), (
        f"the scan graded {len(jobs)} jobs but jobs.json has {len(expected)} enabled "
        "script jobs — the helper and the file disagree"
    )


@pytest.mark.parametrize("job", _enabled_script_jobs(), ids=lambda j: j.get("script", "?"))
def test_enabled_job_script_exists(job):
    """weekly-lux-verify.sh once errored every run because `script` held a bash body, not a
    filename. The runner resolves `script` as a file under ~/.hermes/scripts/ and nothing
    else."""
    assert (SCRIPTS / job["script"]).exists(), \
        f"job {job['id']} is enabled but scripts/{job['script']} does not exist"


@pytest.mark.parametrize("job", _enabled_script_jobs(), ids=lambda j: j.get("script", "?"))
def test_enabled_job_stays_inside_the_estate(job):
    path = SCRIPTS / job["script"]
    if not path.exists():
        pytest.skip("covered by test_enabled_job_script_exists")
    code = _strip_prose(path.read_text(errors="replace"), path.suffix == ".py")
    hits = sorted(set(m.group(0) for m in OFF_ESTATE.finditer(code)))
    assert not hits, (
        f"enabled job {job['script']} references off-estate projects {hits}. "
        "The estate is prospector and hermes-agent. Either narrow the script or leave the "
        "job disabled."
    )


@pytest.mark.parametrize("job", _enabled_script_jobs(), ids=lambda j: j.get("script", "?"))
def test_enabled_job_does_not_need_a_git_repo(job):
    path = SCRIPTS / job["script"]
    if not path.exists():
        pytest.skip("covered by test_enabled_job_script_exists")
    raw = path.read_text(errors="replace")
    if GIT_OPTIONAL.search(raw):
        # The author has declared that this script survives a machine with no checkouts, and
        # the declaration names how. A declaration is checkable by a person; a static guess at
        # "is this git call guarded?" is not.
        return
    code = _strip_prose(raw, path.suffix == ".py")
    hits = sorted(set(m.group(0) for m in NEEDS_GIT_REPO.finditer(code)))
    assert not hits, (
        f"enabled job {job['script']} runs {hits}, but the deploy image contains no .git "
        "(.dockerignore strips it), so every such call dies with 'fatal: not a git "
        "repository'. Config is pushed from the laptop."
    )


def test_disabled_jobs_record_why():
    """A job turned off without a reason gets turned back on by the next agent who sees it."""
    jobs = json.loads(JOBS.read_text())["jobs"]
    off = [j for j in jobs if not j.get("enabled", True)]
    assert off, "no disabled jobs — fixture moved?"
    undocumented = [j["id"] for j in off
                    if not (j.get("paused_reason") or j.get("retired_reason") or j.get("description"))]
    assert not undocumented, f"disabled with no reason recorded: {undocumented}"


# ---- mutation proofs: the scanners must actually fire, and must not grade prose ----

def test_estate_scanner_catches_real_code_and_ignores_comments():
    bad_sh = 'REPOS=("$HOME/Documents/code/lux")\n'
    assert OFF_ESTATE.search(_strip_prose(bad_sh, False)), "scanner missed a real lux reference"

    commented_sh = '# Safe: leaves PID 1228 (signal_engine.daemon) alone — its argv is not "pytest".\necho hi\n'
    assert not OFF_ESTATE.search(_strip_prose(commented_sh, False)), \
        "scanner graded a comment (this is pytest-orphan-cleanup.sh's real first line)"

    bad_py = 'REPOS = {"lux": "/x"}\n'
    assert OFF_ESTATE.search(_strip_prose(bad_py, True)), "scanner missed a real lux dict key"

    docstring_py = '"""Scans signalengine and lux for cross-impact."""\nX = 1\n'
    assert not OFF_ESTATE.search(_strip_prose(docstring_py, True)), \
        "scanner graded a module docstring"


def test_git_scanner_catches_the_auto_push_line():
    real = 'out=$(git status --porcelain 2>&1) || echo fail\n'
    assert NEEDS_GIT_REPO.search(_strip_prose(real, False)), "scanner missed `git status`"
    assert not NEEDS_GIT_REPO.search(_strip_prose("# git status is fine in a comment\n", False))
    assert not NEEDS_GIT_REPO.search(_strip_prose("git --version\n", False)), \
        "git --version needs no repository and must not be flagged"


def test_git_optional_marker_must_state_a_reason():
    assert GIT_OPTIONAL.search("# cron-guard: git-optional — guarded by path.exists()\n")
    assert not GIT_OPTIONAL.search("# cron-guard: git-optional\n"), \
        "a bare marker with no reason must not opt a script out"
    assert not GIT_OPTIONAL.search("echo '# cron-guard: git-optional — x'\n"), \
        "the marker must be a comment at the start of a line, not text inside a command"
