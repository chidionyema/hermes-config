#!/usr/bin/env python3
"""estate_watchdog.py — independent supervisor so Telegram is never silently down.

The founder runs the estate from his phone; "the bot is down" must self-heal. launchd
already restarts a CRASHED gateway, and the coordinator watches the gateway — but if the
COORDINATOR itself is down, nothing watches anything (recon gap #4). This watchdog is the
outer ring: a tiny launchd job (every 5 min) that depends on NEITHER daemon.

It does load-immune pid checks (os.kill(pid,0), not `ps|grep` which hangs under high load)
and:
  • gateway process gone      → `launchctl kickstart -k` it + DM the founder
  • coordinator process gone  → kickstart it + DM the founder
  • coordinator alive but its heartbeat is very stale (wedged, not crashed) → DM only,
    never kill a possibly-busy daemon.

Alerts + restarts are debounced (state in coordinator.db meta) so a flapping service can't
spam the phone or restart-storm. Healthy runs are silent (logged only). Never raises.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import coordinator as C

UID = os.getuid()
GATEWAY_PID_FILE = os.path.expanduser("~/.hermes/gateway.pid")
LOG = os.path.expanduser("~/.hermes/logs/estate-watchdog.log")
WEDGED_STALE_S = 1800        # heartbeat older than this while proc alive = wedged → alert only
ALERT_DEBOUNCE_S = 1800      # don't re-alert the same issue within this window
RESTART_DEBOUNCE_S = 300     # don't restart the same service more than once per this window


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n"
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(line)
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    """Load-immune liveness: signal 0 probes existence without touching the process."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # exists but owned by another uid → alive


def _gateway_pid() -> int | None:
    try:
        with open(GATEWAY_PID_FILE) as fh:
            return int(json.load(fh).get("pid"))
    except Exception:
        return None


def _coordinator_pid(conn) -> int | None:
    """The daemon stamps its pid into meta last_tick as 'pid|summary'."""
    hb = C.get_meta(conn, "last_tick")
    if not hb or not hb["value"]:
        return None
    try:
        return int(str(hb["value"]).split("|", 1)[0])
    except (ValueError, IndexError):
        return None


def _debounced(conn, key: str, window_s: float) -> bool:
    """True if `key` fired within window_s (→ skip). Otherwise stamp now and return False."""
    row = C.get_meta(conn, key)
    now = time.time()
    if row and (now - row["updated_at"]) < window_s:
        return True
    C.set_meta(conn, key, str(int(now)))
    return False


def _kickstart(label: str) -> bool:
    try:
        r = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{UID}/{label}"],
                           capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        _log(f"kickstart {label}: {'ok' if ok else 'FAIL '+r.stderr.strip()[:120]}")
        return ok
    except Exception as e:
        _log(f"kickstart {label} exception: {e}")
        return False


def _alert(conn, key: str, msg: str) -> None:
    if _debounced(conn, f"watchdog_alert:{key}", ALERT_DEBOUNCE_S):
        _log(f"alert suppressed (debounced): {key}")
        return
    C.telegram_notify(msg)
    _log(f"alerted: {key}")


def main() -> int:
    try:
        conn = C.connect()
    except Exception as e:
        _log(f"cannot open coordinator.db: {e}")
        return 0  # never fail loudly; try again next tick
    try:
        # ── gateway ────────────────────────────────────────────────────────────
        gpid = _gateway_pid()
        gw_alive = gpid is not None and _pid_alive(gpid)
        if not gw_alive:
            _log(f"gateway DOWN (pid={gpid}) — restarting")
            if not _debounced(conn, "watchdog_restart:gateway", RESTART_DEBOUNCE_S):
                if _kickstart("ai.hermes.gateway"):
                    _alert(conn, "gateway",
                           "🟠 *Gateway was down — I restarted it.* Telegram should be back. "
                           "If this repeats, the box is likely overloaded (see Otto health).")
        else:
            _log(f"gateway ok (pid={gpid})")

        # ── coordinator ────────────────────────────────────────────────────────
        cpid = _coordinator_pid(conn)
        hb = C.get_meta(conn, "last_tick")
        tick_age = int(time.time() - hb["updated_at"]) if hb else None
        co_alive = cpid is not None and _pid_alive(cpid)
        if not co_alive:
            _log(f"coordinator DOWN (pid={cpid}, last tick {tick_age}s ago) — restarting")
            if not _debounced(conn, "watchdog_restart:coordinator", RESTART_DEBOUNCE_S):
                if _kickstart("ai.hermes.coordinator"):
                    _alert(conn, "coordinator",
                           "🟠 *Coordinator daemon was down — I restarted it.* Task processing "
                           "resumes. Pull *Otto health* to confirm.")
        elif tick_age is not None and tick_age > WEDGED_STALE_S:
            _log(f"coordinator WEDGED (alive pid={cpid}, last tick {tick_age}s ago) — alert only")
            _alert(conn, "coordinator_wedged",
                   f"🟡 *Coordinator looks wedged* — alive but no heartbeat for {tick_age // 60} min. "
                   f"Not force-killing (it may be on a long task). Check *Otto health*.")
        else:
            _log(f"coordinator ok (pid={cpid}, last tick {tick_age}s ago)")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
