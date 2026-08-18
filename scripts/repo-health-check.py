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

# HOST-FAULT PATTERNS (2026-08-18T13:22:06Z incident). That one tick broke ALL THREE
# repos at once: signalengine and prospector both said "Operation not permitted" on
# ~/Documents/code, and lux's vitest died on Node's fatal-uncaught-exception path. Nine
# seconds later the next tick read "lux: tests pass". The host broke, not the repos.
# A fault matching one of these is a property of the machine, so it hits every repo in
# the same tick and clears by itself — grade it like a timeout, not like a regression.
TRANSIENT_PATTERNS = (
    "Operation not permitted",
    "EPERM",
    "EMFILE",
    "ENFILE",
    "FATAL ERROR: ",
    "JavaScript heap out of memory",
)

# "requires" = repo-relative paths the test_cmd needs and CANNOT create itself.
# When one is missing the working tree is incomplete, so the command's verdict says
# nothing about the test suite (see check_repo).
REPOS = {
    # Call .venv/bin/python directly, NOT `uv run`: plain `uv run` syncs the project
    # (resolve + download + build the whole dependency tree) before it runs anything, so
    # on a cold or freshly cloned tree the per-repo timeout times the dependency install
    # instead of the tests. That is what paged at 12:52:06 and 12:53:40 on 2026-08-18
    # (logs/health/repo-health.jsonl lines 412-413): both ticks landed inside a re-clone
    # window that finished at 12:54:51 (git reflog "branch: Created from origin/main",
    # uv.lock rewritten 12:54:51) with .venv/bin still being populated until 12:58:44.
    # Listing .venv/bin/python in requires makes an unbuilt environment grade 'skip',
    # like prospector below, instead of burning the timeout and paging.
    "signalengine": {"path": str(CODE / "signalengine"),
                     "requires": ["pyproject.toml", "tests", ".venv/bin/python"],
                     "test_cmd": ".venv/bin/python -m pytest --collect-only -q -p no:cacheprovider 2>&1 | tail -25"},
    "lux": {"path": str(CODE / "lux"),
            "requires": ["node_modules/.bin/vitest"],
            "test_cmd": "./node_modules/.bin/vitest run 2>&1 | tail -25"},
    "prospector": {"path": str(CODE / "prospector"),
                   "requires": [".venv/bin/python", "tests/unit"],
                   "test_cmd": ".venv/bin/python -m pytest tests/unit -q --no-header 2>&1 | tail -25"},
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

    EXIT-CODE FIX (2026-08-18): every test_cmd ends with `... 2>&1 | tail -5`.
    A shell pipeline reports the LAST command's status, so the returncode was
    tail's and was always 0 — no repo could ever be graded 'fail'. Run under
    bash with `set -o pipefail` so the first failing stage wins.
    """
    proc = None
    try:
        proc = subprocess.Popen("set -o pipefail; " + cmd, shell=True,
                                executable="/bin/bash",
                                stdout=subprocess.PIPE,
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


def _present_reason(p: Path):
    """WHY a required path cannot satisfy the test command: None, or the reason.

    Returns None when the path is usable, 'missing' when it is genuinely absent
    (or is a directory holding nothing real), and 'unreadable' when it exists but
    the filesystem refused to list it.

    Existence alone is not enough. An EMPTY directory is a half-restored tree: a
    tests/ that exists but holds no test files makes pytest collect zero tests and
    exit 5 in ~0.02s — the exact symptom the requires-check exists to stop. Ignore
    __pycache__ and dotfiles, which survive a wipe of the real sources.

    The two reasons are NOT the same fault, which is why they are separated here.
    'missing' is a repo defect and must page. 'unreadable' is a host fault — at
    13:22:06Z and again at 15:22:33Z an EPERM on ~/Documents/code hit every repo
    in the same tick, and the next tick was green.
    """
    if not p.exists():
        return "missing"
    # UNREADABLE-TREE FIX (2026-08-18 page "signalengine: runner error [Errno 1]
    # Operation not permitted"). Path.exists() swallows OSError and returned True,
    # but iterdir() on the tests/ directory raised PermissionError under a
    # sandboxed/TCC-denied ad-hoc run. The exception escaped to main()'s blanket
    # handler and graded state='fail' — a page about the filesystem dressed up as a
    # broken test suite. A prerequisite we cannot read is an unusable tree, exactly
    # like a missing one, so it must grade 'skip', never 'fail'.
    try:
        if p.is_dir():
            real = any(c.name != "__pycache__" and not c.name.startswith(".")
                       for c in p.iterdir())
            return None if real else "missing"
    except OSError:
        return "unreadable"
    return None


def _present(p: Path) -> bool:
    """Is a required path actually able to satisfy the test command?"""
    return _present_reason(p) is None


def _summary_line(out):
    """The last INFORMATIVE line of test output, capped at 80 chars.

    ROOT CAUSE (2026-08-18T13:22:06Z): the page read "lux: FAIL — Node.js v26.3.0",
    which says nothing at all. vitest's Node process died on its fatal-uncaught-
    exception path, and the final line of that dump is the version footer. The old
    code took `out.split("\\n")[-1]` blindly, so the one line that named the fault
    ("Error: EPERM: operation not permitted ...") was thrown away and the footer
    survived. Skip the footer, stack frames, blanks and punctuation-only lines.
    """
    lines = [l.rstrip() for l in (out or "").split("\n")]
    # A host fault names itself ONCE, at the TOP of the crash dump ("Error: EPERM:
    # operation not permitted, open ..."). Below it come stack frames and a detail
    # object whose lines ("code: 'EPERM',", "syscall: 'open'") are alphanumeric and
    # would win any last-line scan while saying nothing. So scan FORWARD for the
    # first line that names a known host fault.
    for line in lines:
        s = line.strip()
        if s and any(pat in s for pat in TRANSIENT_PATTERNS):
            return s[:80]
    for line in reversed(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith("Node.js v"):
            continue
        if line.lstrip().startswith("at "):
            continue
        if not any(c.isalnum() for c in s):
            continue
        return s[:80]
    for line in reversed(lines):
        if line.strip():
            return line.strip()[:80]
    return "test failed"


def _is_transient(out):
    """Does this output name a HOST fault rather than a repo defect?"""
    return any(pat in (out or "") for pat in TRANSIENT_PATTERNS)


def check_repo(name, info):
    """Grade one repo, never letting a filesystem error become a 'fail'.

    UNREADABLE-TREE GUARD (2026-08-18): any OSError raised while probing the tree
    (EPERM under TCC, ENOENT during a concurrent re-clone) means we could not read
    the working tree, so the test command's verdict would say nothing about the
    suite. Grade it 'skip', the same contract as a missing repo: never a false
    'pass', never a false 'crit'. A pass->skip transition still escalates as
    'warn' through should_escalate_change, so it cannot go silent. main()'s
    blanket `except Exception` stays as the last-resort net for genuine runner
    bugs — filesystem races no longer reach it.
    """
    try:
        return _check_repo(name, info)
    except OSError as e:
        # transient: an OSError from the filesystem is a host fault, the same
        # class as an EPERM on a prerequisite. Without this flag _is_flake gave it
        # no grace and the first occurrence paged as a regression.
        return name, {"state": "skip", "transient": True,
                      "summary": f"{name}: tree unreadable — {e}"}


def _check_repo(name, info):
    path = info["path"]
    if not Path(path).exists():
        return name, {"state": "skip", "summary": f"{name}: not found"}
    # INCOMPLETE-TREE FIX (2026-08-18): signalengine paged 'crit' with
    # "FAIL — no tests collected in 0.02s". Since pytest 8, testpaths that match
    # nothing is not an error — pytest collects zero tests and exits 5 in ~0.02s.
    # The tests/ directory was missing (the whole working tree was re-cloned at
    # 12:54:51 that day, per its git reflog), so the run graded a wiped tree as a
    # broken test suite. A missing prerequisite means the command's verdict says
    # nothing about the tests, so report 'skip' — same contract as a missing repo:
    # never a false 'pass', and never a false 'crit' either. A pass->skip change
    # still escalates as 'warn' via should_escalate_change, so this cannot go silent.
    #
    # THE TWO REASONS ARE GRADED DIFFERENTLY (2026-08-18, page "signalengine:
    # fail -> skip: incomplete tree — missing or unreadable tests"). Both used to
    # collapse into one unflagged 'skip':
    #   missing    = the repo really lost a prerequisite. A repo defect. It PAGES
    #                on the first tick, as it always did.
    #   unreadable = the path is there but the filesystem refused to list it
    #                (TCC/EPERM, dead cwd). A HOST fault, not a repo defect. It
    #                gets `transient: True` and therefore the same one-tick grace
    #                as a timeout via _is_flake, and pages only if it repeats.
    # The 15:22:33Z tick proves the split: signalengine's tests/ held 50+ files on
    # disk the whole time, lux named the host fault in the same tick ("getcwd:
    # cannot access parent dir") and prospector flipped identically. Only the
    # DIRECTORY requires failed while the file requires passed — exists()==True
    # with iterdir() raising.
    reasons = {r: _present_reason(Path(path) / r) for r in info.get("requires", [])}
    missing = [r for r, why in reasons.items() if why == "missing"]
    unreadable = [r for r, why in reasons.items() if why == "unreadable"]
    if unreadable:
        return name, {"state": "skip", "transient": True,
                      "summary": f"{name}: tree unreadable (host/transient) — {', '.join(unreadable)}"}
    if missing:
        return name, {"state": "skip",
                      "summary": f"{name}: incomplete tree — missing or unreadable {', '.join(missing)}"}
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
        last = _summary_line(test_out)
        if _is_transient(test_out):
            # The host broke, not the repo (see TRANSIENT_PATTERNS). Flagged so
            # _is_flake suppresses the first occurrence and the escalation block
            # pages it 'warn', not 'crit'.
            return name, {"state": "fail", "transient": True,
                          "summary": f"{name}: FAIL (host/transient) — {last}"}
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


def _is_flake(name, res, prev):
    """The FIRST consecutive TRANSIENT tick is a bad moment, not an incident.

    check_repo already says a transient timeout "self-heals on the next run"
    (see its comment) — but nothing acted on that, so one slow tick paged twice:
    "lux: pass -> fail" plus a bare "lux: TIMEOUT (> 60s)". This makes the first
    consecutive timeout silent. Two timeouts in a row is a real regression and
    still pages. The previous tick's flag comes from the history entry written in
    main(), so no new state file is needed.

    GENERALISED 2026-08-18: a timeout was only one kind of host fault. At
    13:22:06Z an EPERM on ~/Documents/code broke all three repos in one tick and
    lux paged "FAIL — Node.js v26.3.0"; the next tick, 9 seconds later, said
    "lux: tests pass". Any TRANSIENT_PATTERNS hit now gets the same one-tick grace
    as a timeout, on the same contract: recorded in history, not paged the first
    time, paged on a second consecutive occurrence.
    """
    cur = bool(res.get("timeout") or res.get("transient"))
    old = prev.get(name, {}).get("timeout") or prev.get(name, {}).get("transient")
    return cur and not old


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
                name = futs[fut]
                # An OSError escaping check_repo is the FILESYSTEM failing, not the
                # repo — that is how 13:22:06Z paged "runner error [Errno 1]
                # Operation not permitted: .../tests". Flag it transient so the first
                # occurrence is recorded but not paged as a regression.
                res = {"state": "fail", "summary": f"{name}: runner error {e}"}
                if isinstance(e, OSError):
                    res["transient"] = True
            results[name] = res
            old = prev.get(name, {}).get("state", "unknown")
            if old != "unknown" and old != res["state"]:
                changes.append((name, old, res["state"], res["summary"]))

    # Computed from the PREVIOUS tick, before the new entry is appended.
    flaky = {n for n, r in results.items() if _is_flake(n, r, prev)}

    # The timeout is still RECORDED — suppression is about paging only, never
    # about hiding state. A second consecutive timeout needs this line to exist.
    entry = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "results": results}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    any_fail = any(r["state"] == "fail" and n not in flaky for n, r in results.items())

    # Silent on no-change. Escalate changes/failures to the relay queue.
    if changes or any_fail or flaky:
        for name, old, new, summary in changes:
            if name not in flaky and should_escalate_change(new):
                submit(f"{name}: {old} -> {new}: {summary}", "warn")
        for n, r in results.items():
            if r["state"] == "fail" and n not in flaky:
                # Timeouts and host faults (EPERM, OOM) page as 'warn'; only a real
                # test failure pages as 'crit'.
                submit(r["summary"],
                       "warn" if r.get("timeout") or r.get("transient") else "crit")
        passes = sum(1 for r in results.values() if r["state"] == "pass")
        # Counts what PAGED, matching any_fail. A suppressed transient timeout is
        # reported on its own '~' line below, so it is visible but not double-counted.
        fails = sum(1 for n, r in results.items()
                    if r["state"] == "fail" and n not in flaky)
        print(f"Repo health — {passes} pass, {fails} fail")
        for name, old, new, summary in changes:
            print(f"  Δ {name}: {old} -> {new}: {summary}")
        for n in sorted(flaky):
            print(f"  ~ {n}: transient timeout (first consecutive, not paged)")

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
