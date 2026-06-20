#!/usr/bin/env python3
"""gateway_preflight — validate edit-prone gateway modules BEFORE going live.

THE BUG THIS KILLS: a syntax-broken gateway/platforms/telegram.py was committed and
launchd crash-looped the gateway silently for minutes — nobody was told. This wrapper
imports the edit-prone adapter modules first. If any fails to import, it does NOT
launch the broken code; it alerts the operator (gateway-independent, via Telegram)
with the actual error and exits, so launchd backs off (ThrottleInterval) instead of
thrashing, and the OLD code keeps running until the bad import is fixed.

The launchd plist runs THIS instead of `python -m hermes_cli.main gateway run`.
On success it execs the real gateway, so there is zero added runtime overhead.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

# Edit-prone modules whose breakage would take the gateway down on import.
CRITICAL_MODULES = ("gateway.platforms.telegram",)

# Default gateway launch command tail (overridable via argv after the script name).
DEFAULT_TAIL = ["-m", "hermes_cli.main", "gateway", "run", "--replace"]


def _preflight() -> tuple[bool, str]:
    import importlib
    for mod in CRITICAL_MODULES:
        try:
            importlib.import_module(mod)
        except BaseException:  # SyntaxError is not an Exception subclass at import time
            tb = traceback.format_exc()
            last = tb.strip().splitlines()[-1] if tb.strip() else "unknown import error"
            return False, f"{mod}: {last}\n\n{tb[-1200:]}"
    return True, ""


def main() -> int:
    ok, err = _preflight()
    if ok:
        tail = sys.argv[1:] or DEFAULT_TAIL
        # Replace this process with the real gateway — no overhead, same pid semantics.
        os.execv(sys.executable, [sys.executable, *tail])
        return 0  # unreachable on success

    # --- preflight FAILED: alert, do not launch broken code, back off ---
    sys.stderr.write(f"[gateway_preflight] ABORT — import failed:\n{err}\n")
    sys.stderr.flush()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import estate_alert
        head = err.splitlines()[0] if err else "import error"
        estate_alert.send_operator_alert(
            "🚨 Gateway preflight FAILED — NOT starting (old code stays up).\n"
            f"{head}\n\nFix the import error, then the gateway will start on next launchd cycle.",
            debounce_key="gateway_preflight_fail", debounce_s=600)
    except Exception as e:
        sys.stderr.write(f"[gateway_preflight] alert send failed: {e}\n")
    # Back off so launchd (ThrottleInterval) does not hammer-restart.
    time.sleep(20)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
