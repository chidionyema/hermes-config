#!/usr/bin/env python3
"""Continuous-audit trigger — operationalizes the user's rule:
"every time I have to correct you, Claude has to audit you."

The rule must not depend on Otto *remembering* to self-audit (that is itself the
dropped-ball pattern). This scanner inspects a message for user-correction markers and,
when it finds one, escalates an AUDIT REQUEST into the relay queue automatically — so an
Otto heartbeat picks it up and forwards it to Claude WITHOUT the user having to ask.

  scan --text "<message>"     scan a literal message
  scan --file <path>          scan a file's contents
  (or pipe the message on stdin)

Exit codes: 2 if a correction is detected (so a hook/cron treats it as actionable),
0 if the message is clean. Detection is intentionally high-recall — a false audit is
cheap; a missed correction is the exact failure we are eliminating.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# Markers the user named, plus close variants. High-recall by design.
CORRECTION_MARKERS = [
    r"dropped?\s+(?:the\s+)?ball",
    r"another\b",
    r"should(?:'?ve| have)?\s+(?:be|been)",
    r"you\s+did\s*n['o]?t",
    r"did\s*n['o]?t\s+(?:verify|check|run|probe|test)",
    r"should\s*n['o]?t\s+have\s+to",
    r"you\s+should\s*n['o]?t",
    r"have\s+to\s+correct",
    r"correct\s+you",
    r"why\s+did\s*n['o]?t\s+you",
    r"that'?s\s+a\s+(?:new\s+)?(?:dropped?\s+)?ball",
    r"i\s+told\s+you",
    r"stop\s+(?:doing|self-certif)",
]
_RX = [re.compile(p, re.IGNORECASE) for p in CORRECTION_MARKERS]


def detect(text: str) -> list[str]:
    hits = []
    for rx in _RX:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0).strip())
    return hits


def _escalate(text: str, hits: list[str]) -> None:
    snippet = " ".join((text or "").split())[:160]
    msg = (f"user correction detected ({', '.join(sorted(set(h.lower() for h in hits)))}); "
           f"auto-audit required — forward to Claude: diagnose why the rule was not "
           f"self-enforcing, build the substrate prevention, probe it. ctx: {snippet!r}")
    try:
        subprocess.run(
            ["python3", str(SCRIPTS / "hermes_queue.py"), "submit",
             "--source", "correction-audit", "--severity", "crit", "--message", msg],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:  # noqa: BLE001 — never let escalation failure swallow the signal
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Continuous-audit correction scanner")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--text", default=None)
    s.add_argument("--file", default=None)
    args = p.parse_args()

    if args.text is not None:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(errors="replace")
    else:
        text = sys.stdin.read()

    hits = detect(text)
    if hits:
        _escalate(text, hits)
        print(f"CORRECTION DETECTED ({len(hits)} marker(s)): {sorted(set(h.lower() for h in hits))}")
        print("  -> audit request escalated to relay queue (source=correction-audit)")
        return 2
    print("no correction markers — clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
