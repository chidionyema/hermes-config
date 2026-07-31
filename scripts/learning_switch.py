#!/usr/bin/env python3
"""learning_switch — ONE honest kill switch for all self-improvement loops.

Semantics (canonical — do not invert elsewhere):
  ~/.hermes/meta/OFF_SWITCH  PRESENT  → ARMED   (RSI / meta-improver / idle-learning may run)
  ~/.hermes/meta/OFF_SWITCH  ABSENT   → DISARMED (all automatic learning must no-op / exit non-zero)

Telegram: "Otto arm self-improvement" creates the file; "disarm" removes it.
"""
from __future__ import annotations

import os
import sys

HERMES = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
OFF_SWITCH = os.path.join(HERMES, "meta", "OFF_SWITCH")


def learning_armed() -> bool:
    return os.path.isfile(OFF_SWITCH)


def require_armed(stream=None) -> bool:
    """Print status; return True if armed. Callers that must fail-closed use exit code 1."""
    out = stream or sys.stderr
    if learning_armed():
        print("✅ Learning ARMED (OFF_SWITCH present)", file=out)
        return True
    print("⛔ OFF_SWITCH absent — self-improvement DISARMED; refusing to mutate.", file=out)
    return False


def arm(reason: str = "armed via learning_switch") -> None:
    os.makedirs(os.path.dirname(OFF_SWITCH), exist_ok=True)
    with open(OFF_SWITCH, "w") as fh:
        fh.write(reason.rstrip() + "\n")


def disarm() -> bool:
    if os.path.isfile(OFF_SWITCH):
        os.remove(OFF_SWITCH)
        return True
    return False


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "arm":
        arm("armed via CLI")
        print("ARMED")
        raise SystemExit(0)
    if cmd == "disarm":
        disarm()
        print("DISARMED")
        raise SystemExit(0)
    print("ARMED" if learning_armed() else "DISARMED")
    raise SystemExit(0 if learning_armed() else 1)
