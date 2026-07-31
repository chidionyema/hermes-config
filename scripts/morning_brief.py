#!/usr/bin/env python3
"""morning_brief.py — deterministic CEO brief (no LLM).

Wired as a no_agent cron script. Uses operator_shell executive brief when
importable; falls back to coordinator.operator_brief + product_autonomy.
"""
from __future__ import annotations

import os
import sys

HERMES = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
sys.path.insert(0, os.path.join(HERMES, "scripts"))
sys.path.insert(0, os.path.join(HERMES, "hermes-agent"))


def _render() -> tuple[str, list | None, bool]:
    try:
        from gateway.operator_shell.voice_brief import render_executive_brief
        text, buttons = render_executive_brief()
        import coordinator as C
        return text, buttons, C.estate_paused()
    except Exception:
        pass
    import coordinator as C
    conn = C.connect()
    try:
        body = C.operator_brief(conn)
        m = C.autonomy_ratio(conn, 7 * 86400)
        prod = m.get("product_autonomy_ratio", m.get("autonomy_ratio", 0))
        head = (
            f"🎙 *Morning brief*\n"
            f"📈 Product autonomy (7d): *{prod*100:.0f}%*\n"
            f"📦 Product done: {m.get('product_auto_resolved', '?')} · "
            f"asks: {m.get('product_escalated', '?')}\n\n"
        )
        return head + body, None, C.estate_paused()
    finally:
        conn.close()


def main() -> int:
    text, buttons, paused = _render()
    import coordinator as C
    ok = C.send_estate_panel(text, paused, buttons=buttons)
    if not ok:
        # last resort plain send
        token, chat = C.get_telegram_creds()
        if not token or not chat:
            print(text)
            return 1
        import json, urllib.request
        payload = {"chat_id": chat, "text": text[:4000]}
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
    print("sent" if ok else "send_failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
