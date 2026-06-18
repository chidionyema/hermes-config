#!/usr/bin/env python3
"""skill-hygiene — flag orphan skills (created, never wired). Item 6.

A skill is ORPHAN if, more than ORPHAN_DAYS (default 14) after its SKILL.md was
created, its name is referenced by NO file outside its own directory — i.e. nothing
wires it in. The search surface is the wiring surface (skills/scripts/policies/
memories/cron + root *.md/*.yaml), not logs/caches, so a passing mention in a log
never counts as "wired".

Exit 0 = no orphans. Exit 1 = orphan(s) flagged (and escalated to the relay queue).
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SKILLS = HERMES / "skills"
QUEUE = HERMES / "scripts" / "hermes_queue.py"
ORPHAN_DAYS = int(os.environ.get("HERMES_SKILL_ORPHAN_DAYS", "14"))
# files that count as "wiring" a skill in
SEARCH_DIRS = ["skills", "scripts", "policies", "memories", "cron"]


def _name(skill_md: Path) -> str:
    m = re.search(r"^name:\s*(.+)$", skill_md.read_text(errors="ignore"), re.M)
    return (m.group(1).strip() if m else skill_md.parent.name)


def _created(p: Path) -> float:
    st = p.stat()
    return getattr(st, "st_birthtime", st.st_mtime)  # macOS birthtime; fallback mtime


def _referenced_elsewhere(name: str, skill_dir: Path) -> bool:
    targets = [str(HERMES / d) for d in SEARCH_DIRS if (HERMES / d).exists()]
    r = subprocess.run(["grep", "-rlF", "--", name, *targets],
                       capture_output=True, text=True)
    for hit in r.stdout.splitlines():
        # a reference inside the skill's own directory does not count as wiring
        if not hit.startswith(str(skill_dir) + os.sep) and hit != str(skill_dir):
            return True
    return False


def main():
    if not SKILLS.exists():
        print("skill-hygiene: no skills dir — PASS")
        return 0
    now = time.time()
    orphans = []
    for md in SKILLS.rglob("SKILL.md"):
        name = _name(md)
        age_days = (now - _created(md)) / 86400
        if age_days <= ORPHAN_DAYS:
            continue
        if not _referenced_elsewhere(name, md.parent):
            orphans.append((name, int(age_days)))

    if not orphans:
        print(f"skill-hygiene: 0 orphan skills (> {ORPHAN_DAYS}d, unwired) — PASS")
        return 0

    detail = ", ".join(f"{n}({d}d)" for n, d in sorted(orphans))
    msg = f"{len(orphans)} orphan skill(s) created but never wired: {detail}"
    if QUEUE.exists():
        subprocess.run([sys.executable, str(QUEUE), "submit", "--source", "skill-hygiene",
                        "--severity", "warn", "--message", msg], capture_output=True)
    print(f"skill-hygiene: FAIL — {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
