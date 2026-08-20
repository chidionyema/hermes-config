#!/usr/bin/env python3
"""Refuse to let the self-improvement loop run in silence again.

THE INCIDENT. Measured 2026-08-19: 244 hourly cycles, 1,723 gaps found, **0 closed**, 247
shadow policies written, health score 0.457 -> 0.250. Three separate defects had broken the
loop and none of them raised anything, because `self_improve_runner.run_cycle` printed its
result to stdout and wrote it nowhere. There was no series to look at, so nobody looked.

The class is: **a loop whose two halves each run green while never once agreeing on a key.**
The producer (gap-finding) tagged failures with capability domains; the consumer (the outcome
store) recorded executor names. Both halves worked. Nothing compared them.

This module closes that class with two signals a machine can check:

  STALL      — the last N recorded cycles all found gaps and closed none.
  DISJOINT   — gaps are waiting on outcome evidence in domains the outcome store has never
               recorded a single row for, while the store is not empty. That is the exact
               shape of the 2026-08-19 defect and it is visible on cycle ONE, not cycle 244.

`record_cycle` is what makes any of this possible: it gives the loop a series.

Exit code 1 on unhealthy, so cron, CI and a hook can all refuse it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
CYCLES = HERMES / "logs" / "self-improve-cycles.jsonl"
STALL_WINDOW = int(os.environ.get("HERMES_RSI_STALL_WINDOW", "6"))


def record_cycle(results: dict, home: Path | None = None) -> None:
    """Append one cycle to the series. Never raises — a broken recorder must not stop a cycle."""
    home = home or HERMES
    path = home / "logs" / "self-improve-cycles.jsonl"
    gaps = results.get("gaps", {}) or {}
    meta = results.get("meta", {}) or {}
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "gaps_found": gaps.get("gaps_found", 0),
        "uncovered": gaps.get("uncovered", 0),
        "auto_closed": gaps.get("auto_closed", 0),
        "shadow": gaps.get("shadow", 0),
        "escalated": gaps.get("escalated", 0),
        "shadow_eval": gaps.get("shadow_eval", {}),
        "health_score": meta.get("health_score"),
        "velocity": meta.get("velocity"),
        "elapsed": results.get("elapsed"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        sys.stderr.write(f"rsi_loop_guard: could not record cycle: {e}\n")


def _cycles(home: Path, window: int) -> list:
    path = home / "logs" / "self-improve-cycles.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-window:]


def _outcome_domains(home: Path) -> dict:
    """{domain: row count} from the live outcome store. Empty dict when there is no store.

    A plain connect, not `mode=ro`: the store runs in WAL mode and a read-only URI cannot
    open the -shm sidecar, so it fails with "unable to open database file" — the same trap
    that made `auto_close_identity._domain_outcomes` silently return nothing.
    """
    db = home / "state" / "outcomes.db"
    if not db.is_file():
        return {}
    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            return {r[0]: r[1] for r in
                    conn.execute("SELECT domain, COUNT(*) FROM task_outcomes GROUP BY domain")}
        finally:
            conn.close()
    except sqlite3.Error as e:
        sys.stderr.write(f"rsi_loop_guard: outcome store unreadable: {e}\n")
        return {}


def _waiting_domains(home: Path) -> set:
    """Domains of gaps parked in SHADOW — the ones whose promotion waits on outcome rows."""
    path = home / "logs" / "active-gaps.json"
    if not path.is_file():
        return set()
    try:
        gaps = json.loads(path.read_text())
    except json.JSONDecodeError:
        return set()
    return {v.get("domain", "") for v in gaps.values() if v.get("status") == "shadow"}


def check(home: Path | None = None, window: int = STALL_WINDOW) -> dict:
    home = home or HERMES
    problems = []

    rows = _cycles(home, window)
    if len(rows) >= window and all(
        (r.get("gaps_found") or 0) > 0 and (r.get("auto_closed") or 0) == 0 for r in rows
    ):
        problems.append(
            "STALL: the last %d cycles found gaps (%s) and closed none. The loop is running "
            "and learning nothing." % (window, ", ".join(str(r.get("gaps_found")) for r in rows))
        )

    outcomes = _outcome_domains(home)
    waiting = _waiting_domains(home)
    if outcomes and waiting:
        blind = sorted(d for d in waiting if outcomes.get(d, 0) == 0)
        if blind:
            problems.append(
                "DISJOINT: %d shadow gap domain(s) have zero rows in the outcome store "
                "(%s), while the store holds %d rows across %s. The half that finds gaps and "
                "the half that records outcomes are not using the same vocabulary, so no "
                "shadow can ever be graded."
                % (len(blind), ", ".join(blind), sum(outcomes.values()),
                   ", ".join(sorted(outcomes)))
            )

    return {"healthy": not problems, "problems": problems,
            "cycles_examined": len(rows), "outcome_domains": outcomes,
            "waiting_domains": sorted(waiting)}


def main() -> int:
    alert = "--alert" in sys.argv
    r = check()
    if r["healthy"]:
        print("rsi loop OK — %d cycles examined, outcome domains: %s"
              % (r["cycles_examined"], r["outcome_domains"] or "none yet"))
        return 0
    for p in r["problems"]:
        print("UNHEALTHY: " + p)
    if alert:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from estate_alert import send_operator_alert
            send_operator_alert(
                "🧠 Self-improvement loop unhealthy\n\n" + "\n\n".join(r["problems"]),
                debounce_key="rsi-loop-guard",
                # 12h, not the 300s default. This condition clears over DAYS as
                # capability-domain outcomes accrue, and the cycle runs hourly, so
                # the default would send the same sentence 24 times a day.
                debounce_s=43200,
            )
        except Exception as e:
            sys.stderr.write(f"rsi_loop_guard: alert failed: {e}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
