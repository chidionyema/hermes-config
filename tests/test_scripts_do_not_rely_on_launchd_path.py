"""A launchd job does not get /usr/sbin on PATH. Calling those tools by bare name is a no-op.

The incident: idle-learning-run.sh gated its work on host load with a bare `sysctl`. Under
launchd that call printed nothing and failed, and both fallbacks pointed the wrong way — NCPU
fell back to 1, so MAX_LOAD became 2, and the load reading became empty, which the shell
compared as 0. `[ 0 -gt 2 ]` is false, so the gate deferred at no load, ever. The only trace
was `sysctl: command not found` in a DIFFERENT job's stderr, 410 times.

The class is bigger than one tool: a bare name plus a swallowed failure turns a guard into a
no-op that reports nothing. otto-daemon.sh had the same shape on `lsof`, where a missing lsof
reads as "the port is free" and a second server starts.

Record: docs/incidents/INC-2026-08-19-launchd-path-inert-gate.json in the prospector repo.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = sorted((Path(__file__).resolve().parent.parent / "scripts").glob("*.sh"))

# Tools that live in /usr/sbin on macOS and are therefore absent from a launchd job's PATH.
SBIN_ONLY = ("sysctl", "lsof", "ioreg", "networksetup", "system_profiler", "pmset", "diskutil")

# A bare invocation: the name not preceded by a path separator, a word character, a dot or a
# dash, so `/usr/sbin/sysctl`, `HERMES_SYSCTL` and `--lsof` are all left alone.
BARE = re.compile(r"(?<![\w/.\-])(" + "|".join(SBIN_ONLY) + r")\b")


def _code(line: str) -> str:
    """The line with its trailing comment removed. Naive on a '#' inside a quoted string, which
    is the safe direction: it under-reports rather than failing a correct script."""
    return line.split("#", 1)[0]


def test_no_script_calls_a_usr_sbin_tool_by_bare_name():
    offenders: list[str] = []
    for path in SCRIPTS:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BARE.search(_code(line)):
                offenders.append(f"{path.name}:{lineno}: {line.strip()[:110]}")
    assert not offenders, (
        "these call a /usr/sbin tool by bare name, which resolves in your shell and NOT under "
        "launchd — write the absolute path:\n  " + "\n  ".join(offenders)
    )


def test_the_load_gate_reads_a_real_cpu_count():
    """The specific guard the incident disabled, checked end to end rather than by pattern."""
    src = (Path(__file__).resolve().parent.parent / "scripts" / "idle-learning-run.sh").read_text()
    assert "/usr/sbin/sysctl -n hw.ncpu" in src, "the CPU count is what sets MAX_LOAD"
    assert "/usr/sbin/sysctl -n vm.loadavg" in src, "the load reading is the gate's only input"
