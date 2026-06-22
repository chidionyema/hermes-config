"""§7 Phase 1 sabotage test for coordinator.run_bounded(). Run: python3 test_reaper.py

A stalled executor spawns grandchildren (model workers, pytest, ...). subprocess.run's
timeout SIGKILLs only the direct child, orphaning the grandchild. run_bounded() must kill
the whole process group. We prove BOTH directions:
  - run_bounded   -> grandchild is DEAD after timeout   (the fix works)
  - subprocess.run-> grandchild SURVIVES (the leak)      (teeth: proves the test is real)
"""
import os, sys, time, signal, subprocess, tempfile
import coordinator as C

# parent writes its grandchild's PID to argv[1], then both sleep 600s
PARENT = (
    "import subprocess,sys,time;"
    "p=subprocess.Popen(['sleep','600']);"
    "open(sys.argv[1],'w').write(str(p.pid));"
    "time.sleep(600)"
)


def grandchild_pid(pidfile):
    for _ in range(50):
        try:
            txt = open(pidfile).read().strip()
            if txt:
                return int(txt)
        except Exception:
            pass
        time.sleep(0.05)
    raise AssertionError("grandchild pid never written")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_run_bounded_kills_the_group():
    pf = tempfile.mktemp()
    t0 = time.time()
    try:
        C.run_bounded([sys.executable, "-c", PARENT, pf], timeout=1, capture_output=True, text=True)
        raise AssertionError("expected TimeoutExpired")
    except subprocess.TimeoutExpired:
        pass
    elapsed = time.time() - t0
    gpid = grandchild_pid(pf)
    time.sleep(0.3)  # let the SIGKILL propagate
    assert not alive(gpid), f"LEAK: grandchild {gpid} survived run_bounded"
    assert elapsed < 10, f"took {elapsed:.1f}s to clear (should be ~1s)"
    os.path.exists(pf) and os.unlink(pf)
    print(f"PASS  run_bounded: grandchild reaped with the group, cleared in {elapsed:.1f}s")


def test_teeth_plain_run_leaks_grandchild():
    pf = tempfile.mktemp()
    try:
        subprocess.run([sys.executable, "-c", PARENT, pf], timeout=1, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        pass
    gpid = grandchild_pid(pf)
    time.sleep(0.3)
    leaked = alive(gpid)
    if leaked:                       # expected: clean up the orphan we just proved leaks
        try: os.kill(gpid, signal.SIGKILL)
        except Exception: pass
    os.path.exists(pf) and os.unlink(pf)
    assert leaked, "TEETH FAILURE: plain subprocess.run did NOT leak — test proves nothing"
    print("PASS  teeth: plain subprocess.run orphans the grandchild (the leak run_bounded fixes)")


if __name__ == "__main__":
    try:
        test_run_bounded_kills_the_group()
        test_teeth_plain_run_leaks_grandchild()
    except AssertionError as e:
        print("FAIL ", e); sys.exit(1)
    print("ALL GREEN")
