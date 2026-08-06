#!/usr/bin/env python3
"""delivery_canary — proves that an estate alert actually REACHES the founder.

Why the obvious design is worthless
-----------------------------------
The tempting canary is "call the Telegram API, assert 200". That probe would have
been green on every one of the 46 days otto-dispatch sat disabled, because the
credentials and the network were never the fault — a RELAY was off. Everything the
estate watches is production ("did the job make a file"); nothing watched delivery,
so the one link that had failed was the one link nobody measured.

So this canary is deliberately not a self-contained send. It is a cron job, and it
rides the exact path a real alert rides:

    cron scheduler tick
      -> runs this script (no_agent: stdout is delivered verbatim,
         cron/scheduler.py:1409-1412)
      -> _deliver_result() -> telegram home channel
      -> mark_job_run(..., delivery_error=...) writes the outcome back onto the
         job record (cron/jobs.py:958-978, cleared to None on success)

Each hop is then proven by a DIFFERENT run:

  * that the relay RAN at all      -> this script executing produces a fresh receipt
  * that its message ARRIVED       -> the NEXT run reads last_delivery_error on its
                                      own job record and sees it cleared

That one-run lag is the point. Nothing here trusts its own report of success; the
proof of week N is written in week N+1, by reading state the delivery machinery wrote,
not state this script wrote.

Breaking the circularity
------------------------
An alarm about a broken alert channel cannot be delivered over the broken alert
channel. So this writes state/delivery_proof.json on every run and verify_estate.sh
reads its age — a PULL check of a PUSH channel, which the founder runs by hand and
which needs no delivery to be seen.

Exit codes: 0 = proven (or first run, honestly recorded as not yet proven).
            1 = the previous message did not arrive, or it is going somewhere the
                estate does not consider the founder's channel.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
JOBS = HOME / "cron" / "jobs.json"
PROOF = HOME / "state" / "delivery_proof.json"

JOB_NAME = "delivery-canary"

# One a week. This message is a real Telegram to a human; at hourly cadence the
# canary itself becomes the noise that trains the founder to mute the channel, which
# is the failure it exists to prevent.
PERIOD_S = 7 * 86400


def _load_jobs() -> list[dict]:
    with open(JOBS) as fh:
        data = json.load(fh)
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    return [j for j in jobs if isinstance(j, dict)]


def _home_channel() -> str | None:
    """The chat the ESTATE considers the founder, read from config, not from us.

    Delivery to a channel nobody reads is not delivery. If the canary's own origin
    ever diverges from the configured home channel, a green canary would be proving
    arrival somewhere irrelevant — so a mismatch is a failure, not a warning.
    """
    for key in ("TELEGRAM_HOME_CHANNEL", "TELEGRAM_HOME_CHAT_ID"):
        val = os.environ.get(key)
        if val:
            return val.strip()
    env = HOME / ".env"
    try:
        for line in env.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_HOME_CHANNEL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def _parse_iso(value: str | None) -> float | None:
    if not isinstance(value, str) or len(value) < 19:
        return None
    try:
        return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


# A delivery error stays on a job record until that job next delivers successfully,
# so a monthly job can carry one for weeks after the channel healed. Only count
# failures recent enough to still be news.
PEER_WINDOW_S = 14 * 86400


def peer_delivery_failures(jobs: list[dict], now: float) -> list[dict]:
    """Every OTHER job whose last delivery to the founder failed, recently.

    The canary alone would detect a broken channel a week late. But the estate
    already runs a dozen jobs that deliver to origin daily, and cron/jobs.py:978 has
    been recording each one's delivery outcome the whole time with no reader — the
    same dead-end shape as missed_runs.jsonl and queue/pending-digest.json. Reading
    them here turns existing traffic into near-daily coverage at no extra message.
    """
    out = []
    for j in jobs:
        if j.get("name") == JOB_NAME or j.get("deliver") != "origin":
            continue
        err = j.get("last_delivery_error")
        if not err:
            continue
        ts = _parse_iso(j.get("last_run_at"))
        if ts is not None and now - ts > PEER_WINDOW_S:
            continue
        out.append({"job": j.get("name") or j.get("id"),
                    "error": str(err)[:200], "at": j.get("last_run_at")})
    return sorted(out, key=lambda r: str(r["job"]))


def _write_proof(rec: dict) -> None:
    try:
        PROOF.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROOF.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, PROOF)
    except OSError as exc:
        # The proof file IS the pull-side signal; losing it silently would make the
        # channel look unproven forever, so say so on stdout where it gets delivered.
        print(f"delivery-canary: could not write {PROOF}: {exc}")


def assess(job: dict | None, now: float, home_chat: str | None) -> tuple[dict, int]:
    """Return (proof record, exit code). Pure — the tests drive this directly."""
    stamp = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(now))

    if job is None:
        return ({
            "checked_at": now, "verified": False, "reason": "job-missing",
            "detail": f"no cron job named {JOB_NAME!r} — the canary cannot ride a relay "
                      "that is not registered",
        }, 1)

    origin = (job.get("origin") or {}).get("chat_id")
    origin = str(origin) if origin is not None else None

    if job.get("deliver") != "origin":
        return ({
            "checked_at": now, "verified": False, "reason": "not-delivered",
            "detail": f"job deliver={job.get('deliver')!r}; output goes to a file, so "
                      "nothing about the founder's channel is being tested",
        }, 1)

    if home_chat and origin and origin != home_chat:
        return ({
            "checked_at": now, "verified": False, "reason": "wrong-channel",
            "detail": f"canary delivers to {origin} but the estate's home channel is "
                      f"{home_chat} — a green canary would prove arrival somewhere "
                      "the founder does not read",
        }, 1)

    last_run = job.get("last_run_at")
    if not last_run:
        return ({
            "checked_at": now, "verified": False, "reason": "first-run",
            "detail": "first run — this message is the one under test; arrival is "
                      "confirmed by the next run reading last_delivery_error",
            "chat_id": origin,
        }, 0)

    err = job.get("last_delivery_error")
    if err:
        return ({
            "checked_at": now, "verified": False, "reason": "delivery-failed",
            "detail": f"the {last_run} canary did not reach the founder: {err}",
            "chat_id": origin, "attempted_at": last_run,
        }, 1)

    return ({
        "checked_at": now, "verified": True, "reason": "arrived",
        "detail": f"the {last_run} canary was accepted by the delivery path with no "
                  "error recorded",
        "chat_id": origin, "delivered_at": last_run,
        "route": "cron tick -> no_agent stdout -> _deliver_result -> telegram",
        "stamp": stamp,
    }, 0)


def main() -> int:
    now = time.time()
    try:
        jobs = _load_jobs()
    except (OSError, json.JSONDecodeError) as exc:
        _write_proof({"checked_at": now, "verified": False, "reason": "jobs-unreadable",
                      "detail": str(exc)})
        print(f"🚨 delivery-canary: cannot read {JOBS}: {exc}")
        return 1

    job = next((j for j in jobs if j.get("name") == JOB_NAME), None)
    rec, code = assess(job, now, _home_channel())

    peers = peer_delivery_failures(jobs, now)
    if peers:
        # A peer failure is evidence the channel is broken NOW, which outranks this
        # canary's report about last week.
        rec["verified"] = False
        rec["peer_failures"] = peers
        code = 1
    _write_proof(rec)

    # Stdout is never empty: the scheduler only attempts delivery when there is
    # something to deliver, so a silent success would leave last_delivery_error
    # untouched and the NEXT run would read a stale None as fresh proof.
    if rec["verified"]:
        print(f"🐤 delivery canary — the alert channel to you is proven working "
              f"(previous canary {rec['delivered_at']} arrived). "
              f"Next check in {PERIOD_S // 86400}d.")
    elif code == 0:
        # Not yet proven is not an emergency. Dressing it as one is how the founder
        # learns that this emoji means nothing.
        print(f"🐣 delivery canary [{rec['reason']}] — {rec['detail']}")
    else:
        print(f"🚨 delivery canary [{rec['reason']}] — {rec['detail']}")
    for p in rec.get("peer_failures", []):
        print(f"   ↳ {p['job']} failed to deliver at {p['at']}: {p['error']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
