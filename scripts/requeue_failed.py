#!/usr/bin/env python3
"""Recover the stranded `failed` tasks — bounded, deduped, dry-run by default.

WHY THEY ARE STRANDED
`coordinator.py:446-447` declares ACTIVE and TERMINAL; `failed` is in neither, and no live
code path assigns it. The 243 rows came from a one-shot retrospective audit that relabelled
fabricated completions (`backfill_layer0`). The tick's only work query (`:740`) is
`WHERE status IN (ACTIVE)`, so they are unreachable by every retry path that exists.

WHY A BLIND REQUEUE IS WRONG
Measured 2026-08-07: the 243 rows carry only **40 distinct titles**. "Status report for
Prospector" appears 49 times, Haworks 44, Signal Engine 41 — these are recurring cron tasks.
Requeueing all of them re-runs identical work dozens of times against the one Claude
subscription, and provider_capacity is already 35.2% of failures in the 14-day window. So:

  RULE: a failed row is a candidate ONLY if it is the newest task for its title.
  Anything superseded by a later task — failed or not — is stale by construction: the cron
  already regenerated it, or a duplicate already ran. Requeueing it buys nothing.

SAFETY
  * Dry run unless --apply. Dry run opens the DB read-only.
  * --apply refuses without a backup of the DB.
  * Bounded by --limit (default 10) and by MAX_REQUEUES per task, tracked in meta exactly as
    `requeue_transient_escalations` (`coordinator.py:2181`) does, so a row cannot loop forever.
  * Writes status='diagnosed' — the coordinator's own retry entry point (`:2128`) — plus a
    `requeued_from_failed` event carrying the reason, so the change is auditable.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

DEFAULT_DB = os.path.expanduser("~/.hermes/coordinator.db")
MAX_REQUEUES = 2


def _connect(db_path, writable):
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    uri = f"file:{db_path}" + ("" if writable else "?mode=ro")
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _backups(db_path):
    d, base = os.path.dirname(db_path), os.path.basename(db_path)
    return [f for f in os.listdir(d or ".") if f.startswith(base + ".bak")]


def _requeue_count(con, tid):
    row = con.execute("select value from meta where key=?",
                      (f"requeue_count:{tid}",)).fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def select_candidates(con, limit):
    """Failed rows that are the NEWEST task for their title. Returns (candidates, skipped)."""
    newest_by_title = {}
    for r in con.execute("select id, title, created_at from tasks").fetchall():
        t = r["title"] or ""
        ts = float(r["created_at"] or 0)
        if t not in newest_by_title or ts > newest_by_title[t][1]:
            newest_by_title[t] = (r["id"], ts)

    candidates, superseded, capped = [], 0, 0
    rows = con.execute(
        "select id, title, created_at from tasks where status='failed' "
        "order by created_at desc").fetchall()
    for r in rows:
        if newest_by_title.get(r["title"] or "", (None, 0))[0] != r["id"]:
            superseded += 1
            continue
        if _requeue_count(con, r["id"]) >= MAX_REQUEUES:
            capped += 1
            continue
        candidates.append(r)
    return candidates[:limit], {"total_failed": len(rows), "superseded": superseded,
                                "requeue_capped": capped,
                                "eligible": len(candidates)}


def apply_requeue(con, candidates, reason):
    now = time.time()
    ids = []
    for r in candidates:
        tid = r["id"]
        n = _requeue_count(con, tid)
        con.execute(
            "insert into events (task_id, kind, payload, created_at) values (?,?,?,?)",
            (tid, "requeued_from_failed",
             json.dumps({"attempt": n + 1, "max": MAX_REQUEUES, "from": "failed",
                         "to": "diagnosed", "reason": reason}), now))
        con.execute(
            "update tasks set status='diagnosed', consecutive_failures=0, "
            "last_failure_error=null where id=?", (tid,))
        con.execute("insert or replace into meta (key, value) values (?,?)",
                    (f"requeue_count:{tid}", str(n + 1)))
        ids.append(tid)
    con.commit()
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=10,
                    help="max tasks to requeue in one run (default 10)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without this the DB is opened READ-ONLY")
    ap.add_argument("--reason", default="stranded by the layer0 relabel; "
                                        "executor fabrications now diagnosable")
    args = ap.parse_args(argv)

    if args.apply and not _backups(args.db):
        print(f"REFUSING: no backup matching {os.path.basename(args.db)}.bak* — "
              f"take one before writing to a production DB.")
        return 2

    con = _connect(args.db, writable=args.apply)
    try:
        cands, stats = select_candidates(con, args.limit)
        print(f"failed rows        : {stats['total_failed']}")
        print(f"  superseded       : {stats['superseded']}  "
              f"(a newer task exists for the same title — stale by construction)")
        print(f"  requeue-capped   : {stats['requeue_capped']}  (already retried {MAX_REQUEUES}x)")
        print(f"  eligible         : {stats['eligible']}")
        print(f"  selected (limit {args.limit}): {len(cands)}")
        for r in cands:
            print(f"    {r['id']}  {(r['title'] or '')[:78]!r}")
        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to requeue the selected rows.")
            return 0
        ids = apply_requeue(con, cands, args.reason)
        print(f"\nrequeued {len(ids)} task(s) failed -> diagnosed")
        return 0
    finally:
        # `with sqlite3.connect(...)` commits but does NOT close (memory:
        # sqlite-with-conn-does-not-close.md).
        con.close()


if __name__ == "__main__":
    sys.exit(main())
