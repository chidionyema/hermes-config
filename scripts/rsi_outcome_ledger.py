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


# --- Recency: the gate must measure the CURRENT failure regime ---------------
# Attribution over all-time answers "what has ever gone wrong here", which is not
# the question the authority gate asks. Measured 2026-08-07: 170 of 174 recorded
# executor timeouts were the 30s cap fixed on 2026-08-06, and every no-cause
# fallback predates the exit-1 cause fix at coordinator.py:1349. Letting those
# rows vote holds the gate shut on bugs that no longer exist — RSI declining
# forever because of ghosts is indistinguishable from RSI being broken.
import time

AUTHORITY_WINDOW_DAYS = float(os.environ.get("RSI_AUTHORITY_WINDOW_DAYS", "14"))
# Below this many failures in the window, a share is noise rather than a
# measurement. The gate then STANDS ASIDE — it neither blocks nor waives, and
# the downstream ruler preflight still applies.
MIN_AUTHORITY_SAMPLE = int(os.environ.get("RSI_MIN_AUTHORITY_SAMPLE", "5"))


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
        # A share computed from a handful of rows is not evidence. Callers that
        # gate on prompt_authority must check this first.
        "sufficient_sample": total >= MIN_AUTHORITY_SAMPLE,
        "min_sample": MIN_AUTHORITY_SAMPLE,
    }


def prompt_authority(db_path: str = DEFAULT_DB, since: float | None = None) -> dict:
    """Attribution over the recorded corpus. `since=None` means ALL TIME —
    diagnostic only; gates want `recent_authority`."""
    return attribute(load_outcomes(db_path, since=since))


def recent_authority(db_path: str = DEFAULT_DB,
                     window_days: float | None = None,
                     now: float | None = None) -> dict:
    """The gate's entry point: attribution over the CURRENT regime only.

    A fixed bug keeps its rows forever; it must stop voting the day it is fixed.
    `now` is injectable so the window is testable without the wall clock.
    """
    days = AUTHORITY_WINDOW_DAYS if window_days is None else window_days
    ref = time.time() if now is None else now
    a = attribute(load_outcomes(db_path, since=ref - days * 86400.0))
    a["window_days"] = days
    return a


# --- Attempt-level attribution ------------------------------------------------
# MEASURED 2026-08-07: task-level attribution finds FIVE prompt_quality rows all-time
# (5 of 437 outcomes, 1.5%), and the SAME five in every window — so no honest window
# ever lifts the authority gate. That is not because prompt quality is irrelevant; it
# is because `classify_lever` grades a TASK, and a task is only counted once it dies
# in a FAILED_STATUS. A task that failed verification five times and was then retried
# into `done` burned five executor runs a better prompt could have prevented, and
# contributed ZERO to the metric.
#
# An executor prompt operates per ATTEMPT, so the attribution must too. The `verify`
# events are the attempt-level record: 1110 of them, 742 with ok=false. Counted there,
# the prompt-reachable share is 70.8% all-time / 95.4% over 14 days — two orders of
# magnitude from the task-level figure, on the same database, same day.
#
# This is a bigger numerator, so it deserves more suspicion, not less. Two guards:
#   * `ambiguous_exit_nonzero` — "acceptance test failed (exit≠0): (exit N, no output)"
#     carries NO evidence of who was wrong. The executor may have underdelivered or the
#     test may be broken. Those rows stay in the DENOMINATOR and are excluded from the
#     numerator, so the gate runs on the reading that could embarrass us.
#   * `acceptance_test_broken` — a test that cannot even run (command not found, no such
#     file) is a defect in the RULER, never in the executor's work.
# Conservative authority is 41.9% all-time and 42.9% over 14 days. That STABILITY across
# windows is itself the evidence it is a measurement and not the noise the task-level
# number was (12.5% → 21.7% → 9.1% across adjacent windows).

# Order is the measured order; changing it changes the numbers, so do not reorder
# without re-running the corpus classification.
_ATTEMPT_PATTERNS = (
    # Not prompt-reachable: no tools were available, so no wording would have helped.
    ("executor_fallback",      re.compile(r"fell back to chat|could not act", re.I)),
    # Not prompt-reachable: the acceptance test itself failed to run.
    ("acceptance_test_broken", re.compile(r"command not found|No such file or directory|"
                                          r"Permission denied|SyntaxError|ModuleNotFoundError|"
                                          r"unbound variable|cannot open", re.I)),
    # Unattributable by construction — kept out of the numerator on purpose.
    ("ambiguous_exit_nonzero", re.compile(r"acceptance test failed[^:]*:\s*\(exit \d+, no output\)",
                                          re.I)),
    # Prompt-reachable: the executor ran, produced output, and was still wrong.
    ("prompt_quality_unfixed", re.compile(r"failure condition still present", re.I)),
    ("prompt_quality_noproof", re.compile(r"acceptance test failed", re.I)),
    ("prompt_quality_prose",   re.compile(r"\bplans?\b|\bintentions?\b|\bI will\b|no actual output|"
                                          r"no concrete|does not contain concrete|only describes|"
                                          r"ambiguous|missing proof", re.I)),
)

PROMPT_REACHABLE_PREFIX = "prompt_quality"


def classify_attempt(reason: str | None) -> str:
    """Name the actuator that could have prevented ONE rejected execution attempt."""
    text = reason or ""
    if not text.strip():
        return "unclassified"
    for lever, pat in _ATTEMPT_PATTERNS:
        if pat.search(text):
            return lever
    return "unclassified"


def load_attempts(db_path: str = DEFAULT_DB, since: float | None = None) -> list[dict]:
    """Every REJECTED verification attempt, labelled with its lever. Read-only.

    Passed attempts are not failures and are not returned; the denominator this feeds
    is "attempts that went wrong", matching `attribute`'s task-level denominator.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select task_id, payload, created_at from events where kind='verify'"
        ).fetchall()
    finally:
        con.close()

    out = []
    for r in rows:
        ts = float(r["created_at"] or 0)
        if since is not None and ts < since:
            continue
        try:
            p = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(p, dict):
            continue
        # The producer has used both spellings; a gate that knows only one silently
        # drops half the corpus (the Layer 0 lesson, coordinator.py:869).
        verdict = p.get("ok", p.get("passed"))
        if verdict is not False:
            continue
        reason = p.get("reason") or ""
        out.append({"task_id": r["task_id"], "ts": ts, "reason": reason,
                    "lever": classify_attempt(reason)})
    out.sort(key=lambda o: o["ts"])
    return out


def attempt_attribute(attempts: list[dict]) -> dict:
    """Rank levers over rejected attempts. Same shape as `attribute` so the gate can
    consume either without branching."""
    by_lever = collections.Counter(a["lever"] for a in attempts)
    total = len(attempts)
    reachable = sum(n for lev, n in by_lever.items()
                    if lev.startswith(PROMPT_REACHABLE_PREFIX))
    return {
        "level": "attempt",
        "closed_with_result": total,
        "failures": total,
        "fallback_rate": round(by_lever.get("executor_fallback", 0) / total, 4) if total else 0.0,
        "by_lever": [
            {"lever": lev, "n": n, "share": round(n / total, 4) if total else 0.0}
            for lev, n in by_lever.most_common()
        ],
        # Conservative by construction: `ambiguous_exit_nonzero` is in the denominator
        # and never in the numerator.
        "prompt_authority": round(reachable / total, 4) if total else 0.0,
        "prompt_reachable": reachable,
        "ambiguous": by_lever.get("ambiguous_exit_nonzero", 0),
        "dominant_lever": by_lever.most_common(1)[0][0] if total else None,
        "sufficient_sample": total >= MIN_AUTHORITY_SAMPLE,
        "min_sample": MIN_AUTHORITY_SAMPLE,
    }


def recent_attempt_authority(db_path: str = DEFAULT_DB,
                             window_days: float | None = None,
                             now: float | None = None) -> dict | None:
    """The gate's entry point at attempt level, or None when this database has no
    verify events at all (an older schema, or a fresh install) — the caller then
    falls back to `recent_authority` rather than reading an empty corpus as 0%."""
    days = AUTHORITY_WINDOW_DAYS if window_days is None else window_days
    ref = time.time() if now is None else now
    if not load_attempts(db_path):
        return None
    a = attempt_attribute(load_attempts(db_path, since=ref - days * 86400.0))
    a["window_days"] = days
    return a


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
    if "window_days" in a:
        lines.append(f"window                     : last {a['window_days']:.0f} days "
                     f"(--all-time to include fixed bugs)")
    if not a.get("sufficient_sample", True):
        lines.append(f"⚠️  sample                  : {a['failures']} failures < "
                     f"{a['min_sample']} — too few to gate on; authority stands aside")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--since", type=float, default=None, help="epoch seconds lower bound")
    ap.add_argument("--window-days", type=float, default=None,
                    help=f"count only outcomes newer than N days (default "
                         f"{AUTHORITY_WINDOW_DAYS:.0f})")
    ap.add_argument("--all-time", action="store_true",
                    help="no recency window — includes already-fixed bugs; diagnostic only")
    args = ap.parse_args(argv)
    if args.all_time or args.since is not None:
        a = prompt_authority(args.db, since=args.since)
    else:
        a = recent_authority(args.db, window_days=args.window_days)
    print(json.dumps(a, indent=2) if args.json else format_report(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
