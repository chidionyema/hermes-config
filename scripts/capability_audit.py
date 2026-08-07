#!/usr/bin/env python3
"""Capability audit — does the estate actually PRODUCE anything?

The question every green light failed to answer on 2026-08-05: verify_estate.sh said
"coordinator last_tick 15s ago" while the estate had done nothing for 3 days, because
liveness (is the process alive) was being read as productivity (is it doing the job).

This probe reads ~/.hermes/capabilities.json — where every capability declares what it
must produce and how often — and compares the declaration against the filesystem and the
database. It never asks whether a job ran. It asks whether its output exists and is fresh.

Verdicts:
  PRODUCING  fresh output within 1.5x the declared period
  STALE      output exists but is older than 1.5x the period (drifting)
  DARK       output older than 3x the period, or absent entirely  -> FAIL
  UNPROVEN   the capability declares no observable at all         -> FAIL
  BROKEN     the declared observable could not be evaluated       -> FAIL
  LATCHED    a latch has been held longer than its declared max   -> FAIL

UNPROVEN is deliberately a failure. A capability nobody can measure is indistinguishable
from a capability that does not work, and treating it as a pass is the exact bug this
probe exists to kill. To clear an UNPROVEN, declare its observable — never delete the row.

Read-only. Exit 0 = every capability proven producing, every latch within its window.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import time

# Honour HERMES_HOME so this probe can be pointed at a fixture estate.
#
# It was hardcoded to ~/.hermes until 2026-08-05, which made every "mutation test"
# of it silently read production and pass for the wrong reason. A reliability probe
# you cannot exercise against a known-bad fixture is one whose failure path has
# never been observed — the same class of defect it exists to catch.
HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
REGISTRY = os.environ.get("HERMES_CAPABILITIES") or os.path.join(HOME, "capabilities.json")
JOBS = os.path.join(HOME, "cron", "jobs.json")

FAIL_VERDICTS = {"DARK", "UNPROVEN", "BROKEN", "LATCHED"}

MARK = {
    "PRODUCING": "\033[32m✅\033[0m",
    "STALE": "\033[33m⚠️ \033[0m",
    "DARK": "\033[31m❌\033[0m",
    "UNPROVEN": "\033[31m❓\033[0m",
    "BROKEN": "\033[31m💥\033[0m",
    "WARMING": "\033[36m🌡️ \033[0m",
    "LATCHED": "\033[31m🔒\033[0m",
    "OK": "\033[32m✅\033[0m",
}


def _resolve(path: str) -> str:
    """Registry paths are relative to ~/.hermes unless absolute or ~-prefixed."""
    if path.startswith("~"):
        return os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(HOME, path)


def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds/60:.0f}m"
    if seconds < 172800:
        return f"{seconds/3600:.1f}h"
    return f"{seconds/86400:.1f}d"


def _newest_mtime(pattern: str) -> tuple[float | None, str | None]:
    """Newest mtime across a glob, and which file carried it."""
    matches = glob.glob(_resolve(pattern))
    best_t, best_p = None, None
    for p in matches:
        try:
            t = os.path.getmtime(p)
        except OSError:
            continue
        if best_t is None or t > best_t:
            best_t, best_p = t, p
    return best_t, best_p


def _normalise_epoch(value) -> float | None:
    """Accept seconds, milliseconds, or an ISO-8601 string. Reject nonsense."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        if not s:
            return None
        try:
            from datetime import datetime

            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            try:
                value = float(s)
            except ValueError:
                return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1e11:  # milliseconds
        v /= 1000.0
    # An epoch before 2001 or more than a day in the future is a schema mismatch,
    # not a timestamp. Report it as BROKEN rather than silently as DARK/PRODUCING.
    if v < 978_307_200 or v > time.time() + 86_400:
        raise ValueError(f"implausible epoch {v!r}")
    return v


def _observe(cap: dict) -> tuple[float | None, str, str | None]:
    """Return (last_produced_epoch, detail, error). error non-None => BROKEN."""
    obs = cap.get("observable") or {"kind": "none"}
    kind = obs.get("kind", "none")

    if kind == "none":
        return None, "no observable declared", None

    if kind == "file":
        pattern = obs.get("path")
        if not pattern:
            return None, "", "file observable has no path"
        t, which = _newest_mtime(pattern)
        if t is None:
            return None, f"no file matches {pattern}", None
        return t, os.path.relpath(which, HOME) if which.startswith(HOME) else which, None

    if kind == "receipt":
        # Measured production, from cron/scheduler.py::_write_receipt. Each job run
        # records the files it touched under ~/.hermes. This is how a capability whose
        # output nobody could name becomes measurable without a human maintaining a
        # path list that drifts the moment a script is edited.
        #
        # requires:
        #   artifacts (default) — a run counts only if it wrote a non-log file. This is
        #                         what catches exit-0-did-nothing, the class that let
        #                         self-improve report ok while closing zero gaps.
        #   exit0               — a clean exit counts. Only correct for jobs whose real
        #                         output leaves the filesystem (a Telegram message);
        #                         say so in the note, because it is a weaker claim.
        script = obs.get("script")
        if not script:
            return None, "", "receipt observable has no script"
        requires = obs.get("requires", "artifacts")
        path = os.path.join(HOME, "state", "capability_receipts.jsonl")
        if not os.path.exists(path):
            return None, "no receipts file yet (cron instrumentation added 2026-08-05)", None
        best, runs, matched = None, 0, 0
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("script") != script:
                        continue
                    runs += 1
                    if requires == "artifacts" and not rec.get("artifact_count"):
                        continue
                    if requires == "exit0" and rec.get("exit_code") != 0:
                        continue
                    matched += 1
                    t = rec.get("ended_at")
                    if isinstance(t, (int, float)) and (best is None or t > best):
                        best = t
        except OSError as exc:
            return None, "", f"receipts unreadable: {exc}"
        if best is None:
            if runs == 0:
                return None, f"no run of {script} recorded yet", None
            return None, f"{runs} run(s) of {script}, 0 met [{requires}]", None
        return best, f"{matched}/{runs} run(s) of {script} met [{requires}]", None

    if kind == "json_field":
        # Freshness of a file proves a WRITE happened; it does not prove the write meant
        # anything. This kind filters on content first: only records matching `where`
        # count. It exists because the first draft of this registry scored the RSI loop
        # PRODUCING off pol-auto-*.json mtimes while all 13 of those policies were
        # provisional and none had ever taken effect — the same output-volume-as-health
        # mistake the estate's own signals were making.
        pattern = obs.get("path")
        if not pattern:
            return None, "", "json_field observable has no path"
        where = obs.get("where") or {}
        ts_field = obs.get("timestamp_field")
        best_t, best_p, scanned = None, None, 0
        for p in glob.glob(_resolve(pattern)):
            scanned += 1
            try:
                with open(p) as fh:
                    rec = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(rec, dict):
                continue
            if any(str(rec.get(k)) != str(v) for k, v in where.items()):
                continue
            try:
                t = _normalise_epoch(rec.get(ts_field)) if ts_field else os.path.getmtime(p)
            except (ValueError, OSError):
                t = None
            if t is None:
                try:
                    t = os.path.getmtime(p)
                except OSError:
                    continue
            if best_t is None or t > best_t:
                best_t, best_p = t, p
        if best_t is None:
            cond = ", ".join(f"{k}={v}" for k, v in where.items()) or "any"
            return None, f"{scanned} file(s) matched {pattern}, 0 satisfied [{cond}]", None
        return best_t, os.path.basename(best_p), None

    if kind == "sqlite":
        db = _resolve(obs.get("db", ""))
        query = obs.get("query", "")
        if not os.path.exists(db):
            return None, "", f"db not found: {db}"
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            try:
                row = conn.execute(query).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return None, "", f"query failed: {exc}"
        raw = row[0] if row else None
        if raw is None:
            return None, "query returned no rows", None
        try:
            return _normalise_epoch(raw), f"row value {raw!r}", None
        except ValueError as exc:
            return None, "", str(exc)

    return None, "", f"unknown observable kind: {kind!r}"


_RECEIPTS_SINCE: float | None | str = "unset"


def receipts_since() -> float | None:
    """Epoch of the OLDEST receipt — i.e. when receipt instrumentation began.

    A receipt-kind capability produces evidence only when its job next runs. Cron
    instrumentation landed 2026-08-05 ~00:00; a daily job therefore has no receipt
    for up to 24h and a weekly one for up to 7d, through no fault of its own.
    Scoring those DARK made 11 of 17 DARK rows false on the first audit, and the
    hourly watchdog would have Telegrammed that same false set 24x/day. An alarm
    that is mostly wrong and always repeating is one that gets muted — which is
    exactly how otto-dispatch sat disabled for 46 days. Returns None when no
    receipt exists at all (nothing has been observed yet).
    """
    global _RECEIPTS_SINCE
    if _RECEIPTS_SINCE != "unset":
        return _RECEIPTS_SINCE  # type: ignore[return-value]
    path = os.path.join(HOME, "state", "capability_receipts.jsonl")
    oldest = None
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("ended_at")
                if isinstance(t, (int, float)) and (oldest is None or t < oldest):
                    oldest = t
    except OSError:
        oldest = None
    _RECEIPTS_SINCE = oldest
    return oldest


def _classify(last: float | None, period_s: float, now: float) -> tuple[str, float | None]:
    if last is None:
        return "DARK", None
    age = now - last
    if age <= period_s * 1.5:
        return "PRODUCING", age
    if age <= period_s * 3:
        return "STALE", age
    return "DARK", age


def audit_capabilities(reg: dict, now: float) -> list[dict]:
    out = []
    for cap in reg.get("capabilities", []):
        period = float(cap.get("period_s") or 86400)
        last, detail, err = _observe(cap)
        if err:
            verdict, age = "BROKEN", None
            detail = err
        elif (cap.get("observable") or {}).get("kind", "none") == "none":
            verdict, age = "UNPROVEN", None
        else:
            verdict, age = _classify(last, period, now)
            # Not-yet-observed is not the same claim as not-producing. Only a
            # receipt-kind capability can be in this state: file/sqlite/json_field
            # observables read history that predates the probe, so absence there is
            # real. See receipts_since() for why this distinction had to exist.
            if (
                verdict == "DARK"
                and last is None
                and (cap.get("observable") or {}).get("kind") == "receipt"
            ):
                since = receipts_since()
                # A capability added TODAY is not covered by the global instrumentation
                # epoch. receipts_since() is estate-wide (2026-08-05); by 2026-08-07 it
                # is 56h old, past the 36h grace of any daily capability, so every newly
                # registered daily job would read DARK the moment it was declared and
                # stay that way until it next ran — up to 24h of alarm about a job with
                # nothing wrong with it. Ten launchd capabilities were registered at once
                # on 2026-08-07, which would have been ten such rows in one delivery.
                # instrumented_at gives each capability its own clock from the moment it
                # joined the layer; it only ever DELAYS a DARK verdict, never hides one,
                # because it is bounded by the same period * 1.5 as everything else.
                cap_since = cap.get("instrumented_at")
                if isinstance(cap_since, (int, float)):
                    since = cap_since if since is None else max(since, cap_since)
                watched = (now - since) if since is not None else 0.0
                if watched < period * 1.5:
                    verdict = "WARMING"
                    detail = (
                        f"{detail} — instrumented {_fmt_age(watched)} ago, "
                        f"under the {_fmt_age(period)} period; not yet due"
                    )
        out.append(
            {
                "id": cap.get("id"),
                "what": cap.get("what", ""),
                "owner": cap.get("owner", ""),
                "verdict": verdict,
                "age_s": age,
                "period_s": period,
                "detail": detail,
                "note": cap.get("note"),
            }
        )
    return out


def _load_jobs() -> list[dict]:
    try:
        with open(JOBS) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        for key in ("jobs", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return list(data.values()) if all(isinstance(v, dict) for v in data.values()) else []
    return data if isinstance(data, list) else []


def audit_latches(reg: dict, now: float) -> list[dict]:
    out = []
    for latch in reg.get("latches", []):
        kind = latch.get("kind")
        max_age = float(latch.get("max_age_s") or 86400)
        held: list[tuple[str, float | None]] = []
        err = None

        if kind == "file_exists":
            p = _resolve(latch.get("path", ""))
            if os.path.exists(p):
                try:
                    held.append((os.path.basename(p), now - os.path.getmtime(p)))
                except OSError as exc:
                    err = str(exc)

        elif kind == "cron_disabled":
            for job in _load_jobs():
                # A job someone deliberately RETIRED is not a latch. Two of the three
                # jobs this branch escalated on 2026-08-05 were retirements with the
                # reason written down ("superseded by repo-health-check.py"), and
                # re-reporting a settled decision every hour forever is how an alarm
                # gets muted — at which point the one genuine latch in that same list
                # (otto-dispatch: 46d, no reason recorded, and it was the last hop of
                # the estate's entire alert chain) rides along unnoticed.
                # Retiring is explicit and auditable: state=retired + retired_reason.
                if job.get("state") == "retired":
                    continue
                if job.get("enabled") is False:
                    try:
                        age = now - _normalise_epoch(job.get("disabled_at") or job.get("last_run_at"))
                    except (ValueError, TypeError):
                        age = None
                    held.append((str(job.get("name") or job.get("id")), age))

        elif kind == "cron_never_ran":
            for job in _load_jobs():
                if job.get("enabled") is False or job.get("last_run_at"):
                    continue
                name = str(job.get("name") or job.get("id"))
                # A job registered a minute ago has not "gone silent" — it has not had a
                # chance to run. Without this the probe escalates every new job the
                # instant it is added, including itself, and a checker that cries wolf
                # about its own installation is one nobody will keep listening to.
                #
                # `registered_at` alone could not deliver that, because NOTHING WRITES IT:
                # on 2026-08-06 a grep found this line to be its only mention estate-wide.
                # The damage was not the skipped `continue` below (which merely duplicates
                # the threshold) but the resulting UNKNOWN age: `breached` counts h[1] is
                # None as held-too-long, deliberately, so an unmeasurable hold cannot hide.
                # An always-None age therefore latched every new job the instant it existed.
                # The bug proved itself on installation — registering delivery-canary
                # latched it as "never fired" within the minute. cron/jobs.py:create_job
                # does set `created_at`, which answers the same question, so fall back to it.
                registered = None
                for field in ("registered_at", "created_at"):
                    try:
                        registered = _normalise_epoch(job.get(field))
                    except (ValueError, TypeError):
                        registered = None
                    if registered is not None:
                        break
                if registered is not None and (now - registered) < max_age:
                    continue
                # Age is measured from registration where known, so the escalation says
                # how long the silence has actually lasted rather than just "never".
                held.append((name, (now - registered) if registered else None))

        elif kind == "breaker_open":
            for p in glob.glob(_resolve(latch.get("path", ""))):
                try:
                    with open(p) as fh:
                        st = json.load(fh)
                except (OSError, json.JSONDecodeError):
                    continue
                state = str(st.get("state", "")).lower()
                if state == "open":
                    try:
                        age = now - _normalise_epoch(
                            st.get("opened_at") or st.get("last_failure_at") or os.path.getmtime(p)
                        )
                    except (ValueError, TypeError):
                        age = None
                    held.append((os.path.basename(p), age))
        else:
            err = f"unknown latch kind: {kind!r}"

        # A latch held with no known start is not exonerated by the missing timestamp —
        # an unmeasurable hold is the same silence this probe exists to surface.
        breached = [h for h in held if h[1] is None or h[1] > max_age]
        out.append(
            {
                "id": latch.get("id"),
                "what": latch.get("what", ""),
                "verdict": "BROKEN" if err else ("LATCHED" if breached else "OK"),
                "held": held,
                "breached": breached,
                "max_age_s": max_age,
                "detail": err or "",
                "note": latch.get("note"),
            }
        )
    return out


def audit_job_integrity() -> list[dict]:
    """Structural faults that make a job unrunnable without ever raising an error.

    Added 2026-08-06 after I registered reliability-watchdog with schedule as a bare
    string "0 * * * *" instead of {"kind": "cron", ...}. compute_next_run does
    schedule["kind"] (cron/jobs.py:464), which raises TypeError on a string, so the
    job could never be rescheduled. It sat enabled, with a next_run_at in the past,
    and simply never ran — no exception surfaced, no alert, nothing. The cron_never_ran
    latch would have caught it eventually, but only after its grace window; a
    structural fault is knowable immediately and should not wait on a timeout.

    Returns one row per fault. Empty list means every enabled job is well-formed.
    """
    faults = []
    for job in _load_jobs():
        name = str(job.get("name") or job.get("id") or "?")
        if job.get("enabled") is False or job.get("state") == "retired":
            continue
        sched = job.get("schedule")
        if not isinstance(sched, dict):
            faults.append({"job": name, "fault": f"schedule is {type(sched).__name__}, "
                                                 "not a dict — compute_next_run will raise"})
        elif not sched.get("kind"):
            faults.append({"job": name, "fault": "schedule has no 'kind'"})
        # no_agent jobs run a script; an agent job legitimately has script=None.
        if job.get("no_agent") and not job.get("script"):
            faults.append({"job": name, "fault": "no_agent=True but no script set"})
    return faults


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    args = ap.parse_args()

    try:
        with open(REGISTRY) as fh:
            reg = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ capability registry unreadable: {exc}", file=sys.stderr)
        return 2

    now = time.time()
    caps = audit_capabilities(reg, now)
    latches = audit_latches(reg, now)
    faults = audit_job_integrity()

    failing = [c for c in caps if c["verdict"] in FAIL_VERDICTS]
    failing_latches = [l for l in latches if l["verdict"] in FAIL_VERDICTS]

    if args.json:
        print(json.dumps({"generated_at": now, "capabilities": caps,
                          "latches": latches, "job_faults": faults}, indent=2))
        return 1 if (failing or failing_latches or faults) else 0

    print("=" * 78)
    print("CAPABILITY AUDIT — what the estate PRODUCED, not what ran")
    print("=" * 78)

    order = ["DARK", "BROKEN", "UNPROVEN", "STALE", "WARMING", "PRODUCING"]
    for verdict in order:
        rows = [c for c in caps if c["verdict"] == verdict]
        if not rows or (args.quiet and verdict not in FAIL_VERDICTS):
            continue
        print(f"\n{MARK[verdict]} {verdict}  ({len(rows)})")
        for c in rows:
            age = _fmt_age(c["age_s"])
            expect = _fmt_age(c["period_s"])
            print(f"   {c['id']:<30} last={age:<7} expected≤{expect:<6} {c['what']}")
            if c["detail"]:
                print(f"   {'':<30} └─ {c['detail']}")

    print("\n" + "-" * 78)
    print("LATCHES — automatic trip, manual recovery, no expiry")
    print("-" * 78)
    for l in latches:
        if args.quiet and l["verdict"] not in FAIL_VERDICTS:
            continue
        print(f"{MARK[l['verdict']]} {l['id']:<28} held={len(l['held'])} "
              f"breached={len(l['breached'])} max={_fmt_age(l['max_age_s'])}")
        for name, age in l["breached"]:
            print(f"      🔒 {name} — held {_fmt_age(age)}")
        if l["detail"]:
            print(f"      └─ {l['detail']}")

    if faults:
        print("\n" + "=" * 78)
        print("JOB INTEGRITY — structurally unrunnable, will never raise an error")
        print("=" * 78)
        for f in faults:
            print(f"💥 {f['job']:<28} {f['fault']}")

    counts = {v: sum(1 for c in caps if c["verdict"] == v) for v in order}
    print("\n" + "=" * 78)
    print("  ".join(f"{v}={counts[v]}" for v in order))
    if failing or failing_latches or faults:
        print(f"❌ NOT PROVEN: {len(failing)} capabilities, "
              f"{len(failing_latches)} latches breached, {len(faults)} job faults")
        return 1
    print("✅ every capability proven producing; no latch past its window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
