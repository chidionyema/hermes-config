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
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_ledger                                        # noqa: E402  (path set above)

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


# Telegram rejects a sendMessage over 4096 characters OUTRIGHT — the whole message, not the
# tail. An alerting path that loses the entire page because one fault line grew is the worst
# way to fail: it is silent, and it is silent exactly when there is a lot to say. Measured
# 2026-08-19: the self-check's estate section alone builds 2767 characters from 11 faults.
#
# This lives in the SENDER, not in any one caller, because every caller has the same ceiling
# and a rule kept private gets reimplemented three times and wrong twice.
TELEGRAM_MAX_CHARS = 4096


def _fit(text: str, limit: int = TELEGRAM_MAX_CHARS) -> str:
    """Trim to Telegram's ceiling on a line boundary, saying how much was dropped."""
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    kept: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        marker = f"\n… {len(lines) - i} more line(s) trimmed; run the command above for all of it"
        if used + len(line) + 1 + len(marker) > limit:
            return "\n".join(kept) + marker
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


# ── The hourly ceiling ────────────────────────────────────────────────────────────────────
#
# Founder, 2026-08-19: the Telegram channel is "too noisy, hard to see anything useful".
# Per-alert debouncing already existed and was doing its job — what it cannot see is the
# TOTAL. Twenty different faults, each firing once and each correctly un-debounced, still
# buries the one message worth reading.
#
# So there is a ceiling on how many alerts an hour may carry. Past it, alerts stop reaching
# the channel and ONE line goes instead, naming the count and the command that shows them
# all. No information is lost: every capped alert is in the ledger, which is the point of
# having a ledger. A cap that silently drops is unacceptable; a cap that says how much it
# dropped is just a summary.
ALERT_HOURLY_CAP = int(os.environ.get("HERMES_ALERT_HOURLY_CAP", "12"))
_CAP_NOTICE_KEY = "__hourly_cap_notice__"


def _alerts_sent_last_hour() -> int:
    """Alerts this sender put in the channel in the last hour. The cap notice counts too:
    it occupies a message slot exactly like an alert does."""
    return sum(1 for r in telegram_ledger.read(3600.0)
               if r.get("outcome") == "sent" and r.get("source") != "test")


def _cap_notice_due() -> bool:
    """One notice per hour, not one per capped alert — otherwise the cap is the noise."""
    return not any(r.get("key") == _CAP_NOTICE_KEY for r in telegram_ledger.read(3600.0))


def _post(token: str, chat: str, text: str) -> bool:
    """The raw send. Kept separate so the cap notice can go out without being capped."""
    payload = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=payload), timeout=10) as r:
        return r.status == 200


def send_operator_alert(text: str, *, debounce_key: str | None = None,
                        debounce_s: float = 300.0, dry_run: bool = False) -> bool:
    """Send `text` to the operator's Telegram channel. Returns True if sent.

    Returns False (without raising) on missing creds, debounce suppression, or
    network error — alerting must never crash the caller.
    """
    source = os.path.basename(sys.argv[0] or "")
    if not source or source == "-":          # stdin script, or an embedded caller
        source = "estate_alert"
    if debounce_key and _debounced(debounce_key, debounce_s):
        # A suppressed alert is recorded too. The debounce is the noise control that
        # already exists; if it never appears in the ledger it reads as doing nothing.
        telegram_ledger.record(source, "suppressed", text, key=debounce_key or "")
        return False
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        if dry_run:
            print(f"[estate_alert] MISSING creds (token={bool(token)} chat={bool(chat)})")
        telegram_ledger.record(source, "no-creds", text, key=debounce_key or "")
        return False
    text = _fit(text)
    if dry_run:
        print(f"[estate_alert] would send to chat {chat[:4]}…: {text[:120]}")
        return True

    if ALERT_HOURLY_CAP > 0 and _alerts_sent_last_hour() >= ALERT_HOURLY_CAP:
        telegram_ledger.record(source, "rate-capped", text, key=debounce_key or "")
        if not _cap_notice_due():
            return False
        notice = (f"🔇 Alert ceiling reached: {ALERT_HOURLY_CAP} in the last hour, so further "
                  f"alerts are being held.\nThey are all recorded. See them with:\n"
                  f"  python3 ~/.hermes/scripts/telegram_noise.py --since 2h")
        try:
            ok = _post(token, chat, notice)
        except Exception as exc:
            print(f"[estate_alert] cap notice failed: {exc!r}", file=sys.stderr)
            return False
        telegram_ledger.record(source, "sent" if ok else "failed", notice, key=_CAP_NOTICE_KEY)
        return False

    try:
        ok = _post(token, chat, text)
        telegram_ledger.record(source, "sent" if ok else "failed", text, key=debounce_key or "")
        return ok
    except Exception as exc:
        # Never raise — but never swallow the reason either. A page that vanishes with no
        # trace cannot be diagnosed, and this is the path that reports everything else.
        print(f"[estate_alert] send failed: {exc!r}", file=sys.stderr)
        telegram_ledger.record(source, "failed", text, key=debounce_key or "")
        return False


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "🛰️ estate_alert self-test"
    dry = os.environ.get("ESTATE_ALERT_DRYRUN") == "1"
    ok = send_operator_alert(msg, dry_run=dry)
    print(f"sent={ok} dry_run={dry}")
