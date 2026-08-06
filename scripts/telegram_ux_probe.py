#!/usr/bin/env python3
"""Daily Telegram UX probe — replace the goal-ping cron with a real watchdog.

For each public-facing panel reachable from /help or operator buttons, render
the panel and check health: text length (Telegram 4096 cap), row count
(Telegram 8-row cap), markdown balance, callback validity.

Output policy:
    exit 0, stdout empty  → healthy AND unchanged → silent (watchdog pattern)
    exit 0, stdout text   → healthy but changed (e.g. panel count) OR issues found → deliver
    exit 1                → probe crashed → alert
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, "/Users/chidionyema/.hermes/hermes-agent")

from typing import Any, List, Tuple  # noqa: E402

from gateway.operator_shell import mdv2  # noqa: E402

DIGEST_FILE = Path.home() / ".hermes/cache/telegram-ux-probe.digest"

# (label, module, function) — public-facing panels reachable from /help or buttons.
PANELS: List[Tuple[str, str, str]] = [
    ("help",     "help_card",     "render_help"),
    ("status",   "status_summary", "render_status_summary"),
    ("run",      "cockpit",       "render_run"),
    ("tune",     "cockpit",       "render_tune"),
    ("inbox",    "inbox",         "render_inbox"),
    ("fleet",    "fleet",         "render_fleet"),
    ("atlas",    "atlas",         "render_atlas"),
    ("find",     "find",          "render_find"),
    ("daemons",  "daemons",       "render_daemons"),
    ("mission",  "mission",       "render_mission_card"),
]


def normalize(result: Any) -> Tuple[str, list]:
    """Panels return (text, rows) or (text, bool, rows) or other tuples.

    Pick the first member as text and find the first list-of-rows member as rows.
    """
    if not isinstance(result, tuple):
        return str(result), []
    text = result[0]
    rows = next(
        (x for x in result
         if isinstance(x, list)
         and all(isinstance(r, (list, tuple)) for r in x)),
        [],
    )
    return text, rows


def probe() -> Tuple[List[str], List[str]]:
    issues: List[str] = []
    deltas: List[str] = []

    for label, mod_name, fn_name in PANELS:
        try:
            mod = __import__(f"gateway.operator_shell.{mod_name}", fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            text, rows = normalize(fn())
            n_chars = len(text)
            n_rows = len(rows)
            n_buttons = sum(len(r) for r in rows)

            if n_chars > 4096:
                issues.append(f"{label}: text {n_chars}c > 4096 limit")
            if n_rows > 8:
                issues.append(f"{label}: {n_rows} button rows (>8 Telegram cap)")
            # Check what Telegram RECEIVES, not what the panel author wrote.
            # Parity on raw text (text.count('_') % 2) flagged `status` red on
            # 2026-08-06 over an EX_CONFIG(78) interpolated into a cron orphan
            # line — but render_panel() literalises that stray marker, and the
            # rendered panel parses clean. Raw panel text is never valid
            # MarkdownV2 by design (mdv2.parse on it raises on the first bare
            # '.'), so validating it directly can only produce false alarms.
            n_ents = -1
            try:
                parsed = mdv2.parse(mdv2.render_panel(text))
                ents = parsed[1] if isinstance(parsed, tuple) else parsed
                n_ents = len(ents)
            except Exception as exc:
                issues.append(
                    f"{label}: MarkdownV2 rejected after render — "
                    f"{type(exc).__name__}: {exc}"
                )

            # Entity count goes in the DIGEST, not in a threshold. A hard rule
            # ("panels must parse") has almost no sensitivity here — render_panel
            # literalises anything it cannot parse, so 4 of 4 deliberately
            # malformed panels passed it on 2026-08-06. What actually regresses
            # is markup silently ceasing to apply, and that always moves this
            # count, so the existing change-detection reports it with no
            # heuristic and no false positives.
            deltas.append(f"{label}={n_chars}c/{n_rows}r/{n_buttons}b/{n_ents}e")
        except Exception as e:
            issues.append(f"{label}: render crashed: {type(e).__name__}: {e}")
            deltas.append(f"{label}=ERR")

    return issues, deltas


def main() -> int:
    DIGEST_FILE.parent.mkdir(parents=True, exist_ok=True)

    issues, deltas = probe()
    digest = hashlib.sha256("|".join(deltas).encode()).hexdigest()[:12]
    prev = DIGEST_FILE.read_text().strip() if DIGEST_FILE.exists() else ""

    if prev == digest and not issues:
        # Healthy AND unchanged → silent.
        return 0

    DIGEST_FILE.write_text(digest)

    if issues:
        print("🔴 UX regressions:")
        for i in issues:
            print(f"  • {i}")
    else:
        print(f"✅ {len(PANELS)} panels healthy ({digest})")
        for d in deltas:
            print(f"  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
