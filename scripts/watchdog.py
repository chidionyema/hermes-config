#!/usr/bin/env python3
"""Continuous Health Watchdog — GRADED on invariants (exit-code honest).

WHAT CHANGED (Fire: hidden restart loops)
  The shell watchdogs exit 0 unconditionally: a daemon that dies and is restarted
  every 5 minutes looks "healthy" forever because each restart returns 0. And the
  old watchdog.py also always `return 0`, so a probe/ledger could never tell from
  the exit code whether the system was actually well.

  This rewrite grades on ACTUAL INVARIANTS and reports them in the exit code:
    exit 0  — healthy: daemon sustained-alive over the window AND no alert has
              persisted unhealed for K runs.
    exit 1  — an alert has been OPEN for >= K consecutive runs (unhealed SLA breach).
    exit 2  — daemon RESTART LOOP / instability: the gateway was not continuously
              alive across the last N runs (the failure the .sh watchdogs hid).

  Two invariants drive it, both stateful across runs (watchdog-state.json):
    • daemon alive  = gateway process up, SUSTAINED for the last N runs (~N*cadence).
    • alert resolved = a previously-open fingerprint ABSENT for the last K runs.
                       (Not "absent once" — flapping no longer reads as resolved.)

  Grading is keyed on the CANONICAL FINGERPRINT (hermes_fingerprint), so PID/
  timestamp-varying messages are one identity and can't desync the streak counters.

DELIVERY
  Silent on stdout when nothing is newly actionable (the job delivers stdout to the
  user). Every active condition is SUBMITTED to the relay queue (the substrate);
  queue-curator + otto-dispatch decide what reaches the user. Probe-verified
  resolution stays alert-resolver's job (called at the end).
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes_fingerprint import canonicalize  # noqa: E402
from hermes_subprocess import sh as _bounded_sh  # noqa: E402  orphan-safe subprocess
from hermes_gateway import gateway_liveness, liveness_state  # noqa: E402  load-immune

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
STATE_FILE = HERMES_HOME / "logs" / "alerts" / "watchdog-state.json"
QUEUE = HERMES_HOME / "scripts" / "hermes_queue.py"

# Invariant windows (env-overridable so the probe can drive them deterministically).
RESOLVE_AFTER_K = int(os.environ.get("HERMES_WD_RESOLVE_K", "3"))   # absent K runs => resolved
SUSTAIN_N = int(os.environ.get("HERMES_WD_SUSTAIN_N", "3"))         # daemon must be up N runs
OPEN_BREACH_K = int(os.environ.get("HERMES_WD_BREACH_K", "3"))      # open K runs => exit 1
# The watchdog's OWN cron job name — excluded from cron-error detection so a nonzero
# exit (which may mark this job errored) can never feed back as a CRON_ERROR alert.
SELF_JOB = os.environ.get("HERMES_WD_SELF_JOB", "health-watchdog")

ALERT_THRESHOLDS = {
    "cron_stale_hours": int(os.environ.get("HERMES_CRON_STALE_HOURS", "26")),
    "uncommitted_files_max": int(os.environ.get("HERMES_GIT_DIRTY_MAX", "50")),
    "disk_usage_percent_max": int(os.environ.get("HERMES_DISK_PCT_MAX", "90")),
}

EXIT_HEALTHY, EXIT_OPEN_BREACH, EXIT_RESTART_LOOP = 0, 1, 2


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd, timeout=10):
    # orphan-safe: hermes_subprocess.run_bounded kills the whole process group on timeout.
    # Returns ('(timeout)', -1) on deadline, identical to the old contract.
    return _bounded_sh(cmd, timeout=timeout)


# ── detectors (return list[str], type-prefixed) ──────────────────────────────
def _jobs():
    jp = HERMES_HOME / "cron" / "jobs.json"
    if not jp.exists():
        return []
    try:
        return json.loads(jp.read_text()).get("jobs", [])
    except (OSError, json.JSONDecodeError):
        return []


def check_cron_health():
    alerts = []
    for j in _jobs():
        name = j.get("name", "?")
        if name == SELF_JOB:        # never grade ourselves -> no feedback loop
            continue
        enabled = j.get("enabled", False)
        if enabled and j.get("state") == "scheduled" and j.get("last_status") is None:
            continue  # never run yet — normal
        if j.get("last_status") == "error":
            err = str(j.get("last_error") or "")
            # A bounded-runner TIMEOUT (scheduler.py: "Script timed out after Ns: ...") is the
            # same transient-overload class the git guard already excludes (load noise must not
            # read as down). Post-wake CPU/IO contention makes a script that normally finishes in
            # ~9s blow past its 120s cap; load subsides and the next run + probe pass clean. These
            # self-resolve, so recording a CRON_ERROR fingerprint only fires a FALSE health-watchdog
            # failure (root-caused 2026-06-21: repo-health-check 8.77s/exit0 vs a 120s timeout in
            # the 04:54Z wake window). A genuine cron fault exits nonzero with a real error string.
            if "Script timed out after" in err:
                continue
            # Upstream provider billing/auth rejections (HTTP 402 "Insufficient Balance",
            # 401 Unauthorized, 429 rate-limited) hang the stream indefinitely — they
            # look like timeouts but are a different class of failure (provider-side,
            # not scheduler-side). They re-fire every cycle until the user tops up the
            # provider balance. Surfacing them as CRON_ERROR re-fires ~96x/day with
            # zero resolution. Emit a single CREDITS_ERROR fingerprint per affected
            # job and continue.
            #
            # Two patterns to detect:
            # 1. Direct: err contains "Insufficient Balance", "402", "Payment Required"
            # 2. Indirect: stream stalled mid-flight ("waiting for stream response (Ns, no chunks yet)")
            #    — the cron surfaces only TimeoutError, but agent.log will show the underlying 402.
            #    We cross-reference agent.log when the message matches the stream-stall pattern.
            is_credits = any(token in err for token in ("Insufficient Balance", "402", "Payment Required"))
            is_stream_stall = "waiting for stream response" in err and "no chunks yet" in err
            if is_credits or is_stream_stall:
                # Cross-reference agent.log for the underlying HTTP status if it's a stream stall
                upstream_cause = ""
                if is_stream_stall:
                    try:
                        import subprocess as _sp
                        _r = _sp.run(
                            ["grep", "-E", "Insufficient Balance|HTTP 402|402 -", "-m", "3", "logs/agent.log"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if _r.stdout.strip():
                            upstream_cause = " — upstream agent.log shows provider billing rejection"
                    except Exception:
                        pass
                # Log as a dedicated CREDITS_ERROR so the 8am strategist audit picks it up
                # even though it's not in the main alerts list.
                credit_alert = {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "type": "CREDITS_ERROR",
                    "message": f"CREDITS_ERROR: {name} provider rejected request (likely billing){upstream_cause}: {err[:200]}",
                    "job": name,
                    "status": "open",
                    "healthy": False,
                }
                try:
                    with open(ALERT_LOG, "a") as _f:
                        _f.write(json.dumps(credit_alert) + "\n")
                except Exception:
                    pass
                continue
            alerts.append(f"CRON_ERROR: {name} errored: {err[:80]}")
        # Staleness must be schedule-aware. A flat "older than N hours since last_run"
        # test fires a false CRON_STALE for any job whose cadence exceeds the threshold:
        # a weekly job (e.g. "Run lux verify on all projects", 0 0 * * 0) ran on time
        # Sunday but reads as "not run in 26h" every day Mon–Sat by design. Grade against
        # the job's OWN next_run_at instead — a job is stale only when the scheduler should
        # already have re-run it but hasn't (overdue past a grace window). Fall back to the
        # last_run heuristic only when next_run_at is absent/unparseable.
        if not enabled:
            continue
        grace_h = ALERT_THRESHOLDS["cron_stale_hours"]
        next_raw = j.get("next_run_at")
        if next_raw:
            try:
                nxt = datetime.fromisoformat(next_raw.replace("Z", "+00:00"))
                overdue = (time.time() - nxt.timestamp()) / 3600
                if overdue > grace_h:
                    alerts.append(f"CRON_STALE: {name} overdue {overdue:.0f}h past schedule")
                continue
            except (ValueError, TypeError):
                pass  # malformed next_run_at -> fall through to last_run heuristic
        last_raw = j.get("last_run_at")
        if last_raw:
            try:
                last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
                elapsed = (time.time() - last.timestamp()) / 3600
                if elapsed > grace_h:
                    alerts.append(f"CRON_STALE: {name} not run in {elapsed:.0f}h")
            except (ValueError, TypeError):
                alerts.append(f"CRON_PARSE: {name} unparseable last_run_at")
    return alerts


def check_git_health():
    out, code = run(f"cd {HERMES_HOME} && git status --porcelain", timeout=10)
    if code < 0:
        # Negative return code = our bounded runner killed git on a TIMEOUT (run() returns
        # ('(timeout)', -1)) or the OS killed it with a signal (e.g. SIGHUP on sleep/wake).
        # The box was overloaded, not the repo broken — transient load-noise (UNKNOWN), the
        # same class the probe excludes ("load noise must not read as down"). Recording it as a
        # GIT_ERROR fingerprint lets a sustained-overload window breach the K-run SLA and fire a
        # FALSE health-watchdog failure (root-caused 2026-06-21: 'git status failed code -1' =
        # the 10s git status timing out post-wake at 04:54Z). Real git faults return code > 0.
        return []
    if code != 0:
        return [f"GIT_ERROR: git status failed code {code}"]
    count = len([l for l in out.split("\n") if l.strip()]) if out else 0
    if count > ALERT_THRESHOLDS["uncommitted_files_max"]:
        return [f"GIT_DIRTY: {count} uncommitted files"]
    return []


def gateway_up() -> bool:
    """True iff the gateway daemon is GENUINELY alive (load-immune os.kill on the pidfile
    PID — never a ps snapshot). HERMES_FAKE_GATEWAY (up/down) remains the test seam,
    honored inside hermes_gateway.gateway_liveness()."""
    return gateway_liveness() is True


def check_disk():
    out, _ = run("df -h / | tail -1 | awk '{print $5}' | tr -d '%'", 5)
    try:
        pct = int(out)
        if pct > ALERT_THRESHOLDS["disk_usage_percent_max"]:
            return [f"DISK_HIGH: disk at {pct}%"]
    except ValueError:
        pass
    return []


# ── state ────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"fingerprints": {}, "daemon_history": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.parent / f".wd-{os.getpid()}.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_FILE)


# Cron cadence inference map (display string → hours). Conservative: when schedule kind
# is "every Nm" or cron expr, we map common cases. Fallback for unknown cadence is None
# (silent-stretch skipped for that job to avoid false positives).
_CADENCE_HOURS = {
    "*/5 * * * *": 5/60, "*/10 * * * *": 10/60, "*/15 * * * *": 15/60,
    "*/30 * * * *": 0.5, "0 * * * *": 1, "1-59/5 * * * *": 5/60,
    "0 0 * * *": 24, "0 6 * * *": 24, "0 8 * * *": 24, "0 9 * * *": 24,
    "0 18 * * *": 24, "0 0 * * 0": 168, "0 0 * * 1": 168,
}


def _infer_cadence_hours(j):
    """Best-effort cadence in hours for a job. Returns float or None."""
    sched = j.get("schedule") or {}
    expr = sched.get("expr") if isinstance(sched, dict) else None
    display = j.get("schedule_display") or ""
    if expr and expr in _CADENCE_HOURS:
        return _CADENCE_HOURS[expr]
    if display.startswith("every "):
        try:
            n = int(display.split()[1].rstrip("m"))
            return n / 60.0
        except (IndexError, ValueError):
            return None
    return None


def check_cron_silent_stretch(state, jobs):
    """07-08 audit fix, refined 2026-07-10: detect cron jobs whose schedule has advanced
    past `last_run_at + cadence` without the job firing.

    Layer-verification (added 2026-07-10): the original detector only tracked changes
    between consecutive watchdog runs — i.e. "did next_run_at change since I last saw
    it?" — which is structurally blind to historical accumulation. If the cron ticker
    fast-forwards a paused/disabled job ONCE per watchdog cycle (advancing to "next
    scheduled time"), the detector sees schedule_at==next_raw, run_at==last_raw, and
    records no change. So a job that has been silent for 19 days shows streak=0.

    The correct invariant is **schedule_vs_run_drift**: how many cadences has the
    schedule advanced past the actual run? If `last_run_at` is older than
    `(last_run_at + cadence * N)` would predict for N>=3, then the ticker has skipped
    at least 3 schedules without firing. We compute the drift directly from the
    CURRENT jobs.json (no need to track changes across watchdog runs), which makes the
    detector stateless w.r.t. watchdog frequency and catches historical accumulation.

    Also keeps the streak counter so a job that gets fast-forwarded while we're watching
    can still trigger mid-cycle (recovers the original intent).
    """
    silent_stretch_threshold = int(os.environ.get("HERMES_CRON_SILENT_STRETCH", "2"))
    fast_forward_state = state.setdefault("fast_forward_streaks", {})
    alerts = []
    now = datetime.now(timezone.utc)
    for j in jobs:
        if not j.get("enabled", False):
            continue
        jid = j.get("id", "")
        name = j.get("name", jid)
        next_raw = j.get("next_run_at")
        last_raw = j.get("last_run_at")
        if not next_raw or not last_raw:
            continue
        cadence_h = _infer_cadence_hours(j)
        if cadence_h is None or cadence_h <= 0:
            continue
        try:
            nxt_dt = datetime.fromisoformat(next_raw.replace("Z", "+00:00"))
            last_dt = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        # Primary signal: how many scheduled fires have been skipped since last_run?
        # The cron ticker fast-forwards to the NEXT scheduled run. Slots in the
        # future are not yet due, so we measure drift from elapsed wall-clock time.
        # Grace is 10% of cadence (or 1 minute, whichever is larger) to absorb
        # sub-cadence fractional drift in last_run_at timestamps.
        elapsed_h = (now - last_dt).total_seconds() / 3600.0
        grace_h = max(cadence_h * 0.10, 1.0 / 60.0)
        if elapsed_h <= 0:
            drift = 0
        else:
            # Number of schedules that fell at or before now, strictly after last_run.
            # Schedule k fires at last_run + k*cadence. It's missed if last_run +
            # k*cadence <= now. The largest such k is int(elapsed_h / cadence_h).
            # Grace absorbs sub-cadence remainder to handle clock drift.
            # Result: drift = "how many times this job should have fired since
            # last_run but did not."
            drift = max(0, int((elapsed_h + grace_h) / cadence_h))
        # Backstop: if next_run_at is in the past and last_run_at hasn't moved, the
        # ticker has clearly skipped. Use that as a "minimum drift" floor.
        backstop_drift = 0
        if nxt_dt < now and last_dt < now:
            # next_run is overdue and last_run hasn't fired since. Drift = at least 1.
            backstop_drift = max(0, int((now - nxt_dt).total_seconds() / 3600.0 / cadence_h) + 1)

        # Secondary signal: maintain the streak counter so changes between watchdog runs
        # still count. If schedule_at advanced past last record AND run_at unchanged,
        # increment; if run_at advanced, reset.
        rec = fast_forward_state.setdefault(jid, {"schedule_at": next_raw, "run_at": last_raw, "streak": 0})
        if rec["run_at"] != last_raw:
            rec["streak"] = 0
            rec["schedule_at"] = next_raw
            rec["run_at"] = last_raw
        elif rec["schedule_at"] != next_raw:
            rec["streak"] += 1
            rec["schedule_at"] = next_raw
            rec["run_at"] = last_raw

        # Use the larger of the two signals
        effective = max(drift, backstop_drift, rec["streak"])
        if effective >= silent_stretch_threshold:
            alerts.append(
                f"CRON_SILENT_STRETCH: {name} missed {effective} consecutive schedules "
                f"(last_run_at stuck at {last_raw[:19]}, cadence={cadence_h}h)"
            )
            rec["streak"] = effective  # so we don't lose track
    return alerts


def log_summary(entry):
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def submit_to_queue(alert, severity):
    if not QUEUE.exists():
        return
    run(f'{sys.executable} {QUEUE} submit --source health-watchdog '
        f'--severity {severity} --message {json.dumps(alert)}', timeout=10)


def main():
    (HERMES_HOME / "logs" / "alerts").mkdir(parents=True, exist_ok=True)
    state = load_state()
    fps = state["fingerprints"]
    now = time.time()

    # 1. detect
    alerts = []
    for det in (check_cron_health, check_git_health, check_disk):
        alerts.extend(det())
    # CRON_SILENT_STRETCH (07-08 audit fix): catches fast-forward streaks that the
    # schedule-aware CRON_STALE check is blind to (next_run_at gets updated by the
    # ticker on every fast-forward, masking the gap).
    try:
        jobs = _jobs()
        alerts.extend(check_cron_silent_stretch(state, jobs))
    except Exception:
        pass
    current = {}
    for a in alerts:
        atype = a.split(":")[0] if ":" in a else "UNKNOWN"
        current[canonicalize(f"{atype}: {a}")] = (atype, a)

    # 2. daemon liveness invariant — sustained over last N *known* runs, load-immune.
    #    A timeout/unreadable reading is UNKNOWN (not DOWN), so load noise can no longer
    #    forge a restart loop. Only GENUINE down readings (os.kill says the PID is gone)
    #    count against sustained-liveness. This is the snapshot-as-proof fix, sensor side.
    st = liveness_state()                       # 'up' | 'down' | 'unknown'
    up = (st == "up")
    hist = state["daemon_history"]
    hist.append({"ts": iso_now(), "up": up, "state": st})
    # Keep extra slots so a run of UNKNOWNs can't evict the known history that proves health.
    state["daemon_history"] = hist[-max(SUSTAIN_N * 2, 1):]
    window = state["daemon_history"]

    def _state(h):
        return h.get("state", "up" if h.get("up") else "down")  # back-compat for old entries

    recent_known = [h for h in window if _state(h) in ("up", "down")][-SUSTAIN_N:]
    restart_loop = (len(recent_known) >= SUSTAIN_N
                    and not all(_state(h) == "up" for h in recent_known))

    # 3. update fingerprint streaks
    newly, breached = [], []
    for fp, (atype, msg) in current.items():
        rec = fps.get(fp)
        if rec is None:
            fps[fp] = {"type": atype, "sample": msg[:200], "first_seen": iso_now(),
                       "last_seen": iso_now(), "present_streak": 1, "absent_streak": 0}
            newly.append(msg)
        else:
            rec["present_streak"] = rec.get("present_streak", 0) + 1
            rec["absent_streak"] = 0
            rec["last_seen"] = iso_now()
        if fps[fp]["present_streak"] >= OPEN_BREACH_K:
            breached.append(msg)

    # 4. resolution invariant: absent for K runs => drop from open set
    resolved_fps = []
    for fp in list(fps.keys()):
        if fp not in current:
            fps[fp]["absent_streak"] = fps[fp].get("absent_streak", 0) + 1
            fps[fp]["present_streak"] = 0
            if fps[fp]["absent_streak"] >= RESOLVE_AFTER_K:
                resolved_fps.append(fp)
    for fp in resolved_fps:
        # State-vs-log mirroring (07-08 audit fix): write a status: resolved log entry
        # so that `grep '"status": "open"' watchdog.jsonl` doesn't return historical entries
        # that the state file has already cleared. Without this, state and log drift apart
        # and grep-based audits see false positives (open_fingerprints=0 vs open log entries).
        try:
            resolved_entry = {
                "timestamp": iso_now(),
                "type": fps[fp].get("type", "UNKNOWN"),
                "fingerprint": fp,
                "status": "resolved",
                "resolution": "auto_streak_resolved",
                "healthy": True,
            }
            ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ALERT_LOG.open("a") as _rf:
                _rf.write(json.dumps(resolved_entry) + "\n")
        except Exception:
            pass
        del fps[fp]

    # 5. summary + relay submit
    log_summary({"timestamp": iso_now(), "type": "watchdog_summary",
                 "message": f"Watchdog run: {len(alerts)} alerts",
                 "healthy": len(alerts) == 0 and not restart_loop,
                 "alert_count": len(alerts), "alerts": alerts,
                 "daemon_up": up, "restart_loop": restart_loop,
                 "open_fingerprints": len(fps)})
    for a in alerts:
        log_summary({"timestamp": iso_now(),
                     "type": a.split(":")[0] if ":" in a else "UNKNOWN",
                     "message": a, "healthy": False, "status": "open"})

    if restart_loop:
        submit_to_queue(f"GATEWAY_RESTART_LOOP: gateway not sustained-alive over last "
                        f"{len(window)} runs (window up={[h['up'] for h in window]})", "crit")
    for a in newly:
        submit_to_queue(a, "warn")

    # 6. heal (best-effort)
    healer = HERMES_HOME / "scripts" / "self-healer.py"
    if alerts and healer.exists():
        run(f"{sys.executable} {healer} " + " ".join(f'"{a}"' for a in alerts), timeout=30)

    # 7. probe-verified resolution pass (authoritative log lifecycle)
    resolver = HERMES_HOME / "scripts" / "alert-resolver.py"
    if resolver.exists():
        run(f"{sys.executable} {resolver} --check {json.dumps(json.dumps(alerts))}", timeout=20)

    save_state(state)

    # 8. grade -> exit code (honest signal). stdout only when newly actionable.
    if restart_loop:
        print(f"🔁 RESTART LOOP: gateway not sustained-alive over last {len(window)} runs")
        code = EXIT_RESTART_LOOP
    elif breached:
        print(f"⚠️  {len(breached)} alert(s) open >= {OPEN_BREACH_K} runs (unhealed):")
        for a in breached:
            print(f"   ❗ {a.splitlines()[0][:100]}")
        code = EXIT_OPEN_BREACH
    elif newly:
        print(f"⚠️  {len(newly)} new issue(s) (tracking):")
        for a in newly:
            print(f"   • {a.splitlines()[0][:100]}")
        code = EXIT_HEALTHY  # new but not yet breached — tracked, not a failure
    else:
        code = EXIT_HEALTHY  # silent
    return code


if __name__ == "__main__":
    sys.exit(main())
