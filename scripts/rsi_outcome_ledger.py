#!/usr/bin/env python3
"""Outcome attribution for the self-improvement loop — which lever can move the metric?

The RSI loop has exactly one actuator: it rewrites EXECUTE_PROMPT / VERIFY_PROMPT.
Before 2026-08-07 nothing checked whether that actuator had any authority over the
number it was trying to improve. It did not.

MEASURED on the live coordinator.db (2026-08-07, n=333 recorded fallbacks):

    ~46%  claude: timeout after 900s        -> lever: executor_timeout
    ~28%  claude: exit N (session/rate limit)-> lever: provider_capacity
     11%  no cause recorded at all           -> lever: observability

`EXECUTE_PROMPT` is a three-line string (coordinator.py:843-846). No rewrite of it
makes a 900-second subprocess return sooner or a rate limit clear. So the nightly
tuner was searching for a better prompt to fix failures a prompt cannot reach — it
could only land nothing, or a regression. That is the real answer to "the recursive
self-improvement isn't going well", and it is upstream of both the inverted ruler
(fixed cb20659) and the orphaned apply path.

This module answers ONE question with recorded evidence and zero LLM spend:

    prompt_authority() -> the fraction of failures where the executor actually RAN,
                          produced output, and still failed.

That is the only population a prompt rewrite can affect. When it is small, tuning
the prompt is not "self-improvement", it is motion. `rsi-orchestrator.py` gates on
it and names the dominant lever instead of burning a strategist call.

Read-only: opens the DB with mode=ro and never writes. The db path is a parameter,
never a module-level bind, so tests cannot touch production state (the defect class
in memory `tests-polluted-the-production-audit-log.md`).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.hermes/coordinator.db")

# Duplicated from coordinator.py by VALUE, asserted equal by test. Importing
# coordinator.py here would drag the whole daemon (Telegram, launchd, network) into
# a read-only report; asserting equality in the test gives the same Layer-0
# guarantee without the import. See test_rsi_outcome_ledger.py::test_markers_match_producer.
FALLBACK_MARKERS = (
    "[executor-narrative-fallback",
    "[executor-unavailable-fallback",
    "[agentic-exec-fallback",
)

# Statuses that mean the task did not land. `escalated` counts: the executor ran and
# the outcome still required a human.
FAILED_STATUSES = ("failed", "escalated")

# Lever taxonomy. Order matters — first match wins, most specific first. Each entry is
# (lever, compiled pattern). A lever names WHAT WOULD HAVE TO CHANGE to remove the
# failure, which is the only useful grouping for a loop that must choose an actuator.
_LEVER_PATTERNS = (
    ("executor_timeout",   re.compile(r"timeout after \d+s", re.I)),
    ("provider_capacity",  re.compile(r"session/rate limit|usage limit|rate limit|"
                                      r"credit balance|quota exceeded|overloaded", re.I)),
    ("provider_config",    re.compile(r"not installed|no [A-Z_]*API_KEY|exhausted all \d+ provider",
                                      re.I)),
)

# How much of a result to inspect for a cause. The marker and its parenthetical are
# always at the very front; scanning the whole narrative would match the executor
# quoting the word "timeout" in a report about something else.
_CAUSE_WINDOW = 400


def is_fallback(result: str | None) -> bool:
    """True when execution fell back to chat — no tool work was performed."""
    return any(m in (result or "") for m in FALLBACK_MARKERS)


def cause_text(result: str | None) -> str:
    """The recorded cause window at the head of a result, '' when there is none."""
    r = result or ""
    if not is_fallback(r):
        return ""
    return r[:_CAUSE_WINDOW]


def classify_lever(result: str | None, status: str | None = None) -> str:
    """Name the actuator that could have prevented this failure.

    - a fallback with a recognised cause  -> the lever for that cause
    - a fallback with NO recorded cause   -> 'observability' (we cannot route it yet)
    - not a fallback, but the task failed -> 'prompt_quality'

    That last branch is the whole point: the executor ran, did real tool work, produced
    output, and the outcome was still wrong. That — and only that — is the population a
    better EXECUTE_PROMPT can move.
    """
    if is_fallback(result):
        window = cause_text(result)
        for lever, pat in _LEVER_PATTERNS:
            if pat.search(window):
                return lever
        return "observability"
    if (status or "") in FAILED_STATUSES:
        return "prompt_quality"
    return "ok"


def load_outcomes(db_path: str = DEFAULT_DB, since: float | None = None) -> list[dict]:
    """Every closed task with a result, labelled with its lever. Read-only."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select id, title, status, result, created_at, completed_at "
            "from tasks where coalesce(result,'') != ''"
        ).fetchall()
    finally:
        # `with sqlite3.connect(...)` commits but does NOT close (memory:
        # sqlite-with-conn-does-not-close.md), so close explicitly.
        con.close()

    out = []
    for r in rows:
        ts = 0.0
        for key in ("completed_at", "created_at"):
            try:
                ts = max(ts, float(r[key] or 0))
            except (TypeError, ValueError):
                pass
        if since is not None and ts < since:
            continue
        out.append({
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "ts": ts,
            "fallback": is_fallback(r["result"]),
            "lever": classify_lever(r["result"], r["status"]),
        })
    return out


def attribute(outcomes: list[dict]) -> dict:
    """Rank levers by how many failures each one owns."""
    failures = [o for o in outcomes if o["lever"] != "ok"]
    by_lever = collections.Counter(o["lever"] for o in failures)
    total = len(failures)
    return {
        "closed_with_result": len(outcomes),
        "failures": total,
        "fallbacks": sum(1 for o in outcomes if o["fallback"]),
        "fallback_rate": round(sum(1 for o in outcomes if o["fallback"]) / len(outcomes), 4)
        if outcomes else 0.0,
        "by_lever": [
            {"lever": lev, "n": n, "share": round(n / total, 4) if total else 0.0}
            for lev, n in by_lever.most_common()
        ],
        "prompt_authority": round(by_lever.get("prompt_quality", 0) / total, 4) if total else 0.0,
        "dominant_lever": by_lever.most_common(1)[0][0] if total else None,
    }


def prompt_authority(db_path: str = DEFAULT_DB, since: float | None = None) -> dict:
    """The gate's entry point: attribution over the recorded corpus."""
    return attribute(load_outcomes(db_path, since=since))


def format_report(a: dict) -> str:
    lines = [
        f"closed tasks with a result : {a['closed_with_result']}",
        f"failures                   : {a['failures']}",
        f"fallback rate              : {a['fallback_rate']:.1%} "
        f"({a['fallbacks']}/{a['closed_with_result']})",
        "levers (what would have to change to remove the failure):",
    ]
    for row in a["by_lever"]:
        lines.append(f"   {row['share']:6.1%}  {row['n']:5}  {row['lever']}")
    lines.append(f"prompt_authority           : {a['prompt_authority']:.1%} "
                 f"— the share a prompt rewrite could reach")
    lines.append(f"dominant lever             : {a['dominant_lever']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--since", type=float, default=None, help="epoch seconds lower bound")
    args = ap.parse_args(argv)
    a = prompt_authority(args.db, since=args.since)
    print(json.dumps(a, indent=2) if args.json else format_report(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
