#!/usr/bin/env python3
"""estate_alert — gateway-INDEPENDENT operator alerting.

The estate's normal alert path goes through the gateway queue. But the failures we
most need to hear about are exactly when the gateway is DOWN (crash-loop, preflight
failure). So this sends straight to Telegram via urllib, reading the bot token and
operator channel from ~/.hermes/.env — no gateway, no heavy deps, stdlib only.

Built 2026-06-20 after a syntax-broken commit crash-looped the gateway silently.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_ENV = HERMES_HOME / ".env"
_DEBOUNCE = HERMES_HOME / "logs" / ".alert-debounce.json"


def _env(key: str) -> str | None:
    """Read one KEY from ~/.hermes/.env (env var wins), minimal parser, no deps."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        for line in _ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _debounced(key: str, window_s: float) -> bool:
    """True if an alert under `key` fired within window_s (i.e. suppress this one)."""
    if not key:
        return False
    now = time.time()
    try:
        data = json.loads(_DEBOUNCE.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    last = data.get(key, 0)
    if now - last < window_s:
        return True
    data[key] = now
    try:
        _DEBOUNCE.parent.mkdir(parents=True, exist_ok=True)
        _DEBOUNCE.write_text(json.dumps(data))
    except OSError:
        pass
    return False


def send_operator_alert(text: str, *, debounce_key: str | None = None,
                        debounce_s: float = 300.0, dry_run: bool = False) -> bool:
    """Send `text` to the operator's Telegram channel. Returns True if sent.

    Returns False (without raising) on missing creds, debounce suppression, or
    network error — alerting must never crash the caller.
    """
    if debounce_key and _debounced(debounce_key, debounce_s):
        return False
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        if dry_run:
            print(f"[estate_alert] MISSING creds (token={bool(token)} chat={bool(chat)})")
        return False
    if dry_run:
        print(f"[estate_alert] would send to chat {chat[:4]}…: {text[:120]}")
        return True
    payload = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=payload), timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    msg = " ".join(sys.argv[1:]) or "🛰️ estate_alert self-test"
    dry = os.environ.get("ESTATE_ALERT_DRYRUN") == "1"
    ok = send_operator_alert(msg, dry_run=dry)
    print(f"sent={ok} dry_run={dry}")
