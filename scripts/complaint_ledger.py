#!/usr/bin/env python3
"""Persist the founder-complaint scan so it stops evaporating between sessions.

WHAT THIS IS NOT
----------------
It is not a scanner of its own. `~/.claude/scripts/reflect.py` already knows how to tell the
founder's own words from the contaminants that `role: user` sweeps up — tool results, task
notifications, subagent turns, compaction replays — and how to theme what is left. This file
imports that logic. I started writing a second scanner on 2026-08-17 and threw it away when I
found reflect.py, which is itself the defect the founder named that day: "you lost track of
all the process improvements we are trying to solve".

WHY IT IS INCREMENTAL
---------------------
The corpus is 5.3 GB across 88,951 transcript files. A full re-read took over 900 seconds and
was killed by its own timeout, which makes it useless as a daily job. Transcripts are
append-only, so this remembers the byte offset it stopped at in every file and reads only
what is new. A file that shrank or was rewritten is re-read from zero. The first run pays the
full cost once; every run after it reads the tail.

    python3 complaint_ledger.py             # incremental scan, write the ledger, summarise
    python3 complaint_ledger.py --full      # ignore the cache and re-read everything
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
CACHE = HERMES_HOME / "state" / "complaint_ledger.cache.json"
# The scan is evidence and is overwritten every day. The REGISTER is the work list and is
# never overwritten by a scan: it is the only file here that remembers what was DONE.
REGISTER = HERMES_HOME / "state" / "complaint_register.json"
REFLECT = Path(os.path.expanduser("~/.claude/scripts/reflect.py"))
PROJECTS = Path(os.path.expanduser("~/.claude/projects"))


# A complaint is the first sentence or two. Everything after that is pasted tool output the
# founder quoted to show us the problem. Storing it whole took the cache to 835 MB across
# 89,792 files, and a daily run then spent 55s reading it and 112s parsing it before it
# looked at a single transcript — measured 2026-08-17, against 4 files that had changed.
_TEXT_CAP = 2000


def _trim(cache: dict) -> dict:
    """Cap the stored body of every cached row. Applied on write, so the existing fat cache
    shrinks on the next run without anyone having to rescan 5.3 GB."""
    for entry in cache.values():
        for row in entry.get("rows") or ():
            body = row.get("text")
            if isinstance(body, str) and len(body) > _TEXT_CAP:
                row["text"] = body[:_TEXT_CAP]
    return cache


def write_cache(cache: dict) -> None:
    """Write the byte-offset cache atomically.

    Called mid-scan on a 60s clock as well as at the end. A half-written cache would send
    the next run back over 5.3 GB, so the temp-file-then-replace is not optional.
    """
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_trim(cache)))
    tmp.replace(CACHE)


# Cheap pre-filter. A line that cannot be a user message is skipped before json.loads, which
# is where nearly all the time went: parsing 5 GB of JSON to discard 99% of it.
_USER_HINTS = ('"role":"user"', '"role": "user"')
_ASST_HINTS = ('"role":"assistant"', '"role": "assistant"')


def load_reflect():
    """Import reflect.py by path. It is a script, not a package."""
    spec = importlib.util.spec_from_file_location("reflect", REFLECT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {REFLECT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_founder(rec: dict, reflect) -> bool:
    """Every rejection here is a contaminant reflect.py found the hard way: its first run
    counted 716 complaints and the verbatim sample was a task-notification block."""
    if rec.get("isSidechain") or rec.get("isMeta") or rec.get("isCompactSummary"):
        return False
    if "toolUseResult" in rec:
        return False
    if rec.get("userType") not in (None, "external"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    return True


def scan_file(path: Path, start: int, reflect) -> tuple[list[dict], int]:
    """Read from `start` to EOF. Returns (complaints, new offset)."""
    rows: list[dict] = []
    try:
        with path.open("rb") as fh:
            fh.seek(start)
            raw = fh.read()
            end = fh.tell()
    except OSError:
        return [], start
    text_all = raw.decode("utf-8", errors="replace")
    # A partial final line means the session is still being written. Stop before it and come
    # back tomorrow, rather than parse half a record.
    lines = text_all.split("\n")
    if lines and lines[-1] and not text_all.endswith("\n"):
        end -= len(lines[-1].encode("utf-8"))
        lines = lines[:-1]

    for line in lines:
        if not line:
            continue
        is_user = any(h in line for h in _USER_HINTS)
        is_asst = any(h in line for h in _ASST_HINTS)
        if not (is_user or is_asst):
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if is_asst:
            # Harvest assistant text so _own_words can strip quoted replies out of a paste.
            reflect._harvest_assistant(reflect._text((rec.get("message") or {}).get("content")))
            continue
        if not _is_founder(rec, reflect):
            continue
        body = reflect._text((rec.get("message") or {}).get("content")).strip()
        if not body or len(body) < 12:
            continue
        if body.lstrip().startswith(("<task-notification>", "<user-prompt-submit-hook",
                                     "<bash-", "<command-", "[Request interrupted")):
            continue
        if any(m in body for m in reflect.NOT_THE_FOUNDER):
            continue
        own = reflect._own_words(body)
        if not reflect.COMPLAINT_MARKERS.search(own):
            continue
        rows.append({
            "ts": str(rec.get("timestamp", "")),
            "month": str(rec.get("timestamp", ""))[:7],
            "project": path.parent.name,
            "file": path.name,
            "own": own,
            "text": body[:_TEXT_CAP],
            "themes": reflect._themes_of(body),
        })
    return rows, end


def scan(full: bool) -> tuple[list[dict], dict, int, int]:
    reflect = load_reflect()
    cache: dict = {}
    if not full and CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}

    rows: list[dict] = []
    read_files = 0
    # The first scan reads the whole corpus: measured 2026-08-17, 89,779 transcripts and
    # 5.3 GB under ~/.claude/projects, about 22 minutes. Writing the cache only at the end
    # made that 22 minutes all-or-nothing, and it was killed twice before it ever finished,
    # each time starting from zero. Checkpoint on a clock so a kill costs at most 60s of
    # work. Daily runs afterwards read only the new bytes and never reach this path.
    last_ckpt = time.monotonic()
    for path in PROJECTS.rglob("*.jsonl"):
        key = str(path)
        entry = cache.get(key) or {}
        start = int(entry.get("offset", 0))
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < start:            # rewritten or truncated — start over
            start, entry = 0, {}
        if size == start and entry:  # nothing new
            rows.extend(entry.get("rows", []))
            continue
        new_rows, end = scan_file(path, start, reflect)
        read_files += 1
        merged = list(entry.get("rows", [])) + new_rows
        cache[key] = {"offset": end, "rows": merged}
        rows.extend(merged)
        if time.monotonic() - last_ckpt >= 60:
            write_cache(cache)
            last_ckpt = time.monotonic()
            print(f"[complaint_ledger] {read_files} files read, {len(rows)} rows so far",
                  file=sys.stderr, flush=True)

    # De-duplicate last: a resumed session replays earlier turns verbatim, and the same
    # complaint reaches several checkouts. Counting raw occurrences ranks whichever session
    # was compacted most, not whichever problem recurred most.
    seen: set[str] = set()
    unique: list[dict] = []
    for m in rows:
        k = " ".join((m.get("own") or m["text"]).lower().split())[:300]
        if k in seen:
            continue
        seen.add(k)
        unique.append(m)
    unique.sort(key=lambda m: m.get("month") or "", reverse=True)
    return unique, cache, read_files, len(rows)


def _ts_of(m: dict) -> str:
    """Full timestamp where we have it; older cached rows only kept the month."""
    return m.get("ts") or ((m.get("month") or "") + "-01")


def merge_register(rows: list[dict]) -> dict:
    """Fold today's evidence into the standing work list.

    THE POINT OF THIS FUNCTION. A scan that only ever prints is a bigger pile, not a plan:
    every run re-finds the same 373 complaints and nothing says which have been dealt with.
    So the unit of work is the THEME, not the complaint — nobody works a list of 373, and the
    same root cause is complained about a dozen ways.

    A close is provisional. If a complaint in a closed theme arrives AFTER the close date, the
    theme reopens itself and counts the reopen. That is the only way to learn that a fix did
    not hold without asking anyone.
    """
    reg: dict = {}
    if REGISTER.exists():
        try:
            reg = json.loads(REGISTER.read_text()).get("themes", {})
        except Exception:
            reg = {}

    by_theme: dict[str, list[dict]] = {}
    for m in rows:
        for t in m.get("themes") or ["unthemed"]:
            by_theme.setdefault(t, []).append(m)

    for theme, items in by_theme.items():
        stamps = sorted(_ts_of(m) for m in items if _ts_of(m))
        entry = reg.get(theme) or {
            "status": "open", "first_seen": stamps[0] if stamps else "",
            "receipt": "", "closed_at": "", "reopened": 0,
        }
        entry["count"] = len(items)
        entry["last_seen"] = stamps[-1] if stamps else entry.get("last_seen", "")
        entry["first_seen"] = entry.get("first_seen") or (stamps[0] if stamps else "")
        if entry.get("status") == "closed" and entry.get("closed_at"):
            if any(s > entry["closed_at"] for s in stamps):
                entry["status"] = "open"
                entry["reopened"] = int(entry.get("reopened", 0)) + 1
                entry["receipt"] = f"REOPENED — recurred after {entry['closed_at']}"
        reg[theme] = entry

    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    REGISTER.write_text(json.dumps({"themes": reg}, indent=1, sort_keys=True))
    return reg


def _age_days(stamp: str) -> float:
    if not stamp:
        return 0.0
    try:
        from datetime import datetime, timezone
        s = stamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 0.0


def summarise(rows: list[dict], reg: dict | None = None) -> None:
    themes: Counter = Counter()
    months: dict[str, set] = {}
    for m in rows:
        for t in m.get("themes") or ["unthemed"]:
            themes[t] += 1
            months.setdefault(t, set()).add(m.get("month") or "?")
    print(f"COMPLAINTS: {len(rows)} unique across every project\n")
    print(f"  {'count':>5}  {'months':>6}  {'state':<8}  theme")
    for theme, n in themes.most_common():
        e = (reg or {}).get(theme) or {}
        state = e.get("status", "open")
        if state == "closed":
            state = "closed"
        elif int(e.get("reopened", 0)):
            state = f"REOPEN{e['reopened']}"
        print(f"  {n:>5}  {len(months[theme]):>6}  {state:<8}  {theme}")

    if reg:
        openers = [(t, e) for t, e in reg.items() if e.get("status") != "closed"]
        if openers:
            oldest = max(openers, key=lambda te: _age_days(te[1].get("first_seen", "")))
            print(f"\nOPEN THEMES: {len(openers)} of {len(reg)}")
            print(f"OLDEST OPEN: {_age_days(oldest[1].get('first_seen','')):.0f} days — "
                  f"{oldest[0]}")
        else:
            print("\nOPEN THEMES: none")
    print("\nClosing needs a receipt: complaint_ledger.py --close <theme> --receipt <proof>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="ignore the cache, re-read everything")
    ap.add_argument("--print", dest="print_only", action="store_true")
    ap.add_argument("--close", metavar="THEME", help="mark a theme dealt with")
    ap.add_argument("--receipt", help="the proof: a commit sha, a file:line, or a probe line")
    args = ap.parse_args()

    if args.close:
        # A close without proof is the thing this whole file exists to stop.
        if not args.receipt:
            print("refused: --close needs --receipt (a commit sha, a file:line, a probe line)")
            return 1
        reg = json.loads(REGISTER.read_text()).get("themes", {}) if REGISTER.exists() else {}
        if args.close not in reg:
            print(f"no such theme: {args.close}\nthemes: {', '.join(sorted(reg))}")
            return 1
        reg[args.close].update({
            "status": "closed",
            "receipt": args.receipt,
            "closed_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        })
        REGISTER.write_text(json.dumps({"themes": reg}, indent=1, sort_keys=True))
        print(f"closed: {args.close}\nreceipt: {args.receipt}")
        print("It reopens by itself if the same complaint is made again after today.")
        return 0

    if args.print_only:
        if not LEDGER.exists():
            print("No ledger yet. Run without --print.")
            return 1
        data = json.loads(LEDGER.read_text())
        reg = json.loads(REGISTER.read_text()).get("themes", {}) if REGISTER.exists() else {}
        print(f"(ledger written {(time.time() - data.get('generated_at', 0)) / 3600:.1f}h ago)\n")
        summarise(data.get("complaints", []), reg)
        return 0

    started = time.time()
    rows, cache, read_files, raw = scan(args.full)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps({
        "generated_at": time.time(),
        "source": str(REFLECT),
        "scan_seconds": round(time.time() - started, 1),
        "files_read_this_run": read_files,
        "complaints": rows,
    }, indent=1))
    write_cache(cache)
    reg = merge_register(rows)
    summarise(rows, reg)
    print(f"\nledger: {LEDGER}")
    print(f"read {read_files} files this run ({raw} rows before dedup) in "
          f"{time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
