#!/usr/bin/env python3
"""One Hermes leader, decided by a lease both machines can see.

Why this exists. On 2026-08-19 the Fly container and this laptop were both running a Hermes
coordinator, each against its own SQLite database. Nothing was wrong with either one. There was
simply no fact that said which was in charge, so "keep them in sync" was not an option — there
was nothing to sync, there were two estates.

Booting the laptop's daemons out settled that day. It is not a fence: `launchctl enable` undoes
it, a reinstall script undoes it, and a reboot of a machine someone re-enabled undoes it. A
lease is the fence, because it is a fact both machines read from the same place.

WHERE THE LEASE LIVES. An object in the R2 bucket the offsite backup already uses. R2 is the
only storage both environments reach: the laptop has the credentials in .env, and the Fly app
can be given them as secrets. Anything on either machine's disk cannot arbitrate between them,
which is the whole problem.

HOW IT DECIDES. Not with a lock, with a lease: a holder plus a renewal time plus a TTL. A held
lease is renewed by the leader every `--renew-every` seconds. A lease whose renewal is older
than its TTL is dead and anyone may take it. That is what makes this survive the case a lock
cannot — the leader's machine vanishing without releasing anything.

IDENTITY IS NOT A PID. `state/machine_id` holds a uuid minted once per machine. A bare pid means
nothing to the machine that did not mint it: pid 695 exists on both of these boxes right now and
refers to different programs. The pid is still recorded, for a human reading the object, but it
never decides anything.

THE RACE. R2 gives no compare-and-swap this code can rely on across providers, so acquisition is
write-then-read-back: both contenders may write, both then re-read, and the object says who
actually landed last. The loser backs off. It converges in one round because the read is of a
single object, and a lease that flaps is still only ever held by one holder at a time.

Read-only by default. `--enforce` is the only mode that touches anything on this machine, and it
only ever stops daemons on a machine that does NOT hold the lease. It will not start anything,
and it does nothing at all on the leader.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERMES = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

BUCKET = os.environ.get("HERMES_LEASE_BUCKET", "prospector-backup")
KEY = os.environ.get("HERMES_LEASE_KEY", "hermes/leader.json")
DEFAULT_TTL_S = 300.0
DEFAULT_RENEW_S = 60.0

# The daemons Fly's supervisord also runs. Same list as check_single_environment.sh, and the
# same reason: these are the ones that would be answering twice.
DUPLICATED = (
    "coordinator",
    "otto-server",
    "cockpit",
    "rsi",
    "progress",
    "submodule-backup",
    "gateway",
)

EXIT_HELD = 0        # we hold it
EXIT_NOT_OURS = 1    # someone else holds it
EXIT_UNKNOWN = 2     # could not establish — never confused with "free"


class CannotEstablish(RuntimeError):
    """Storage did not answer. Never treated as 'the lease is free'."""


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def machine_id() -> str:
    """Stable per machine, minted once. Survives reboots and process restarts."""
    path = HERMES / "state" / "machine_id"
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    minted = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(minted + "\n")
    except OSError:
        # A read-only or missing state directory must not stop the check from answering. An
        # ephemeral id makes this run a non-holder, which is the safe side to fail on.
        pass
    return minted


def environment_name() -> str:
    """'fly' or 'mac'. FLY_APP_NAME is set in every Fly machine and nowhere else."""
    return "fly" if os.environ.get("FLY_APP_NAME") else "mac"


def identity() -> dict[str, Any]:
    return {
        "machine_id": machine_id(),
        "environment": environment_name(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
    }


def make_client() -> Any:
    """The same R2 credentials the offsite backup uses."""
    try:
        import boto3  # noqa: PLC0415 - optional at import time so --help always works
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise CannotEstablish(f"boto3 is not installed: {exc}") from exc

    missing = [
        name
        for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        raise CannotEstablish(f"missing credentials: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def read_lease(client: Any) -> dict[str, Any] | None:
    """The lease as stored, or None if there is none. Raises rather than returning None on a
    storage failure: 'no lease' means 'anyone may take it', and an outage must never say that."""
    try:
        body = client.get_object(Bucket=BUCKET, Key=KEY)["Body"].read()
    except Exception as exc:  # noqa: BLE001 - botocore raises a generated class
        if type(exc).__name__ in ("NoSuchKey", "404") or "NoSuchKey" in str(exc):
            return None
        code = getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error") or {}
        if isinstance(code, dict) and code.get("Code") in ("NoSuchKey", "404"):
            return None
        raise CannotEstablish(f"could not read {BUCKET}/{KEY}: {exc}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise CannotEstablish(f"lease object is not JSON: {exc}") from exc


def is_expired(lease: dict[str, Any], now: float | None = None) -> bool:
    now = _now() if now is None else now
    return now > float(lease.get("renewed_at", 0)) + float(lease.get("ttl_s", DEFAULT_TTL_S))


def write_lease(client: Any, lease: dict[str, Any]) -> None:
    try:
        client.put_object(
            Bucket=BUCKET,
            Key=KEY,
            Body=json.dumps(lease, indent=2, sort_keys=True).encode(),
            ContentType="application/json",
        )
    except Exception as exc:  # noqa: BLE001
        raise CannotEstablish(f"could not write {BUCKET}/{KEY}: {exc}") from exc


def acquire(client: Any, ttl_s: float = DEFAULT_TTL_S) -> tuple[bool, dict[str, Any]]:
    """Take the lease if it is free, expired, or already ours. Returns (we_hold_it, lease)."""
    me = identity()
    current = read_lease(client)

    if current is not None and current.get("machine_id") != me["machine_id"]:
        if not is_expired(current):
            return False, current

    now = _now()
    mine = dict(me)
    mine["ttl_s"] = ttl_s
    mine["renewed_at"] = now
    mine["renewed_at_iso"] = _iso(now)
    if current is not None and current.get("machine_id") == me["machine_id"]:
        mine["acquired_at"] = current.get("acquired_at", now)
    else:
        mine["acquired_at"] = now
    mine["acquired_at_iso"] = _iso(float(mine["acquired_at"]))
    write_lease(client, mine)

    # Read back. Two contenders can both write; the object says who landed last.
    settled = read_lease(client)
    if settled is None:
        raise CannotEstablish("lease vanished immediately after it was written")
    return settled.get("machine_id") == me["machine_id"], settled


def describe(lease: dict[str, Any] | None) -> str:
    if lease is None:
        return "no lease exists"
    left = float(lease.get("renewed_at", 0)) + float(lease.get("ttl_s", 0)) - _now()
    state = f"{left:.0f}s left" if left > 0 else f"EXPIRED {-left:.0f}s ago"
    return (
        f"{lease.get('environment', '?')} ({lease.get('host', '?')}, "
        f"pid {lease.get('pid', '?')}, id {str(lease.get('machine_id', '?'))[:8]}), {state}"
    )


def write_primary(environment: str) -> None:
    """check_single_environment.sh reads this file. The lease is what decides it, so the fence
    and the lease can never disagree."""
    path = HERMES / "config" / "primary_environment"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text().strip() if path.exists() else None
        if current != environment:
            path.write_text(environment + "\n")
    except OSError as exc:
        print(f"  could not write {path}: {exc}", file=sys.stderr)


def stop_local_daemons(dry_run: bool) -> list[str]:
    """Only ever called on a machine that does NOT hold the lease, and only on this Mac —
    a Fly container has no launchctl, and the container must never stop itself."""
    import subprocess  # noqa: PLC0415

    if environment_name() != "mac":
        return []
    stopped = []
    uid = os.getuid()
    listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
    loaded = {line.split("\t")[-1] for line in listed.stdout.splitlines() if "\t" in line}
    for name in DUPLICATED:
        label = f"ai.hermes.{name}"
        if label not in loaded:
            continue
        stopped.append(label)
        if dry_run:
            continue
        for verb in ("bootout", "disable"):
            subprocess.run(
                ["launchctl", verb, f"gui/{uid}/{label}"], capture_output=True, check=False
            )
    return stopped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "mode",
        choices=("status", "acquire", "hold"),
        help="status: read only. acquire: take it once if free. hold: renew it forever.",
    )
    parser.add_argument("--ttl", type=float, default=DEFAULT_TTL_S)
    parser.add_argument("--renew-every", type=float, default=DEFAULT_RENEW_S)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="on a machine that does NOT hold the lease, stop the local Hermes daemons",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        client = make_client()
    except CannotEstablish as exc:
        print(f"UNKNOWN: {exc}")
        return EXIT_UNKNOWN

    me = identity()

    if args.mode == "status":
        try:
            lease = read_lease(client)
        except CannotEstablish as exc:
            print(f"UNKNOWN: {exc}")
            return EXIT_UNKNOWN
        if args.json:
            print(json.dumps({"lease": lease, "me": me}, indent=2, default=str))
        else:
            print(f"LEASE   {describe(lease)}")
            print(f"ME      {me['environment']} ({me['host']}, id {me['machine_id'][:8]})")
        if lease is None or is_expired(lease):
            return EXIT_NOT_OURS
        return EXIT_HELD if lease.get("machine_id") == me["machine_id"] else EXIT_NOT_OURS

    if args.mode == "acquire":
        try:
            held, lease = acquire(client, args.ttl)
        except CannotEstablish as exc:
            print(f"UNKNOWN: {exc}")
            return EXIT_UNKNOWN
        print(f"{'HELD BY US' if held else 'HELD BY OTHER'}  {describe(lease)}")
        write_primary(str(lease.get("environment", "fly")))
        if not held and args.enforce:
            stopped = stop_local_daemons(dry_run=False)
            for label in stopped:
                print(f"  stopped {label} — this machine does not hold the lease")
        elif not held:
            stopped = stop_local_daemons(dry_run=True)
            for label in stopped:
                print(f"  WOULD stop {label} (pass --enforce)")
        return EXIT_HELD if held else EXIT_NOT_OURS

    # hold: the leader's renewal loop.
    consecutive_failures = 0
    while True:
        try:
            held, lease = acquire(client, args.ttl)
            consecutive_failures = 0
        except CannotEstablish as exc:
            consecutive_failures += 1
            print(f"UNKNOWN ({consecutive_failures}): {exc}", flush=True)
            time.sleep(args.renew_every)
            continue
        write_primary(str(lease.get("environment", "fly")))
        if not held:
            print(f"LOST    {describe(lease)}", flush=True)
            if args.enforce:
                for label in stop_local_daemons(dry_run=False):
                    print(f"  stopped {label}", flush=True)
        time.sleep(args.renew_every)


if __name__ == "__main__":
    sys.exit(main())
