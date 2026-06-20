#!/usr/bin/env python3
"""set-cockpit-menu.py — give the operator a curated, tappable Otto cockpit in Telegram.

WHY a per-chat scope: the gateway registers ~30 built-in commands on every boot using the
broad scopes (Default / AllPrivateChats / AllGroupChats), and 105 more are hidden behind
Telegram's menu cap. Rather than fight that cap with package edits, we set a BotCommandScopeChat
menu for the founder's home chat. Telegram scope precedence (Chat > AllPrivateChats > Default)
means this curated menu WINS in that chat AND survives gateway restarts (the gateway never
touches the chat scope). Re-run this script any time to update the cockpit.

Each verb is already handled by the otto-inbound plugin's pre_gateway_dispatch hook, so tapping
a command Just Works (no new handlers needed). Secrets are read from ~/.hermes/.env and never
printed.
"""
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])  # so we can import coordinator
import coordinator as C

# Curated cockpit — the handful an operator actually uses. Telegram rules: lowercase name,
# 1-32 chars [a-z0-9_], description <=256 chars. Order here is the order shown in the menu.
COCKPIT = [
    ("health",    "Am I alive + is everything OK"),
    ("brief",     "The rundown right now"),
    ("backlog",   "What I'm working on"),
    ("decisions", "What's waiting on you"),
    ("reflect",   "How I'm improving — ideas + receipts"),
    ("missions",  "Project autopilot board"),
    ("chores",    "Internal maintenance I'm handling"),
    ("approve",   "Release a paused task — then add the id"),
    ("help",      "Show the full Otto menu"),
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
    print(f"✔ Cockpit menu set for chat scope — {len(names)} tappable commands:")
    print("  /" + "  /".join(names))
    missing = [n for n, _ in COCKPIT if n not in names]
    if missing:
        print(f"⚠ not confirmed in readback: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
