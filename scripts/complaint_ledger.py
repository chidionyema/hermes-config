#!/usr/bin/env python3
"""Persist the founder-complaint scan so it stops evaporating between sessions.

WHAT THIS IS NOT
----------------
It is not a scanner. `~/.claude/scripts/reflect.py` already reads every transcript in every
project, strips the contaminants that `role: user` sweeps up (tool results, task
notifications, subagent turns, compaction replays), de-duplicates, and themes what is left.
I started writing a second scanner on 2026-08-17 and threw it away when I found that one —
which is itself the defect the founder named that day: "you lost track of all the process
improvements we are trying to solve".

WHAT IT ADDS
------------
reflect.py PRINTS. Nothing survives the terminal it printed to, so a complaint is live only
while someone is looking at it. This writes the same result to a file, which gives it two
things it did not have: a durable register, and an observable the capability audit can grade.
When the ledger goes stale, the estate says so on its own.

    python3 complaint_ledger.py             # scan every project, write the ledger, summarise
    python3 complaint_ledger.py --print     # re-read the ledger, no scan
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
LEDGER = HERMES_HOME / "state" / "complaint_ledger.json"
REFLECT = Path(os.path.expanduser("~/.claude/scripts/reflect.py"))
PROJECTS = Path(os.path.expanduser("~/.claude/projects"))


def _load_reflect():
    """Import reflect.py by path. It is a script, not a package, and has no __init__."""
    spec = importlib.util.spec_from_file_location("reflect", REFLECT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {REFLECT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scan_all() -> list[dict]:
    """Every project, not just this one. A complaint made in the Hermes checkout is the
    same complaint; scoping to one slug is how a recurring theme reads as a one-off."""
    reflect = _load_reflect()
    out: list[dict] = []
    for slug_dir in sorted(PROJECTS.iterdir()):
        if not slug_dir.is_dir():
            continue
        try:
            msgs = reflect.scan_user_messages(slug_dir.name)
        except Exception as exc:                      # one bad project never kills the scan
            print(f"  skipped {slug_dir.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        for m in msgs:
            if m.get("complaint"):
                m["project"] = slug_dir.name
                m["themes"] = reflect._themes_of(m["text"])
                out.append(m)
    # De-duplicate across projects too: the same complaint reaches two checkouts often.
    seen: set[str] = set()
    unique: list[dict] = []
    for m in out:
        key = " ".join((m.get("own") or m["text"]).lower().split())[:300]
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    unique.sort(key=lambda m: m.get("month") or "", reverse=True)
    return unique


def summarise(rows: list[dict]) -> None:
    themes: Counter = Counter()
    theme_months: dict[str, set] = {}
    for m in rows:
        for t in m.get("themes") or ["unthemed"]:
            themes[t] += 1
            theme_months.setdefault(t, set()).add(m.get("month") or "?")
    print(f"COMPLAINTS: {len(rows)} unique across every project\n")
    print(f"  {'count':>5}  {'months':>6}  theme")
    for theme, n in themes.most_common():
        print(f"  {n:>5}  {len(theme_months[theme]):>6}  {theme}")
    print("\nA theme spanning many months is a root cause that was never fixed.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="print_only", action="store_true")
    args = ap.parse_args()

    if args.print_only:
        if not LEDGER.exists():
            print("No ledger yet. Run without --print.")
            return 1
        data = json.loads(LEDGER.read_text())
        age_h = (time.time() - data.get("generated_at", 0)) / 3600
        print(f"(ledger written {age_h:.1f}h ago)\n")
        summarise(data.get("complaints", []))
        return 0

    started = time.time()
    rows = scan_all()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps({
        "generated_at": time.time(),
        "source": str(REFLECT),
        "scan_seconds": round(time.time() - started, 1),
        "complaints": rows,
    }, indent=1))
    summarise(rows)
    print(f"\nledger: {LEDGER}  ({time.time() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
