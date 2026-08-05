#!/usr/bin/env python3
"""Mid-day digest — runs at 1pm and 8:50am.

Between the lightweight 30-min pulse and the heavy 6pm strategic reflection, this
delivers a human-readable snapshot of the day so far:
- Estate activity (tasks done / stuck / escalated)
- Recurring mistake pattern (last 24h error categories)
- Recent injection volume
- Outstanding improvement items from latest self-audit

Writes one file to logs/reflection/digest-<timestamp>.md and (optionally) sends to Telegram.
No LLM cost — pure DB queries.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
DIGEST_DIR = HERMES / "logs" / "reflection" / "digests"
DIGEST_DIR.mkdir(parents=True, exist_ok=True)
_HOME_BIN = Path(os.environ.get("HOME", "~")) / ".local" / "bin"
COOR_DB = HERMES / "coordinator.db"
ERRORS = HERMES / "logs" / "errors.log"
INJECTION = HERMES / "logs" / "injection-log.jsonl"
LATEST_AUDIT = HERMES / "logs" / "self-audit" / f"{datetime.now(timezone.utc):%Y-%m-%d}.md"


def _coor() -> dict:
    if not COOR_DB.exists():
        return {}
    out = {}
    try:
        conn = sqlite3.connect(str(COOR_DB), timeout=5)
        for label, sql in [
            ("by_status", "SELECT status, COUNT(*) FROM tasks GROUP BY status"),
            ("stuck", "SELECT id, title, consecutive_failures FROM tasks "
                      "WHERE status='escalated' OR consecutive_failures > 0 "
                      "ORDER BY consecutive_failures DESC, created_at DESC LIMIT 5"),
            ("done_today", "SELECT COUNT(*) FROM tasks WHERE status='done' "
                           "AND COALESCE(completed_at, created_at) >= ?"),
            ("awaiting", "SELECT COUNT(*) FROM tasks WHERE status='awaiting_approval'"),
        ]:
            try:
                if "?" in sql:
                    out[label] = conn.execute(sql, (time.time() - 86400,)).fetchall()
                else:
                    out[label] = conn.execute(sql).fetchall()
            except Exception:
                out[label] = None
        conn.close()
    except Exception as e:
        out["_error"] = str(e)
    return out


def _error_categories() -> Counter:
    cats = Counter()
    if not ERRORS.exists():
        return cats
    cutoff = time.time() - 86400
    try:
        for line in ERRORS.read_text().splitlines()[-2000:]:
            # Heuristic: file:line: error category
            for cat in ("NetworkError", "ServiceUnavailable", "AuthError",
                        "TimeoutError", "ValidationError", "ResourceExhausted"):
                if cat in line:
                    cats[cat] += 1
                    break
    except Exception:
        pass
    return cats


def _injection_volume() -> int:
    if not INJECTION.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - 86400
    n = 0
    try:
        for line in INJECTION.read_text().splitlines()[-500:]:
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                t = datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


def main() -> int:
    coor = _coor()
    errs = _error_categories()
    inj = _injection_volume()

    bs = dict(coor.get("by_status") or [])
    done_today = (coor.get("done_today") or [(0,)])[0][0]
    awaiting = (coor.get("awaiting") or [(0,)])[0][0]

    ts = datetime.now(timezone.utc)
    fname = DIGEST_DIR / f"digest-{ts.strftime('%Y%m%d-%H%M%S')}.md"
    lines = [
        f"# Otto Digest — {ts.isoformat(timespec='seconds')}",
        "",
        "## Estate state",
        "",
        f"- Tasks: {', '.join(f'{v} {k}' for k, v in sorted(bs.items())) or 'unknown'}",
        f"- Done in last 24h: **{done_today}**",
        f"- Awaiting approval: **{awaiting}**",
        "",
        "## Stuck tasks",
        "",
    ]
    stuck = coor.get("stuck") or []
    if stuck:
        for r in stuck:
            rid = str(r[0])[:8] if r and r[0] else "?"
            title = (r[1][:60] if len(r) > 1 and r[1] else "?")
            cf = r[2] if len(r) > 2 and r[2] else 0
            lines.append(f"- ⚠️ `{rid}` {title} — {cf}× fail")
    else:
        lines.append("_No escalated or failing tasks._")
    lines.append("")
    lines.append("## Errors (24h, top categories)")
    lines.append("")
    if errs:
        for cat, n in errs.most_common(5):
            lines.append(f"- `{cat}`: {n}")
    else:
        lines.append("_None recorded._")
    lines.append("")
    lines.append(f"## Injections (24h): **{inj}**")
    lines.append("")
    if LATEST_AUDIT.exists():
        # Pull the "Improvement Plan" lines so the digest points forward
        try:
            audit_text = LATEST_AUDIT.read_text()
            plan_lines = []
            in_plan = False
            for ln in audit_text.splitlines():
                if "Improvement plan" in ln or "Improvement Plan" in ln:
                    in_plan = True
                    continue
                if in_plan and ln.strip().startswith(("-", "1.", "2.", "3.", "4.", "5.")):
                    plan_lines.append(ln)
                elif in_plan and ln.strip() and not ln.startswith(" "):
                    in_plan = False
            if plan_lines:
                lines.append("## Outstanding improvement items (from today's audit)")
                lines.append("")
                lines.extend(plan_lines[:6])
                lines.append("")
        except Exception:
            pass

    fname.write_text("\n".join(lines))
    print(f"[digest] wrote {fname.name} — escalated={bs.get('escalated',0)} done_24h={done_today}")

    # Auto-deliver to Telegram (no-op if hermes CLI unavailable or bot down).
    # Uses the home channel — same as morning_brief / daily-digest.
    try:
        import subprocess as _sp
        _r = _sp.run(
            [_HOME_BIN / "hermes", "send", "--to", "telegram"],
            input=("\n".join(lines)).encode(),
            capture_output=True, timeout=15,
        )
        if _r.returncode == 0 and _r.stdout:
            print(f"[digest] telegram: {_r.stdout.decode().strip()}")
        elif _r.stderr:
            print(f"[digest] telegram stderr: {_r.stderr.decode().strip()[:100]}", file=sys.stderr)
    except Exception as _e:
        # Silent failure — file already saved, delivery is best-effort
        print(f"[digest] telegram send skipped: {_e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
