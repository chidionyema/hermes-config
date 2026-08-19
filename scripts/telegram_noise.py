#!/usr/bin/env python3
"""telegram_noise — what actually reached the operator's channel, and from where.

The answer to "is the channel too noisy?" is this command, never a sentence. It reads
scripts/telegram_ledger.py's record of every attempted send and reports volume by
sender, by outcome, and by repeated message — because the same line sent forty times
is a different problem from forty different lines, and the fix is different too.

Read-only. It sends nothing.

  python3 ~/.hermes/scripts/telegram_noise.py            # last 24 hours
  python3 ~/.hermes/scripts/telegram_noise.py --since 2h
  python3 ~/.hermes/scripts/telegram_noise.py --since 7d --full
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_ledger                                    # noqa: E402


def parse_since(text: str) -> float:
    """'90m', '24h', '7d' → seconds. A bare number is hours, which is how people say it."""
    text = text.strip().lower()
    unit = text[-1]
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
    if mult is None:
        return float(text) * 3600
    return float(text[:-1]) * mult


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="24h", help="window, e.g. 90m / 24h / 7d (default 24h)")
    ap.add_argument("--full", action="store_true", help="list every row, not just the summary")
    args = ap.parse_args()

    window = parse_since(args.since)
    rows = telegram_ledger.read(window)

    if not telegram_ledger.LEDGER.exists():
        print(f"No ledger at {telegram_ledger.LEDGER}.")
        print("Nothing has been sent since it was installed, or the senders are not wired to it.")
        return 0
    if not rows:
        print(f"Nothing sent in the last {args.since}. Ledger: {telegram_ledger.LEDGER}")
        return 0

    by_outcome = collections.Counter(r.get("outcome", "?") for r in rows)
    # "Reached the operator" is `sent` alone. An edit replaces a message already there, and
    # everything else never arrived — grouping them would answer a different question.
    reached = by_outcome.get("sent", 0)

    print(f"── Telegram, last {args.since} ── {telegram_ledger.LEDGER}")
    print(f"{reached} message(s) reached the channel"
          f"  ({reached / (window / 3600):.1f}/hour)")
    print()
    print("BY OUTCOME")
    for outcome, n in by_outcome.most_common():
        print(f"  {n:6d}  {outcome}")

    print()
    print("BY SENDER (only what reached the channel)")
    senders = collections.Counter(r.get("source", "?") for r in rows if r.get("outcome") == "sent")
    for src, n in senders.most_common():
        chars = sum(r.get("chars", 0) for r in rows
                    if r.get("source") == src and r.get("outcome") == "sent")
        print(f"  {n:6d}  {src}  ({chars:,} chars)")
    if not senders:
        print("  (none)")

    print()
    print("MOST REPEATED (same opening line, sent more than once)")
    heads = collections.Counter(r.get("head", "") for r in rows if r.get("outcome") == "sent")
    repeats = [(h, n) for h, n in heads.most_common() if n > 1]
    for head, n in repeats[:10]:
        print(f"  {n:6d}  {head[:96]}")
    if not repeats:
        print("  (none — every message was distinct, so the volume is real, not a loop)")

    print()
    print("BY HOUR")
    buckets = collections.Counter(
        time.strftime("%m-%d %H", time.localtime(r["ts"])) for r in rows
        if r.get("outcome") == "sent" and r.get("ts"))
    for hour in sorted(buckets):
        print(f"  {hour}  {'█' * min(buckets[hour], 60)} {buckets[hour]}")
    if not buckets:
        print("  (none)")

    if args.full:
        print()
        print("EVERY ROW")
        for r in rows:
            print(f"  {r.get('iso','')}  {r.get('outcome',''):<12} {r.get('source','')}  "
                  f"{r.get('head','')[:80]}")

    cap = int(os.environ.get("HERMES_ALERT_HOURLY_CAP", "12"))
    print()
    print(f"Alert ceiling is {cap}/hour (HERMES_ALERT_HOURLY_CAP). Alerts past it are held and "
          f"recorded here, and one summary line goes to the channel instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
