"""Ban the laptop-isms that die silently on the container.

Hermes moved to a Linux container on 2026-08-17. Three separate failures had the same shape: a
command that is valid on macOS and invalid on GNU/Linux, in a script nobody re-ran by hand.

  /bin/zsh                 -> FileNotFoundError; every coordinator acceptance test returned False
                              with an exception string where a verdict should be, for two days.
  mktemp -t hermes-phase   -> "mktemp: too few X's in template"; idle-learning-run.sh failed
                              every 30 minutes, 16 of 16 runs.

Neither was reported as a portability problem. Both were reported as the script failing, which
is why they lasted. The class is: an interpreter or flag that exists on the machine the script
was WRITTEN on and not on the machine it RUNS on. This test is the machine that refuses it.
"""

import json
import re
from pathlib import Path

HERMES = Path.home() / ".hermes"
SCRIPTS = sorted(HERMES.glob("scripts/*.sh"))

# `mktemp -t NAME`: BSD takes NAME as a prefix, GNU demands >=3 trailing X's.
BSD_MKTEMP = re.compile(r"mktemp\s+(?:-[a-z]+\s+)*-t\s+(?!.*XXX)[\w.\-/$\"{}]+")


def test_scripts_exist_to_check():
    """A glob that matched nothing would pass every assertion below."""
    assert len(SCRIPTS) > 50, len(SCRIPTS)


def test_no_bsd_only_mktemp_template():
    bad = []
    for p in SCRIPTS:
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if BSD_MKTEMP.search(line):
                bad.append(f"{p.name}:{n}: {line.strip()}")
    assert not bad, "mktemp -t without XXX fails on GNU coreutils:\n" + "\n".join(bad)


def test_the_pattern_would_have_caught_the_real_defect():
    """Mutation proof: the exact line that failed 16 times must match."""
    assert BSD_MKTEMP.search('  out="$(mktemp -t hermes-phase)"')
    assert not BSD_MKTEMP.search('  out="$(mktemp "${TMPDIR:-/tmp}/hermes-phase.XXXXXX")"')
    assert not BSD_MKTEMP.search("TMP=$(mktemp -d)")


def _scheduled_scripts() -> set[str]:
    jobs = json.loads((HERMES / "cron" / "jobs.json").read_text())
    jobs = jobs.get("jobs", jobs)
    out = set()
    for job in jobs:
        if not job.get("enabled"):
            continue
        name = (job.get("script") or "").strip()
        if name.endswith(".sh"):
            out.add(name.rsplit("/", 1)[-1])
    return out


def test_no_scheduled_script_demands_zsh():
    """The container installs bash and never zsh. A cron job cannot supply its own interpreter."""
    bad = []
    for name in sorted(_scheduled_scripts()):
        p = HERMES / "scripts" / name
        if not p.exists():
            continue
        first = p.read_text(errors="replace").splitlines()[:1]
        if first and "zsh" in first[0]:
            bad.append(f"{name}: {first[0]}")
    assert not bad, "zsh is not installed on the container:\n" + "\n".join(bad)
