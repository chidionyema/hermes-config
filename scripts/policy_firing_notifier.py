#!/usr/bin/env python3
"""Send policy firing events to Telegram — proves the loop is closed.

Reads the latest firings since last notification, formats a compact alert,
and ships it via `hermes send --to telegram`. State persisted in
logs/.last_notified_firing_ts so we don't double-notify.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
FIRINGS = HERMES / "logs" / "policy-firings.jsonl"
STATE = HERMES / "logs" / ".last_notified_firing_ts"
HOME_BIN = Path(os.environ.get("HOME", "~")) / ".local" / "bin"


def main() -> int:
    if not FIRINGS.exists():
        return 0
    last_ts = STATE.read_text().strip() if STATE.exists() else ""

    # Find firings newer than last_ts
    new_firings = []
    newest_ts = last_ts
    with open(FIRINGS) as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if last_ts and ts <= last_ts:
                    continue
                # Only organic (skip tests/probes)
                ctx = e.get("context", "").lower()
                if "test" in ctx or "probe" in ctx:
                    continue
                new_firings.append(e)
                if ts > newest_ts:
                    newest_ts = ts
            except Exception:
                continue

    if not new_firings:
        return 0

    # Group by policy_id, take top 5 by match_score
    by_policy = {}
    for f in new_firings:
        pid = f.get("policy_id", "?")
        by_policy.setdefault(pid, []).append(f)
    ranked = sorted(
        by_policy.items(),
        key=lambda kv: max(x.get("match_score", 0) for x in kv[1]),
        reverse=True,
    )[:5]

    lines = [
        f"⚠️ *Otto — {len(new_firings)} new policy firing{'s' if len(new_firings) != 1 else ''}*",
        "",
    ]
    for pid, evs in ranked:
        score = max(e.get("match_score", 0) for e in evs)
        ctx = evs[0].get("context", "")[:40]
        lines.append(f"• `{pid}` (×{len(evs)}, score {score:.2f})")
        lines.append(f"  _{ctx}_")
    lines.append("")
    lines.append(f"_Total organic: {len(new_firings)}_")

    body = "\n".join(lines)

    # Send
    try:
        r = subprocess.run(
            [str(HOME_BIN / "hermes"), "send", "--to", "telegram"],
            input=body.encode(),
            capture_output=True, timeout=15,
        )
        out = r.stdout.decode().strip() if r.stdout else ""
        if r.returncode == 0:
            print(f"[notify] {len(new_firings)} firings sent: {out}")
            STATE.write_text(newest_ts)
            return 0
        else:
            err = r.stderr.decode().strip()[:200] if r.stderr else ""
            print(f"[notify] FAILED (exit {r.returncode}): {err}", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"[notify] error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
