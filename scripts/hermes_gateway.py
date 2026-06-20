#!/usr/bin/env python3
"""hermes_gateway.gateway_liveness — load-immune gateway liveness.

THE BUG THIS KILLS (snapshot-as-proof, sensor half)
  Both the watchdog and the alert-resolver decided "is the gateway up?" with
  `ps aux | grep 'python.*gateway'`. At load 140 that pipeline takes >5s, hits its
  timeout, returns "(timeout)", fails .isdigit(), and a gateway that has been alive
  for 20h is reported DOWN. That false-DOWN is the mechanism behind every
  GATEWAY_RESTART_LOOP false alarm.

THE FIX
  Read the PID from ~/.hermes/gateway.pid and probe it with os.kill(pid, 0):
  O(1), ~0.7ms, no shell, completely immune to system load.

  THREE-STATE — a read failure is UNKNOWN, never DOWN:
    True   -> the PID is alive (gateway up)
    False  -> the PID file is present and the process is genuinely gone (real down)
    None   -> the PID file is missing/unreadable (UNKNOWN — we must NOT assert DOWN
              on our own inability to read, or load noise re-enters through the back door)

  HERMES_FAKE_GATEWAY=up|down is preserved as the deterministic test seam the probes use.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))


def gateway_liveness(home: Path = None):
    """Return True (alive) / False (genuinely dead) / None (UNKNOWN). Load-immune."""
    fake = os.environ.get("HERMES_FAKE_GATEWAY")
    if fake is not None:
        return fake.lower() == "up"

    pidfile = (home or HERMES_HOME) / "gateway.pid"
    try:
        pid = int(json.loads(pidfile.read_text())["pid"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None  # cannot read identity -> UNKNOWN, never DOWN

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False           # PID known, process gone -> a REAL down
    except PermissionError:
        return True            # alive but owned by another uid
    except OSError:
        return None            # any other probe failure -> UNKNOWN


def liveness_state(home: Path = None) -> str:
    """'up' | 'down' | 'unknown' — the string form used in the daemon_history window."""
    live = gateway_liveness(home)
    return "up" if live is True else ("down" if live is False else "unknown")


if __name__ == "__main__":
    print(f"gateway_liveness={gateway_liveness()} state={liveness_state()}")
