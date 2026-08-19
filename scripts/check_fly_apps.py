#!/usr/bin/env python3
"""Grade the estate's Fly apps against ~/.hermes/config/fly_apps_expected.tsv.

Called by verify_estate.sh. Prints one line per finding and exits 1 if anything is a fault,
0 otherwise, 2 if it could not establish an answer at all.

Why a separate file rather than more bash in the probe: this needs JSON, and it needs to be
testable without a Fly account. Every external call goes through fly_json(), which reads a
fixture directory instead when FLY_FIXTURES is set. A check that can only be exercised against
live production is a check nobody runs before shipping it.

Three verdicts, kept distinct on purpose:

  fault           the estate is wrong and someone must act.
  cannot-establish  the probe could not get an answer -- no fly CLI, no network, not logged in.
                  This is NOT green. It exits 2 and the caller decides. An outage in the
                  measuring instrument that reports as "all clear" is the failure mode this
                  whole file exists to avoid (memory: measurement-stops-during-the-outage).
  ok              measured, and matches the declaration.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DECLARATION = Path.home() / ".hermes" / "config" / "fly_apps_expected.tsv"
#: fly is not on launchd's default PATH; the probe may run from a launchd job.
FLY_TIMEOUT_S = 30


class CannotEstablish(Exception):
    """The probe could not get an answer. Never a pass, never a fault."""


def fly_json(args: list[str], fixture: str) -> object:
    """Run `fly <args> --json`, or read a fixture when FLY_FIXTURES is set.

    The fixture escape hatch is what makes the tests real: they exercise this exact parsing
    and grading code, not a copy of it.
    """
    fixtures = os.environ.get("FLY_FIXTURES")
    if fixtures:
        path = Path(fixtures) / f"{fixture}.json"
        if not path.exists():
            raise CannotEstablish(f"fixture missing: {path}")
        return json.loads(path.read_text())
    try:
        proc = subprocess.run(["fly", *args, "--json"], capture_output=True,
                              text=True, timeout=FLY_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise CannotEstablish("the `fly` CLI is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CannotEstablish(f"`fly {' '.join(args)}` did not answer in {FLY_TIMEOUT_S}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise CannotEstablish(f"`fly {' '.join(args)}` exited {proc.returncode}: "
                              f"{detail[-1] if detail else 'no output'}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CannotEstablish(f"`fly {' '.join(args)}` did not return JSON") from exc


def load_declaration(path: Path) -> dict[str, dict]:
    """Parse the TSV. A row with no reason is not a declaration -- see the launchd allow file
    for the same rule and the same reason: one person typing a name is not a decision."""
    if not path.exists():
        raise CannotEstablish(f"no declaration at {path}")
    out: dict[str, dict] = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 4 or not parts[3].strip():
            raise CannotEstablish(f"{path}:{lineno} needs app, expect, max_deploy_h and a reason")
        app, expect, max_h, reason = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        if expect not in ("running", "suspended"):
            raise CannotEstablish(f"{path}:{lineno} expect must be running or suspended, got {expect!r}")
        try:
            hours = float(max_h)
        except ValueError as exc:
            raise CannotEstablish(f"{path}:{lineno} max_deploy_h must be a number, got {max_h!r}") from exc
        out[app] = {"expect": expect, "max_deploy_h": hours, "reason": reason}
    if not out:
        raise CannotEstablish(f"{path} declares no apps; an empty declaration grades nothing")
    return out


def _deploy_age_hours(app: dict) -> float | None:
    release = app.get("Release") or {}
    stamp = release.get("CreatedAt") or app.get("LatestDeploy")
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600.0


def grade() -> tuple[list[str], int]:
    """Returns (lines, faults)."""
    declared = load_declaration(Path(os.environ.get("FLY_DECLARATION") or DECLARATION))
    listing = fly_json(["apps", "list"], "apps")
    if not isinstance(listing, list):
        raise CannotEstablish("`fly apps list --json` did not return a list")

    live = {a.get("Name"): a for a in listing if isinstance(a, dict) and a.get("Name")}
    lines: list[str] = []
    faults = 0

    for name in sorted(set(declared) | set(live)):
        want = declared.get(name)
        app = live.get(name)

        if want is None:
            lines.append(f"  \u274c {name} is running on the account and nothing declares it "
                         f"\u2014 add it to {DECLARATION.name} or delete the app")
            faults += 1
            continue
        if app is None:
            lines.append(f"  \u274c {name} is declared but does not exist on the account "
                         f"\u2014 {want['reason']}")
            faults += 1
            continue

        status = (app.get("Status") or "").lower()
        if want["expect"] == "suspended":
            if status == "suspended":
                lines.append(f"  \U0001f7e1 {name} suspended, on purpose: {want['reason']}")
            else:
                lines.append(f"  \u274c {name} is declared suspended but reads {status!r} "
                             f"\u2014 a parked app that woke up is spending money")
                faults += 1
            continue

        if status != "deployed":
            lines.append(f"  \u274c {name} reads {status or 'unknown'!r}, not deployed \u2014 {want['reason']}")
            faults += 1
            continue

        machines = fly_json(["machines", "list", "--app", name], f"machines-{name}")
        if not isinstance(machines, list):
            raise CannotEstablish(f"`fly machines list --app {name}` did not return a list")
        stopped = [m.get("id") for m in machines
                   if isinstance(m, dict) and (m.get("state") or "").lower() != "started"]
        if not machines:
            lines.append(f"  \u274c {name} is deployed but has no machines \u2014 {want['reason']}")
            faults += 1
            continue
        if stopped:
            states = ", ".join(f"{m.get('id')}={m.get('state')}" for m in machines
                               if isinstance(m, dict) and (m.get("state") or "").lower() != "started")
            lines.append(f"  \u274c {name} has {len(stopped)} of {len(machines)} machines not started "
                         f"({states}) \u2014 {want['reason']}")
            faults += 1
            continue

        age = _deploy_age_hours(app)
        ceiling = want["max_deploy_h"]
        # A ceiling that cannot be measured must not read as "under the ceiling". `fly apps
        # list --json` returns Release: null for most apps, so age is usually None here; if a
        # ceiling is ever set without a deploy timestamp to grade it against, that is a check
        # silently doing nothing, which is the exact defect this file was written to catch.
        if ceiling > 0 and age is None:
            raise CannotEstablish(
                f"{name} declares a {ceiling:.0f}h deploy-age ceiling but the listing carries no "
                f"deploy timestamp; grading it would be a check that never fires")
        if ceiling > 0 and age > ceiling:
            lines.append(f"  \u274c {name} last deployed {age:.1f}h ago, ceiling {ceiling:.0f}h "
                         f"\u2014 the pipeline that redeploys it has stopped")
            faults += 1
            continue

        shown = f"{len(machines)} machine{'s' if len(machines) != 1 else ''} started"
        if age is not None:
            shown += f", deployed {age:.1f}h ago"
        lines.append(f"  \u2705 {name} {shown}")

    return lines, faults


def main() -> int:
    print("FLY  apps this estate depends on")
    try:
        lines, faults = grade()
    except CannotEstablish as exc:
        print(f"  \u26a0\ufe0f  cannot establish: {exc}")
        print("     This is not a pass. Nothing above was measured.")
        return 2
    for line in lines:
        print(line)
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
