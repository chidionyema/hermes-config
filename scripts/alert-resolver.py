#!/usr/bin/env python3
"""Alert Resolution System — PROBE-VERIFIED resolution (Fire 4-LF fix).

ROOT CAUSE THIS REPLACES
  The old resolver closed an open alert whenever its *message string* was absent
  from the caller-supplied "current run" list. Two failure modes compounded:
    1. PID/timestamp-varying messages made the SAME persistent condition look like
       a different string every run, so the prior alert appeared "absent" and was
       false-cleared. The real log showed an 804/261 false-clear ratio — alerts
       marked "resolved/healthy" while the condition was still firing.
    2. It trusted the caller's list as ground truth instead of re-checking reality.

THE FIX — resolution is an INVARIANT, verified by an independent re-probe:
    An alert is resolved ONLY when a verifier RE-RUNS the underlying check and
    confirms the condition is genuinely CLEARED. Resolution is never inferred from
    a message going absent. Everything is graded on the CANONICAL FINGERPRINT
    (hermes_fingerprint.canonicalize), so PID/timestamp variants collapse to one
    stable identity and can never false-clear each other.

    - verifier says CLEARED  -> append resolution (resolution="probe_verified")
    - verifier says ACTIVE    -> leave open (the condition really is still firing)
    - no verifier for type    -> leave open (CONSERVATIVE: we never guess "resolved")

USAGE
  python3 alert-resolver.py --check '["CRON_ERROR: foo errored: ...", ...]'
    --check is kept for caller compatibility (the watchdog passes its run) but is
    now ADVISORY ONLY: it can never cause a resolution. Resolution is decided purely
    by the verifiers. Pass --verbose for an audit trace.

  python3 alert-resolver.py --self-test   # offline invariant check, exit 0/1

DESIGN
  - Append-only log: an open entry is never mutated; a companion status=resolved
    entry is appended, carrying the fingerprint + the verifier that cleared it.
  - Re-open is automatic: if the condition fires again the watchdog logs a new open
    entry, and a later verifier can resolve it again — full lifecycle, no leaks.
  - Stdlib only. All paths honor HERMES_HOME so the probe runs fully isolated.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes_fingerprint import canonicalize  # noqa: E402
from hermes_subprocess import sh as _bounded_sh  # noqa: E402  orphan-safe subprocess
from hermes_gateway import gateway_liveness      # noqa: E402  load-immune liveness

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
STATE_FILE = HERMES_HOME / "logs" / "alerts" / "watchdog-state.json"
PROBE_LOG = HERMES_HOME / "logs" / "maintenance" / "probe-findings.jsonl"

# Thresholds mirror the watchdog. Env-overridable so the probe can drive them.
GIT_DIRTY_MAX = int(os.environ.get("HERMES_GIT_DIRTY_MAX", "50"))
DISK_PCT_MAX = int(os.environ.get("HERMES_DISK_PCT_MAX", "90"))
CRON_STALE_HOURS = int(os.environ.get("HERMES_CRON_STALE_HOURS", "26"))
# Sustained-liveness window + freshness guard, mirroring the watchdog (cadence 15m).
SUSTAIN_N = int(os.environ.get("HERMES_WD_SUSTAIN_N", "3"))
GATEWAY_FRESH_SECONDS = int(os.environ.get("HERMES_WD_FRESH_SECONDS", "1800"))  # 2*cadence


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ── shell helper (orphan-safe: process-group kill on timeout) ────────────────
def _sh(cmd: str, timeout: int = 8) -> tuple[str, int]:
    out, code = _bounded_sh(cmd, timeout=timeout)
    return ("" if out == "(timeout)" else out), code


def _load_jobs() -> list[dict]:
    jp = HERMES_HOME / "cron" / "jobs.json"
    if not jp.exists():
        return []
    try:
        return json.loads(jp.read_text()).get("jobs", [])
    except (OSError, json.JSONDecodeError):
        return []


def _job_name_from(message: str) -> str:
    """'CRON_ERROR: foo errored: ...' -> 'foo'  (the token after the type prefix)."""
    m = re.match(r"^[A-Z_]+:\s+(\S+)", message.strip())
    return m.group(1) if m else ""


# ── verifiers: return True only when the condition is genuinely CLEARED ───────
# Signature: (entry) -> bool | None.  True=cleared, False=still active, None=unknown.
def _v_cron_error(entry: dict) -> bool | None:
    name = _job_name_from(entry.get("message", ""))
    if not name:
        return None
    open_ts = _parse_iso(entry.get("timestamp"))
    for j in _load_jobs():
        if j.get("name") == name:
            if j.get("last_status") == "error":
                return False  # still erroring -> active
            # Cleared ONLY by a REAL run that completed AFTER the alert opened. The healer
            # no longer writes last_status, and a pre-existing "ok" that predates the alert
            # is NOT proof THIS failure cleared. Proof must come from the workload.
            last_run = _parse_iso(j.get("last_run_at"))
            if open_ts and last_run and last_run > open_ts:
                return True
            return None  # not erroring, but no fresh real run -> UNKNOWN, keep open
    return None  # job vanished — can't prove cleared


def _v_cron_stale(entry: dict) -> bool | None:
    name = _job_name_from(entry.get("message", ""))
    if not name:
        return None
    for j in _load_jobs():
        if j.get("name") == name:
            last = j.get("last_run_at")
            if not last:
                return False
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                return hours <= CRON_STALE_HOURS
            except (ValueError, TypeError):
                return None
    return None


def _v_gateway(entry: dict) -> bool | None:
    # Load-immune liveness (os.kill on the pidfile PID), not a ps snapshot.
    return gateway_liveness()  # True=up(cleared) / False=down(active) / None=unknown(keep open)


def _v_gateway_sustained(entry: dict) -> bool | None:
    """Verifier for GATEWAY_RESTART_LOOP — resolve ONLY on PROOF of sustained liveness:
    the last SUSTAIN_N *known* readings in the watchdog window are all 'up', AND the
    window is FRESH. The freshness guard is mandatory: a stalled watchdog freezes the
    window, and without it the alert would deadlock (never clear, never confirm broken)."""
    try:
        s = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    hist = s.get("daemon_history", [])
    if not hist:
        return None
    last_ts = _parse_iso(hist[-1].get("ts"))
    if not last_ts:
        return None
    if (datetime.now(timezone.utc) - last_ts).total_seconds() > GATEWAY_FRESH_SECONDS:
        return None  # stale window -> UNKNOWN (no deadlock, no false-clear)

    def _up(h):
        return h.get("state") == "up" if "state" in h else bool(h.get("up"))

    def _known(h):
        return h.get("state") in ("up", "down") if "state" in h else True

    recent = [h for h in hist if _known(h)][-SUSTAIN_N:]
    if len(recent) < SUSTAIN_N:
        return None  # not enough evidence yet -> keep open
    return all(_up(h) for h in recent)


def _v_git_dirty(entry: dict) -> bool | None:
    out, code = _sh(f"cd {HERMES_HOME} && git status --porcelain")
    if code != 0:
        return None
    count = len([l for l in out.split("\n") if l.strip()]) if out else 0
    return count <= GIT_DIRTY_MAX


def _v_git_error(entry: dict) -> bool | None:
    """GIT_ERROR means `git status` itself FAILED (e.g. code -1 = the command was
    killed / timed out — typically CPU starvation, not repo corruption). It is a
    TRANSIENT condition: cleared the moment git status runs cleanly again. Re-probe
    and resolve on success so it can't linger as 'unverifiable, kept open'."""
    out, code = _sh(f"cd {HERMES_HOME} && git status --porcelain", timeout=15)
    if code == 0:
        return True   # git is healthy again -> cleared
    return False      # still failing -> keep open (real problem)


def _v_disk(entry: dict) -> bool | None:
    out, _ = _sh("df -h / | tail -1 | awk '{print $5}' | tr -d '%'")
    try:
        return int(out) <= DISK_PCT_MAX
    except ValueError:
        return None


def _v_idle_error(entry: dict) -> bool | None:
    for j in _load_jobs():
        if "idle" in j.get("name", "").lower():
            return j.get("last_status") != "error"
    return None


def _v_policy_never_fired(entry: dict) -> bool | None:
    # cleared iff the named policy now has >0 hits
    m = re.match(r"^POLICY_NEVER_FIRED:\s+(\S+)", entry.get("message", ""))
    if not m:
        return None
    pid = m.group(1)
    pdir = HERMES_HOME / "policies"
    if not pdir.exists():
        return None
    for fn in os.listdir(pdir):
        if not fn.endswith(".json"):
            continue
        try:
            p = json.loads((pdir / fn).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if p.get("id") == pid:
            return p.get("hits", 0) > 0
    return None


VERIFIERS = {
    "CRON_ERROR": _v_cron_error,
    "CRON_STALE": _v_cron_stale,
    "CRON_PARSE": _v_cron_error,
    "GATEWAY_DOWN": _v_gateway,
    "GATEWAY_IDLE": _v_gateway,
    "GATEWAY_RESTART_LOOP": _v_gateway_sustained,  # the only gateway alert the watchdog emits
    "GIT_DIRTY": _v_git_dirty,
    "GIT_ERROR": _v_git_error,
    "DISK_HIGH": _v_disk,
    "IDLE_ERROR": _v_idle_error,
    "POLICY_NEVER_FIRED": _v_policy_never_fired,
}


# ── alert-log lifecycle ──────────────────────────────────────────────────────
def read_alerts() -> list[dict]:
    if not ALERT_LOG.exists():
        return []
    out = []
    try:
        for line in ALERT_LOG.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def open_fingerprints(entries: list[dict]) -> dict[str, dict]:
    """Currently-open alerts keyed by canonical fingerprint.

    An entry is open if it is a typed alert with a message and is not already
    resolved. Resolution by a later companion entry (same fingerprint) closes it.
    Last writer wins per fingerprint, so a re-opened condition is open again.
    """
    state: dict[str, dict] = {}
    for e in entries:
        et = e.get("type", "")
        if et == "watchdog_summary" or "message" not in e or not et:
            continue
        fp = canonicalize(f"{et}: {e['message']}")
        if e.get("status") == "resolved":
            state.pop(fp, None)
        else:
            state[fp] = {**e, "_fp": fp}
    return state


def append_resolution(entry: dict, verifier_name: str) -> None:
    rec = {
        "timestamp": iso_now(),
        "type": entry.get("type", "UNKNOWN"),
        "message": entry.get("message", ""),
        "fingerprint": entry.get("_fp", ""),
        "status": "resolved",
        "resolved_at": iso_now(),
        "resolution": "probe_verified",
        "verifier": verifier_name,
        "open_since": entry.get("timestamp", "unknown"),
        "healthy": True,
    }
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe-verified alert resolution")
    ap.add_argument("--check", default="[]",
                    help="ADVISORY current-run alert list (JSON). Never causes resolution.")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="Run offline invariant checks and exit.")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    # --check is parsed only to validate/echo; it cannot drive resolution anymore.
    try:
        json.loads(args.check)
    except json.JSONDecodeError as e:
        print(f"alert-resolver: bad --check arg: {e}", file=sys.stderr)
        return 1

    entries = read_alerts()
    open_set = open_fingerprints(entries)

    resolved = active = unknown = 0
    for fp, entry in sorted(open_set.items()):
        verifier = VERIFIERS.get(entry.get("type", ""))
        if verifier is None:
            unknown += 1
            if args.verbose:
                print(f"  · no verifier for {entry.get('type')} — left open: {fp[:60]}")
            continue
        try:
            verdict = verifier(entry)
        except Exception as exc:  # a flaky probe must never false-clear
            verdict = None
            if args.verbose:
                print(f"  · verifier error ({entry.get('type')}): {exc} — left open")
        if verdict is True:
            append_resolution(entry, verifier.__name__)
            resolved += 1
            if args.verbose:
                print(f"  ✓ probe-verified CLEARED -> resolved: {fp[:60]}")
        elif verdict is False:
            active += 1
            if args.verbose:
                print(f"  ✗ still ACTIVE — kept open: {fp[:60]}")
        else:
            unknown += 1
            if args.verbose:
                print(f"  · UNKNOWN — kept open (no false-clear): {fp[:60]}")

    if resolved or args.verbose:
        print(f"🔄 alert-resolver: {resolved} probe-verified resolution(s), "
              f"{active} still active, {unknown} unverifiable (kept open)")
    return 0


def _self_test() -> int:
    """Offline proof the resolver grades on fingerprint, not message string."""
    a = "CRON_ERROR: idle-continuous-learning errored: code 1 at 2026-06-18 19:24 PID 111"
    b = "CRON_ERROR: idle-continuous-learning errored: code 1 at 2026-06-18 16:53 PID 222"
    fa = canonicalize(f"CRON_ERROR: {a}")
    fb = canonicalize(f"CRON_ERROR: {b}")
    assert fa == fb, "PID/timestamp variants must share one fingerprint"
    assert _job_name_from(a) == "idle-continuous-learning", "job-name extraction"
    assert set(VERIFIERS) >= {"CRON_ERROR", "GATEWAY_DOWN", "GIT_DIRTY", "IDLE_ERROR"}
    # GATEWAY_RESTART_LOOP is the ONLY gateway alert the watchdog actually emits — it
    # MUST have a verifier, or it can never auto-clear (the original coverage hole).
    assert "GATEWAY_RESTART_LOOP" in VERIFIERS, \
        "GATEWAY_RESTART_LOOP must have a verifier (it is the only gateway alert emitted)"

    # Invariant: the actuator can no longer forge a resolution. A cron that is 'ok' but
    # whose only successful run PREDATES the alert must NOT be graded cleared (UNKNOWN).
    import tempfile
    from pathlib import Path as _P
    global HERMES_HOME
    with tempfile.TemporaryDirectory() as td:
        (_P(td) / "cron").mkdir()
        # last run is BEFORE the alert opened -> not proof THIS failure cleared
        (_P(td) / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
            {"name": "demo", "last_status": "ok", "last_run_at": "2026-01-01T00:00:00Z"}]}))
        _orig = HERMES_HOME
        HERMES_HOME = _P(td)
        try:
            stale = _v_cron_error({"message": "CRON_ERROR: demo errored: x",
                                   "timestamp": "2026-06-20T00:00:00Z"})
        finally:
            HERMES_HOME = _orig
    assert stale is None, f"healer-forged/stale 'ok' must read UNKNOWN, got {stale!r}"
    print("alert-resolver self-test: PASS (fingerprint-keyed, verifier-gated, "
          "actuator cannot forge resolution, gateway loop covered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
