"""Proof that the watchdog can tell a BUSY coordinator from a DEAD one.

THE BUG (measured 2026-08-07, ~/.hermes/logs/estate-watchdog.log):

    14:38:35 coordinator DOWN (pid=42061, last tick 798s ago) — restarting
    14:44:37 coordinator DOWN (pid=42061, last tick 1161s ago) — restarting

pid 42061 last completed a tick at 14:25 and was gone. The daemon had already been
restarted to 78070 and then 79818 — but `estate_watchdog._coordinator_pid()` (:81) reads
the live daemon's pid out of `meta.last_tick`, and `coordinator.run_daemon` wrote that row
ONLY after `tick()` returned. A restarted daemon whose first tick blocks on a long executor
call therefore never stamped its pid, so the watchdog kept reading the dead one, declared
DOWN, and `kickstart -k` SIGKILLed a healthy daemon that was mid-task. Every 300s, forever:
no task lasting longer than one watchdog pass could ever finish.

The watchdog's BUSY branch (:268-274) exists precisely to spare a mid-dispatch daemon, and
`_busy_executor_age`'s own docstring describes this exact scenario — but both sit on the
`co_alive` path, unreachable while liveness itself was misread.

Read-only against the estate: everything runs against a TEMP database. `C.connect`,
`C.check_signed_commit` and `C._reap_orphan_executors` are stubbed, so the production
coordinator.db is never opened and no process is ever signalled.
"""
import importlib.util
import os
import sys
import tempfile

HERMES = os.path.expanduser("~/.hermes")
sys.path.insert(0, os.path.join(HERMES, "scripts"))

spec = importlib.util.spec_from_file_location(
    "coordinator", os.path.join(HERMES, "scripts", "coordinator.py"))
C = importlib.util.module_from_spec(spec)
sys.modules["coordinator"] = C          # estate_watchdog does `import coordinator as C`
spec.loader.exec_module(C)

import estate_watchdog as W  # noqa: E402  (safe: all work is behind `if __name__ == "__main__"`)

failures = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        failures.append(f"{label} :: {detail}")
        if detail:
            print(f"        {detail}")


DEAD_PID = 999_999   # above pid_max on macOS: guaranteed not a live process


def boot_daemon_until_first_tick(conn):
    """Run run_daemon() up to the moment it enters its first tick, and report what the
    watchdog would have seen AT THAT MOMENT — the window the bug lived in."""
    observed = {}

    def fake_tick(_conn, *a, **k):
        # The daemon is now inside its first tick, exactly like a real one blocked on a
        # 900s executor call. This is what the watchdog reads while that is happening.
        observed["pid_on_record"] = W._coordinator_pid(conn)
        observed["row"] = C.get_meta(conn, "last_tick")
        raise KeyboardInterrupt   # run_daemon catches Exception, not BaseException

    orig = (C.connect, C.check_signed_commit, C._reap_orphan_executors, C.tick)
    C.connect = lambda *a, **k: conn
    C.check_signed_commit = lambda *a, **k: True
    C._reap_orphan_executors = lambda *a, **k: 0   # never signal a real process in a test
    C.tick = fake_tick
    try:
        C.run_daemon(interval_s=1)
    except KeyboardInterrupt:
        pass
    finally:
        C.connect, C.check_signed_commit, C._reap_orphan_executors, C.tick = orig
    return observed


tmpdir = tempfile.mkdtemp(prefix="hermes-watchdog-test-")
db = os.path.join(tmpdir, "coordinator.db")
conn = C.connect(db)
C.init_db(conn)

print("=== PROOF 1: a booting daemon stamps its pid BEFORE its first tick ===")
# Reproduce 14:44 exactly: the row still names the previous, dead instance.
C.set_meta(conn, "last_tick", f"{DEAD_PID}|advanced=2 reaped=0")
check("precondition: the record names a dead pid",
      W._coordinator_pid(conn) == DEAD_PID and not W._pid_alive(DEAD_PID))

obs = boot_daemon_until_first_tick(conn)
check("the daemon stamped last_tick before entering tick()", obs.get("row") is not None)
check("the pid on record is THIS live process, not the dead one",
      obs.get("pid_on_record") == os.getpid(),
      f"got {obs.get('pid_on_record')}, live pid is {os.getpid()}, dead was {DEAD_PID}")
check("the watchdog now reads the daemon as ALIVE",
      W._pid_alive(obs.get("pid_on_record") or DEAD_PID))

print()
print("=== PROOF 2: the watchdog's DOWN branch no longer fires on a busy daemon ===")
# Age the tick record past WEDGED_STALE_S while the process stays alive — i.e. a daemon
# that has been inside one tick for over 30 minutes, which is the state that was being
# SIGKILLed. Reproduces the decision, not just the inputs.
conn.execute("UPDATE meta SET updated_at=? WHERE key='last_tick'",
             (__import__("time").time() - (W.WEDGED_STALE_S + 60),))
conn.commit()
cpid = W._coordinator_pid(conn)
hb = C.get_meta(conn, "last_tick")
tick_age = int(__import__("time").time() - hb["updated_at"])
co_alive = cpid is not None and W._pid_alive(cpid)
check("co_alive is True, so the DOWN/kickstart branch is skipped", co_alive is True,
      f"cpid={cpid} tick_age={tick_age}")
check(f"tick_age ({tick_age}s) really is past WEDGED_STALE_S ({W.WEDGED_STALE_S}s)",
      tick_age > W.WEDGED_STALE_S)

# With a fresh per-task executor heartbeat the daemon must be classified BUSY, not wedged.
C.upsert_task(conn, "wd-test-1", title="long executor", status="executing") \
    if hasattr(C, "upsert_task") else conn.execute(
        "INSERT INTO tasks (id,title,status,last_heartbeat_at,created_at) VALUES (?,?,?,?,?)",
        ("wd-test-1", "long executor", "executing",
         __import__("time").time() - 5, __import__("time").time()))
conn.commit()
exec_age = W._busy_executor_age(conn)
check("a fresh executing-task heartbeat is visible to the watchdog",
      exec_age is not None and exec_age <= W.EXECUTOR_FRESH_S, f"exec_age={exec_age}")
check("verdict is BUSY (working), not DOWN and not WEDGED",
      co_alive and exec_age is not None and exec_age <= W.EXECUTOR_FRESH_S)

print()
print("=== PROOF 3: a genuinely dead daemon is still detected ===")
# The fix must not blind the watchdog. A stale record naming a dead pid, with no live
# daemon, must still read as DOWN.
C.set_meta(conn, "last_tick", f"{DEAD_PID}|advanced=0 reaped=0")
cpid_dead = W._coordinator_pid(conn)
check("a dead pid on record still reads as NOT alive",
      not (cpid_dead is not None and W._pid_alive(cpid_dead)),
      f"cpid={cpid_dead}")

print()
conn.close()
if failures:
    print(f"VERDICT: FAIL — {len(failures)} check(s) failed")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("VERDICT: PASS — all checks passed")
