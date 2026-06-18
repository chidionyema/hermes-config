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

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
PROBE_LOG = HERMES_HOME / "logs" / "maintenance" / "probe-findings.jsonl"

# Thresholds mirror the watchdog. Env-overridable so the probe can drive them.
GIT_DIRTY_MAX = int(os.environ.get("HERMES_GIT_DIRTY_MAX", "50"))
DISK_PCT_MAX = int(os.environ.get("HERMES_DISK_PCT_MAX", "90"))
CRON_STALE_HOURS = int(os.environ.get("HERMES_CRON_STALE_HOURS", "26"))


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── shell helper ────────────────────────────────────────────────────────────
def _sh(cmd: str, timeout: int = 8) -> tuple[str, int]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception:
        return "", -1


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
    for j in _load_jobs():
        if j.get("name") == name:
            return j.get("last_status") != "error"  # cleared iff last run not an error
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
    out, _ = _sh("ps aux | grep 'python.*gateway' | grep -v grep | wc -l | tr -d ' '")
    if out == "":
        return None
    return out != "0"  # cleared iff a gateway process is alive


def _v_git_dirty(entry: dict) -> bool | None:
    out, code = _sh(f"cd {HERMES_HOME} && git status --porcelain")
    if code != 0:
        return None
    count = len([l for l in out.split("\n") if l.strip()]) if out else 0
    return count <= GIT_DIRTY_MAX


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
    "GIT_DIRTY": _v_git_dirty,
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
    print("alert-resolver self-test: PASS (fingerprint-keyed, verifier-gated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
