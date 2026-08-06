#!/usr/bin/env python3
"""set-cockpit-menu.py — Otto's chat-scoped BotFather menu (wins over gateway defaults).

WHY a per-chat scope: the gateway registers ~30 built-in commands on every boot using the
broad scopes (Default / AllPrivateChats / AllGroupChats). Telegram scope precedence
(Chat > AllPrivateChats > Default) means this curated menu WINS in the founder's home chat
AND survives gateway restarts. Re-run after any Tier-0 change.

Each verb is handled by otto-inbound (pre_gateway_dispatch) and/or hermes-agent
operator_shell slash handlers — same mission card either way.
"""
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])  # so we can import coordinator
import coordinator as C

# Tier-0 Otto cockpit — ≤12. Order = menu order. Keep names short + CEO-facing.
# Keep in sync with hermes-agent/gateway/operator_shell/menu.py OPERATOR_TELEGRAM_MENU.
# 2026-08-06: "dashboard" takes slot 2 and "sethome" leaves the shortlist. The
# founder typed /dashboard twice and got "unrecognized command" (gateway.log
# 20:30, 20:42) — a web UI you cannot find from your phone does not exist.
# /sethome is still a real command, just a one-time setup one, so it loses the
# menu slot rather than a daily-driver.
#
# Same trade for "projects" -> it takes /fleet's slot. Fleet is 4 hardcoded repos
# (fleet.py:19-22); projects is all 14 in ~/.hermes/projects.json and drills into
# per-project CI / missions / activity. /fleet still WORKS, it just is not one of
# the twelve on the menu.
COCKPIT = [
    ("panel",     "Mission card — verdict, burn, one CTA"),
    ("projects",  "Pick a project — status, CI, missions, activity"),
    ("dashboard", "Open the web dashboard — tappable link"),
    ("status",    "Estate overview — daemons, cron, spend"),
    ("inbox",     "Approvals & blockers waiting on you"),
    ("brief",     "5-line executive sitrep"),
    ("cron",      "Jobs: list · pause · resume · run"),
    ("busy",      "Queue vs interrupt while working"),
    ("notify",    "Quiet hours / notify prefs"),
    ("revert",    "Undo last estate action"),
    ("missions",  "Autopilot mission board"),
    ("help",      "Short Otto cheat sheet"),
]


def _api(token: str, method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    token, chat_id = C.get_telegram_creds()
    if not token or not chat_id:
        print("✖ Missing TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL in ~/.hermes/.env")
        return 1
    try:
        chat_scope = {"type": "chat", "chat_id": int(chat_id)}
    except ValueError:
        chat_scope = {"type": "chat", "chat_id": chat_id}

    commands = [{"command": name, "description": desc} for name, desc in COCKPIT]
    set_res = _api(token, "setMyCommands", {"commands": commands, "scope": chat_scope})
    if not set_res.get("ok"):
        print(f"✖ setMyCommands failed: {set_res}")
        return 1

    # Verify by reading the chat-scoped menu back.
    got = _api(token, "getMyCommands", {"scope": chat_scope})
    names = [c["command"] for c in got.get("result", [])]
    print(f"✔ Otto cockpit menu set — {len(names)} commands:")
    print("  /" + "  /".join(names))
    missing = [n for n, _ in COCKPIT if n not in names]
    if missing:
        print(f"⚠ not confirmed in readback: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
