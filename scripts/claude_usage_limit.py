#!/usr/bin/env python3
"""A shared, cross-process record of when the Claude subscription's usage wall lifts.

THE PROBLEM THIS SOLVES
Otto's coordinator and Prospector's scheduler are two always-on daemons (both
`KeepAlive=1`) drawing on ONE Claude subscription. `provider_capacity` is 35.2% of
Otto's failures in the 14-day window. A mutex does NOT help: serialising two consumers
of a token budget does not reduce total tokens. What actually costs money is that
neither daemon can SEE the wall — `_is_session_limit_text` (`coordinator.py:1055`)
returns a bool, so the CLI's own `Claude AI usage limit reached|<reset-epoch>` is
detected and the reset time discarded. Both processes then keep launching `claude -p`
into a wall they know is there, and each attempt costs a process spawn, a task slot,
and a fabricated narration.

THE CONTRACT IS THE FILE, NOT THIS MODULE
The marker is plain JSON at ~/.hermes/state/claude_usage_limit.json:

    {"reset_at": <epoch>, "observed_at": <epoch>, "observed_by": "<name>",
     "source": "<first 200 chars of the text that proved it>"}

Any process in the estate may read it without importing anything from ~/.hermes —
Prospector reads the path directly. That keeps the two codebases decoupled: this file
is a fact about the shared account, not a library either side depends on.

Writes are atomic (tmp + os.replace) because two daemons may observe the same wall in
the same second. Later reset wins: a wall never gets shorter by being re-observed.
"""
import json
import os
import re
import tempfile
import time

MARKER = os.path.expanduser("~/.hermes/state/claude_usage_limit.json")

# The CLI emits an epoch after a pipe: "Claude AI usage limit reached|1786123456".
_RESET_RE = re.compile(r"usage limit reached\s*\|\s*(\d{9,13})", re.I)

# When the wall is real but carries no timestamp, block for a short cooldown only.
# Guessing hours would stall a daemon that could have resumed; the point is to break a
# hot retry loop, not to impose an outage of our own invention.
DEFAULT_COOLDOWN_S = float(os.environ.get("CLAUDE_LIMIT_COOLDOWN_S", "900"))


def parse_reset(text):
    """The reset epoch carried by the CLI's own message, or None.

    Handles both seconds and milliseconds — the field has appeared as both, and a
    millisecond value read as seconds lands in the year 58000 and blocks forever.
    """
    m = _RESET_RE.search(text or "")
    if not m:
        return None
    val = float(m.group(1))
    if val > 1e11:          # milliseconds
        val /= 1000.0
    return val


def read(now=None):
    """The live marker as a dict, or None when absent, unreadable or expired."""
    ref = time.time() if now is None else now
    try:
        with open(MARKER, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        if float(data.get("reset_at", 0)) <= ref:
            return None
    except (TypeError, ValueError):
        return None
    return data


def blocked_until(now=None):
    """Epoch the wall lifts, or 0.0 when not currently blocked."""
    data = read(now=now)
    return float(data["reset_at"]) if data else 0.0


def is_blocked(now=None):
    return blocked_until(now=now) > 0.0


def observe(text, observed_by, now=None, cooldown_s=None):
    """Record a usage wall proved by `text`. Returns the reset epoch, or None if the
    text does not actually show a limit."""
    ref = time.time() if now is None else now
    low = (text or "").lower()
    if not any(t in low for t in ("usage limit", "session limit", "rate limit",
                                  "quota exceeded")):
        return None
    reset = parse_reset(text)
    if reset is None or reset <= ref:
        reset = ref + (DEFAULT_COOLDOWN_S if cooldown_s is None else cooldown_s)

    # A wall never gets SHORTER by being observed again — two daemons hitting it in the
    # same second must not race each other into an early resume.
    existing = read(now=ref)
    if existing and float(existing.get("reset_at", 0)) > reset:
        return float(existing["reset_at"])

    payload = {"reset_at": reset, "observed_at": ref, "observed_by": observed_by,
               "source": (text or "")[:200]}
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(MARKER), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, MARKER)     # atomic; a reader never sees a half-written marker
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return reset


if __name__ == "__main__":
    d = read()
    if d:
        print(f"BLOCKED until {time.strftime('%F %T', time.localtime(d['reset_at']))} "
              f"({(d['reset_at'] - time.time()) / 60:.1f} min) — observed by "
              f"{d.get('observed_by')}")
    else:
        print("clear — no live usage wall recorded")
