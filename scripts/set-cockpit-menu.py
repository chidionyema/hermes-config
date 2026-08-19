#!/usr/bin/env python3
"""set-cockpit-menu.py — install the operator menu, chat-scoped so it wins.

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

# The names come from hermes-agent/gateway/operator_shell/menu.py. They are NOT
# copied here.
#
# Why: this script sets a CHAT-SCOPED menu, and Telegram's scope precedence
# (Chat > AllPrivateChats > Default) means whatever it writes BEATS the menu the
# gateway registers at boot. It carried its own 12-name list that was last edited
# 2026-08-06, so running it on 2026-08-19 would have silently removed the five
# commands added since — including `summary`, which the founder asked for by name
# that morning. A second copy of a list is a list that will be wrong.
#
# Descriptions still live here because Telegram wants a one-liner per command and
# the gateway builds those from its own registry at runtime, which this one-shot
# has no gateway to ask. The names are the part that drifts, and they no longer
# can: a name in the menu with no description below is a hard failure, not a
# missing row. tests/test_cockpit_menu_matches_the_gateway.py is what fails.
DESCRIPTIONS = {
    "panel": "Mission card \u2014 verdict, burn, one CTA",
    "projects": "Pick a project \u2014 status, CI, missions, activity",
    "dashboard": "Open the web dashboard \u2014 tappable link",
    "status": "Estate overview \u2014 daemons, cron, spend",
    "inbox": "Approvals & blockers waiting on you",
    "brief": "5-line executive sitrep",
    "cron": "Jobs: list \u00b7 pause \u00b7 resume \u00b7 run",
    "busy": "Queue vs interrupt while working",
    "notify": "Quiet hours / notify prefs",
    "revert": "Undo last estate action",
    "missions": "Autopilot mission board",
    "summary": "Numerology, gematria and anagram card for any text",
    "agent_model": "Which brain the agent runs on",
    "model": "Switch the model for this chat only",
    "code": "Open a coding session on a repo",
    "help": "Short Otto cheat sheet",
}


def cockpit() -> list[tuple[str, str]]:
    """The menu to install: the gateway's own order, with descriptions."""
    import sys as _sys
    _sys.path.insert(0, str(__import__("pathlib").Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.menu import OPERATOR_TELEGRAM_MENU

    missing = [n for n in OPERATOR_TELEGRAM_MENU if n not in DESCRIPTIONS]
    if missing:
        raise SystemExit(
            "set-cockpit-menu: no description for " + ", ".join(missing) + ".\n"
            "Add one to DESCRIPTIONS. Installing a menu without them would drop "
            "these commands from the founder's chat."
        )
    return [(n, DESCRIPTIONS[n]) for n in OPERATOR_TELEGRAM_MENU]


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

    menu = cockpit()
    commands = [{"command": name, "description": desc} for name, desc in menu]
    set_res = _api(token, "setMyCommands", {"commands": commands, "scope": chat_scope})
    if not set_res.get("ok"):
        print(f"✖ setMyCommands failed: {set_res}")
        return 1

    # Verify by reading the chat-scoped menu back.
    got = _api(token, "getMyCommands", {"scope": chat_scope})
    names = [c["command"] for c in got.get("result", [])]
    print(f"✔ Otto cockpit menu set — {len(names)} commands:")
    print("  /" + "  /".join(names))
    missing = [n for n, _ in menu if n not in names]
    if missing:
        print(f"⚠ not confirmed in readback: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
