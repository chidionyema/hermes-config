"""The lease must decide one leader, and must never decide one during an outage.

No network and no credentials: the R2 client is faked. What is being tested is the decision,
not boto3.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERMES = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("hermes_lease", HERMES / "scripts" / "hermes_lease.py")
lease_mod = importlib.util.module_from_spec(_spec)
sys.modules["hermes_lease"] = lease_mod
_spec.loader.exec_module(lease_mod)


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class NoSuchKey(Exception):
    pass


class FakeR2:
    """One object, and a switch that makes it fail like a real outage."""

    def __init__(self) -> None:
        self.obj: bytes | None = None
        self.broken = False
        self.writes = 0

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 - boto3's signature
        if self.broken:
            raise RuntimeError("connection reset by peer")
        if self.obj is None:
            raise NoSuchKey("NoSuchKey: the specified key does not exist")
        return {"Body": FakeBody(self.obj)}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str = ""):  # noqa: N803
        if self.broken:
            raise RuntimeError("connection reset by peer")
        self.writes += 1
        self.obj = Body


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A machine identity that does not touch the real ~/.hermes."""
    monkeypatch.setattr(lease_mod, "HERMES", tmp_path)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    return tmp_path


def _as_machine(monkeypatch, mid: str, environment: str):
    monkeypatch.setattr(lease_mod, "machine_id", lambda: mid)
    monkeypatch.setattr(lease_mod, "environment_name", lambda: environment)


def test_a_free_lease_is_taken(isolated, monkeypatch):
    r2 = FakeR2()
    _as_machine(monkeypatch, "fly-1", "fly")
    held, lease = lease_mod.acquire(r2)
    assert held is True
    assert lease["environment"] == "fly"


def test_a_held_lease_is_not_stolen(isolated, monkeypatch):
    r2 = FakeR2()
    _as_machine(monkeypatch, "fly-1", "fly")
    lease_mod.acquire(r2)
    writes_after_fly = r2.writes

    _as_machine(monkeypatch, "mac-1", "mac")
    held, lease = lease_mod.acquire(r2)
    assert held is False
    assert lease["machine_id"] == "fly-1"
    assert r2.writes == writes_after_fly, "the loser must not overwrite a live lease"


def test_an_expired_lease_is_taken_over(isolated, monkeypatch):
    r2 = FakeR2()
    _as_machine(monkeypatch, "fly-1", "fly")
    lease_mod.acquire(r2, ttl_s=1.0)

    stale = json.loads(r2.obj)
    stale["renewed_at"] = stale["renewed_at"] - 3600
    r2.obj = json.dumps(stale).encode()

    _as_machine(monkeypatch, "mac-1", "mac")
    held, lease = lease_mod.acquire(r2)
    assert held is True, "a leader that stopped renewing must not hold the estate forever"
    assert lease["machine_id"] == "mac-1"


def test_the_leader_renewing_keeps_its_acquired_at(isolated, monkeypatch):
    r2 = FakeR2()
    _as_machine(monkeypatch, "fly-1", "fly")
    _, first = lease_mod.acquire(r2)
    _, second = lease_mod.acquire(r2)
    assert second["acquired_at"] == first["acquired_at"]
    assert second["renewed_at"] >= first["renewed_at"]


def test_an_outage_is_never_read_as_a_free_lease(isolated, monkeypatch):
    """The whole point. 'I cannot see the lease' must not become 'nobody holds it'."""
    r2 = FakeR2()
    _as_machine(monkeypatch, "fly-1", "fly")
    lease_mod.acquire(r2)

    r2.broken = True
    _as_machine(monkeypatch, "mac-1", "mac")
    with pytest.raises(lease_mod.CannotEstablish):
        lease_mod.acquire(r2)


def test_status_exit_codes_separate_not_ours_from_unknown(isolated, monkeypatch):
    r2 = FakeR2()
    monkeypatch.setattr(lease_mod, "make_client", lambda: r2)

    _as_machine(monkeypatch, "fly-1", "fly")
    assert lease_mod.main(["acquire"]) == lease_mod.EXIT_HELD

    _as_machine(monkeypatch, "mac-1", "mac")
    assert lease_mod.main(["status"]) == lease_mod.EXIT_NOT_OURS

    r2.broken = True
    assert lease_mod.main(["status"]) == lease_mod.EXIT_UNKNOWN


def test_the_fence_file_follows_the_lease(isolated, monkeypatch):
    """check_single_environment.sh reads config/primary_environment. The lease writes it, so
    the fence cannot disagree with the lease."""
    r2 = FakeR2()
    monkeypatch.setattr(lease_mod, "make_client", lambda: r2)
    _as_machine(monkeypatch, "fly-1", "fly")
    lease_mod.main(["acquire"])
    assert (isolated / "config" / "primary_environment").read_text().strip() == "fly"

    _as_machine(monkeypatch, "mac-1", "mac")
    lease_mod.main(["acquire"])
    assert (isolated / "config" / "primary_environment").read_text().strip() == "fly"


def test_a_non_holder_reports_before_it_enforces(isolated, monkeypatch):
    """Report mode before fix mode. Without --enforce nothing is stopped."""
    calls: list[bool] = []
    monkeypatch.setattr(lease_mod, "stop_local_daemons", lambda dry_run: calls.append(dry_run) or [])
    r2 = FakeR2()
    monkeypatch.setattr(lease_mod, "make_client", lambda: r2)

    _as_machine(monkeypatch, "fly-1", "fly")
    lease_mod.main(["acquire"])

    _as_machine(monkeypatch, "mac-1", "mac")
    lease_mod.main(["acquire"])
    assert calls == [True], "no --enforce means dry run only"

    lease_mod.main(["acquire", "--enforce"])
    assert calls == [True, False]


def test_the_leader_never_stops_itself(isolated, monkeypatch):
    """A container that can stop its own daemons is a container that can take the estate down
    over a transient read. stop_local_daemons is a no-op anywhere but this Mac."""
    _as_machine(monkeypatch, "fly-1", "fly")
    assert lease_mod.stop_local_daemons(dry_run=False) == []


def test_the_duplicated_list_matches_the_shell_fence():
    """Two lists of the same daemons drift. This fails the day they do."""
    shell = (HERMES / "scripts" / "check_single_environment.sh").read_text()
    line = next(ln for ln in shell.splitlines() if ln.startswith("DUPLICATED="))
    names = line.split("=", 1)[1].strip().strip('"').split()
    assert sorted(names) == sorted(lease_mod.DUPLICATED)
