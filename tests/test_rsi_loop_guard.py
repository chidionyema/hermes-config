#!/usr/bin/env python3
"""The self-improvement loop must never again run 244 cycles and learn nothing.

Each test here pins one of the three defects measured on 2026-08-19, so a future change that
reintroduces any of them goes red instead of quiet:

  * `_domain_outcomes` reading a file that a migration deleted   -> test_closer_reads_the_live_store
  * a gap identity that changes every time it is re-found        -> test_gap_identity_is_stable
  * a shadow that nothing ever grades                            -> test_shadow_promotes_and_escalates
  * the two halves tagging with different vocabularies           -> test_guard_sees_a_disjoint_vocabulary
  * a loop with no series, so nobody can see it stalled          -> test_guard_sees_a_stall
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# The modules under test live in scripts/. This file sits in tests/ because that is the
# directory `tests/run.sh` and the CI gate collect; a test left in scripts/ is run by
# nothing at all.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hermes_domains
import rsi_loop_guard
from auto_close_identity import GapCloser, _stable_gap_id


def _home(tmp_path: Path) -> Path:
    for d in ("logs", "policies", "state"):
        (tmp_path / d).mkdir()
    conn = sqlite3.connect(tmp_path / "state" / "outcomes.db")
    conn.execute("CREATE TABLE task_outcomes "
                 "(task_id TEXT, domain TEXT, outcome TEXT, error_type TEXT, created_at TEXT)")
    conn.commit()
    conn.close()
    return tmp_path


def _seed(home: Path, domain: str, n: int, n_success: int, after: datetime | None = None):
    base = after or datetime.now(timezone.utc)
    conn = sqlite3.connect(home / "state" / "outcomes.db")
    conn.executemany(
        "INSERT INTO task_outcomes VALUES (?,?,?,?,?)",
        [(f"t{i}", domain, "success" if i < n_success else "failure", "",
          (base + timedelta(seconds=i + 1)).isoformat()) for i in range(n)],
    )
    conn.commit()
    conn.close()


# ── the sensor ───────────────────────────────────────────────────────────────────
def test_closer_reads_the_live_store(tmp_path):
    """The gap closer must read state/outcomes.db, not the JSONL a migration deleted."""
    home = _home(tmp_path)
    _seed(home, "automation", 5, 5)
    assert not (home / "logs" / "task-outcomes.jsonl").exists()
    rows = GapCloser(home)._domain_outcomes("automation")
    assert len(rows) == 5, "the closer is blind to the live outcome store"
    assert {"ts", "outcome", "task_id", "domain"} <= set(rows[0])


def test_closer_still_reads_a_legacy_jsonl(tmp_path):
    home = _home(tmp_path)
    (home / "logs" / "task-outcomes.jsonl").write_text(
        json.dumps({"domain": "git", "outcome": "success", "task_id": "x", "ts": "2026-01-01"}) + "\n")
    assert len(GapCloser(home)._domain_outcomes("git")) == 1


# ── identity ─────────────────────────────────────────────────────────────────────
def test_gap_identity_is_stable():
    """A re-find is an UPDATE. A timestamp id minted 250 records for one gap."""
    a = _stable_gap_id("automation", "cron never fires")
    b = _stable_gap_id("automation", "cron never fires")
    assert a == b == "gap-automation-" + a.split("-")[-1]
    assert a != _stable_gap_id("automation", "something else")
    assert a != _stable_gap_id("testing", "cron never fires")


def test_refinding_a_gap_does_not_mint_a_second_policy(tmp_path):
    home = _home(tmp_path)
    gc = GapCloser(home)
    for _ in range(3):
        gc.auto_close_if_safe(gc.identify_gap("automation", "cron never fires", 4))
    assert len(list((home / "policies").glob("*.json"))) == 1


# ── the promotion path ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("total,ok,expect,policy_status", [
    (24, 18, "promoted", "active"),        # 75% clears the 70% bar
    (24, 10, "escalated", "provisional"),  # 42% does not
    (19, 19, "waiting", "provisional"),    # one short of the 20-outcome floor
])
def test_shadow_promotes_and_escalates(tmp_path, total, ok, expect, policy_status):
    """Nothing called evaluate_shadow from the hourly cycle, so 247 shadows never moved."""
    home = _home(tmp_path)
    gc = GapCloser(home)
    gc.auto_close_if_safe(gc.identify_gap("automation", "cron never fires", 4))
    _seed(home, "automation", total, ok)          # outcomes land inside the shadow window
    assert gc.evaluate_all_shadows()[expect] == 1
    policy = json.loads(next((home / "policies").glob("*.json")).read_text())
    assert policy["status"] == policy_status


def test_the_stored_record_carries_the_policy(tmp_path):
    """_save_gap dropped proposed_policy, so every reloaded gap said 'No shadow start time'.

    This asserts on the RECORD, not on the rebuilt Gap. `_gap_from_record` recovers the policy
    from `policies/` when the record lacks it, and that fallback masked the missing field
    entirely: with the assertion one level up, deleting the persistence line left the test
    green. Measured 2026-08-20 with a mutation run.
    """
    home = _home(tmp_path)
    gc = GapCloser(home)
    gc.auto_close_if_safe(gc.identify_gap("automation", "cron never fires", 4))
    rec = next(iter(GapCloser(home)._load_gaps().values()))
    assert rec.get("proposed_policy"), "the shadow window start was not persisted"
    assert rec["proposed_policy"]["created"]


def test_a_pre_migration_record_recovers_its_policy_from_disk(tmp_path):
    """253 shadow gaps were written before the field existed; they must still be gradable."""
    home = _home(tmp_path)
    gc = GapCloser(home)
    gc.auto_close_if_safe(gc.identify_gap("automation", "cron never fires", 4))
    gaps = gc._load_gaps()
    for rec in gaps.values():                       # strip it, as the old writer did
        rec.pop("proposed_policy", None)
    (home / "logs" / "active-gaps.json").write_text(json.dumps(gaps))
    rec = next(iter(GapCloser(home)._load_gaps().values()))
    assert GapCloser(home)._gap_from_record(rec).proposed_policy, "the disk fallback is gone"


# ── one vocabulary ───────────────────────────────────────────────────────────────
def test_classify_never_returns_an_executor_tag():
    """"coordinator" says WHERE a task ran. A capability domain says WHAT it exercised."""
    for text in ("cron job never fired", "pytest went red", "push was rejected"):
        assert hermes_domains.classify(text) not in hermes_domains.EXECUTOR_TAGS
        assert hermes_domains.is_capability_domain(hermes_domains.classify(text))


def test_both_halves_import_the_shared_vocabulary():
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    for name in ("gap-finding.py", "coordinator.py"):
        assert "hermes_domains" in (scripts / name).read_text(), \
            f"{name} classifies with its own keywords again"


# ── the guard itself ─────────────────────────────────────────────────────────────
def test_guard_sees_a_disjoint_vocabulary(tmp_path):
    home = _home(tmp_path)
    _seed(home, "coordinator", 40, 40)            # the store is busy...
    (home / "logs" / "active-gaps.json").write_text(json.dumps({
        "gap-automation-abc": {"gap_id": "gap-automation-abc", "domain": "automation",
                               "description": "x", "status": "shadow"}}))
    r = rsi_loop_guard.check(home)                # ...but never in the domain the gap waits on
    assert not r["healthy"]
    assert any(p.startswith("DISJOINT") for p in r["problems"])

    _seed(home, "automation", 1, 1)
    assert rsi_loop_guard.check(home)["healthy"]


def test_guard_sees_a_stall(tmp_path):
    home = _home(tmp_path)
    for _ in range(5):
        rsi_loop_guard.record_cycle({"gaps": {"gaps_found": 12, "auto_closed": 0}}, home=home)
    assert rsi_loop_guard.check(home, window=6)["healthy"], "5 cycles is under the window"

    rsi_loop_guard.record_cycle({"gaps": {"gaps_found": 12, "auto_closed": 0}}, home=home)
    r = rsi_loop_guard.check(home, window=6)
    assert not r["healthy"]
    assert any(p.startswith("STALL") for p in r["problems"])

    rsi_loop_guard.record_cycle({"gaps": {"gaps_found": 12, "auto_closed": 1}}, home=home)
    assert rsi_loop_guard.check(home, window=6)["healthy"], "one closure clears the stall"


def test_record_cycle_writes_a_readable_row(tmp_path):
    home = _home(tmp_path)
    rsi_loop_guard.record_cycle(
        {"gaps": {"gaps_found": 3, "auto_closed": 1, "shadow_eval": {"promoted": 1}},
         "meta": {"health_score": 0.5, "velocity": 0.01}, "elapsed": 2.0}, home=home)
    row = json.loads((home / "logs" / "self-improve-cycles.jsonl").read_text().strip())
    assert row["gaps_found"] == 3 and row["auto_closed"] == 1
    assert row["shadow_eval"] == {"promoted": 1} and row["health_score"] == 0.5
