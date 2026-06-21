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
GATEWAY_HEARTBEAT = os.path.expanduser("~/.hermes/gateway.heartbeat")
LOG = os.path.expanduser("~/.hermes/logs/estate-watchdog.log")
WEDGED_STALE_S = 1800        # heartbeat older than this while proc alive = wedged → alert only
GW_HEARTBEAT_STALE_S = 1200  # gateway event-loop heartbeat (5-min cadence) older than 20 min = wedged
ALERT_DEBOUNCE_S = 1800      # don't re-alert the same issue within this window
RESTART_DEBOUNCE_S = 300     # don't restart the same service more than once per this window
EXECUTOR_FRESH_S = 900       # an 'executing' task with a heartbeat fresher than this = daemon BUSY, not wedged


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


def _gateway_heartbeat_age() -> int | None:
    """Age (s) of the gateway's event-loop heartbeat file, or None if absent/unreadable.

    The gateway writes this every ~5 min from inside its async watcher loop, so a FRESH file
    proves the event loop is turning (Telegram is being serviced) — not merely that the
    process exists. A live pid with a very stale heartbeat = wedged loop.
    """
    try:
        with open(GATEWAY_HEARTBEAT) as fh:
            return int(time.time() - int(fh.read().strip()))
    except Exception:
        return None


def _busy_executor_age(conn) -> int | None:
    """Load-immune busy check (one DB read): age of the freshest 'executing' task heartbeat.

    The daemon stamps last_tick only at TICK BOUNDARIES, but a single tick dispatches
    claude executors that each run up to the per-task timeout (several per tick) — so the
    tick heartbeat looks stale for tens of minutes while the daemon is genuinely working.
    An 'executing' task whose last_heartbeat_at is fresh proves work is in flight, so the
    daemon is BUSY, not wedged. Returns the heartbeat age in seconds, or None if no task
    is actively executing.
    """
    try:
        row = conn.execute(
            "SELECT last_heartbeat_at FROM tasks WHERE status='executing' "
            "AND last_heartbeat_at IS NOT NULL ORDER BY last_heartbeat_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    try:
        return int(time.time() - float(row[0]))
    except (TypeError, ValueError):
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
        if ok:
            _log(f"kickstart {label}: ok")
        else:
            # launchctl sometimes fails with empty stderr (e.g. an in-flight restart);
            # fall back to stdout / returncode so a FAIL is never a blind, undiagnosable line.
            diag = (r.stderr.strip() or r.stdout.strip() or f"rc={r.returncode}")[:120]
            _log(f"kickstart {label}: FAIL {diag}")
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
            # Re-confirm before declaring DOWN. A legitimate `gateway run --replace` briefly
            # removes/rewrites gateway.pid, so a single read can be a false DOWN and would race
            # the in-flight restart (root cause of the 2026-06-21 'kickstart … FAIL' empty-stderr).
            time.sleep(2)
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
            # Process is alive — but is its EVENT LOOP turning? A wedged loop (alive pid, frozen
            # heartbeat) means Telegram is silently dead. Alert only — never auto-kill the live
            # lifeline on a soft signal; the founder decides. No heartbeat file yet = just-restarted
            # gateway that hasn't written its first (≤6 min after boot), so don't cry wolf.
            gw_hb_age = _gateway_heartbeat_age()
            if gw_hb_age is not None and gw_hb_age > GW_HEARTBEAT_STALE_S:
                _log(f"gateway WEDGED (alive pid={gpid}, event-loop heartbeat {gw_hb_age}s stale) — alert only")
                _alert(conn, "gateway_wedged",
                       f"🟡 *Gateway looks wedged* — process is up but its event loop hasn't ticked "
                       f"for {gw_hb_age // 60} min, so Telegram may be silently dead. Not auto-killing "
                       f"the lifeline — reply *Otto restart gateway* if it's unresponsive.")
            else:
                _log(f"gateway ok (pid={gpid}, heartbeat {gw_hb_age if gw_hb_age is not None else 'pending'}s)")

        # ── coordinator ────────────────────────────────────────────────────────
        cpid = _coordinator_pid(conn)
        hb = C.get_meta(conn, "last_tick")
        tick_age = int(time.time() - hb["updated_at"]) if hb else None
        co_alive = cpid is not None and _pid_alive(cpid)
        if not co_alive:
            # Re-confirm: same transient-restart race as the gateway above (the daemon rewrites
            # last_tick on boot), so don't kickstart on a single missed read.
            time.sleep(2)
            cpid = _coordinator_pid(conn)
            co_alive = cpid is not None and _pid_alive(cpid)
        if not co_alive:
            _log(f"coordinator DOWN (pid={cpid}, last tick {tick_age}s ago) — restarting")
            if not _debounced(conn, "watchdog_restart:coordinator", RESTART_DEBOUNCE_S):
                if _kickstart("ai.hermes.coordinator"):
                    _alert(conn, "coordinator",
                           "🟠 *Coordinator daemon was down — I restarted it.* Task processing "
                           "resumes. Pull *Otto health* to confirm.")
        elif tick_age is not None and tick_age > WEDGED_STALE_S:
            exec_age = _busy_executor_age(conn)
            if exec_age is not None and exec_age <= EXECUTOR_FRESH_S:
                # Tick heartbeat is stale only because the daemon is mid-dispatch on a long
                # executor (fresh per-task heartbeat). Busy ≠ wedged → log, never alert.
                _log(f"coordinator BUSY (alive pid={cpid}, tick {tick_age}s stale but executor "
                     f"heartbeat {exec_age}s fresh) — working, not wedged")
            else:
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
