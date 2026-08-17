"""Tests for the delivery canary.

Run: python3 -m pytest ~/.hermes/scripts/test_delivery_canary.py -q

The dangerous direction here is a FALSE GREEN: a canary that reports the alert
channel proven when it is not is strictly worse than no canary, because it retires
the founder's suspicion. So every not-proven branch is asserted explicitly, and the
one green branch is asserted to require all of its preconditions.

`assess()` is pure so these never touch the live cron/jobs.json. The one test that
exercises main() patches the module attributes, not HERMES_HOME — HOME/JOBS/PROOF
bind at import, so setting the env var inside a test is a no-op that silently reads
and writes production.
"""
import json
import time

import pytest

import delivery_canary as dc

HOME_CHAT = "8868748055"


def _job(**over):
    job = {
        "name": dc.JOB_NAME,
        "deliver": "origin",
        "origin": {"platform": "telegram", "chat_id": HOME_CHAT},
        "last_run_at": "2026-07-30T09:00:00+01:00",
        "last_delivery_error": None,
    }
    job.update(over)
    return job


NOW = 1785000000.0


def test_clean_previous_delivery_is_proof():
    rec, code = dc.assess(_job(), NOW, HOME_CHAT)
    assert rec["verified"] is True
    assert rec["delivered_at"] == "2026-07-30T09:00:00+01:00"
    assert code == 0


def test_a_recorded_delivery_error_is_not_proof():
    """The whole point: the scheduler already knows delivery failed, and until now
    nothing read it back."""
    rec, code = dc.assess(_job(last_delivery_error="telegram: chat not found"), NOW, HOME_CHAT)
    assert rec["verified"] is False
    assert rec["reason"] == "delivery-failed"
    assert "chat not found" in rec["detail"]
    assert code == 1


def test_first_run_is_honest_not_green():
    rec, code = dc.assess(_job(last_run_at=None), NOW, HOME_CHAT)
    assert rec["verified"] is False
    assert rec["reason"] == "first-run"
    # Exit 0: nothing is broken yet, so this must not raise an alarm on install.
    assert code == 0


def test_missing_job_is_a_failure():
    rec, code = dc.assess(None, NOW, HOME_CHAT)
    assert rec["verified"] is False and code == 1
    assert rec["reason"] == "job-missing"


def test_local_delivery_proves_nothing():
    """deliver:local writes the output to a file. A canary that never leaves the
    machine cannot say anything about the founder's channel — this is exactly the
    shape of the 46-day outage, where the artifact existed and nobody got it."""
    rec, code = dc.assess(_job(deliver="local"), NOW, HOME_CHAT)
    assert rec["verified"] is False
    assert rec["reason"] == "not-delivered"
    assert code == 1


def test_delivery_to_the_wrong_chat_is_a_failure():
    rec, code = dc.assess(_job(origin={"chat_id": "99999"}), NOW, HOME_CHAT)
    assert rec["verified"] is False
    assert rec["reason"] == "wrong-channel"
    assert code == 1


def test_unknown_home_channel_does_not_manufacture_a_mismatch():
    """If the config cannot be read, the cross-check is unavailable — it must not
    invent a failure, because a canary that cries wolf gets muted."""
    rec, code = dc.assess(_job(), NOW, None)
    assert rec["verified"] is True and code == 0


# --------------------------------------------------------------------------
# peer scan — existing daily traffic, finally read
# --------------------------------------------------------------------------

def _iso(offset_s):
    return time.strftime("%Y-%m-%dT%H:%M:%S+01:00", time.localtime(time.time() + offset_s))


def _peer(name, err, age_s=-3600, deliver="origin"):
    return {"name": name, "deliver": deliver, "last_delivery_error": err,
            "last_run_at": _iso(age_s)}


def test_a_recent_peer_failure_is_reported():
    now = time.time()
    got = peer_names(dc.peer_delivery_failures([_peer("morning-brief", "429 too many")], now))
    assert got == ["morning-brief"]


def peer_names(rows):
    return [r["job"] for r in rows]


def test_healthy_peers_are_silent():
    now = time.time()
    assert dc.peer_delivery_failures([_peer("morning-brief", None)], now) == []


def test_a_stale_peer_failure_does_not_latch_forever():
    """last_delivery_error persists until that job next delivers successfully. A
    monthly job would otherwise keep the alarm on for weeks after the channel healed
    — a permanently-on alarm is one that gets muted."""
    now = time.time()
    old = _peer("monthly-report", "boom", age_s=-40 * 86400)
    assert dc.peer_delivery_failures([old], now) == []


def test_local_delivery_peers_are_not_counted():
    now = time.time()
    rows = dc.peer_delivery_failures([_peer("local-thing", "boom", deliver="local")], now)
    assert rows == []


def test_the_canary_does_not_count_itself():
    now = time.time()
    me = _peer(dc.JOB_NAME, "boom")
    assert dc.peer_delivery_failures([me], now) == []


def test_a_peer_failure_overrides_the_canary_green(tmp_path, monkeypatch, capsys):
    """The canary reports on LAST week. A peer that failed an hour ago is evidence
    about now, and must win."""
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(), _peer("morning-brief", "chat not found")]}))
    monkeypatch.setattr(dc, "JOBS", jobs)
    monkeypatch.setattr(dc, "PROOF", tmp_path / "delivery_proof.json")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", HOME_CHAT)

    assert dc.main() == 1
    out = capsys.readouterr().out
    assert "morning-brief" in out and "chat not found" in out
    rec = json.loads((tmp_path / "delivery_proof.json").read_text())
    assert rec["verified"] is False
    assert rec["peer_failures"][0]["job"] == "morning-brief"


# --------------------------------------------------------------------------
# a healed channel — positive proof beats a sticky error
# --------------------------------------------------------------------------

def test_a_later_clean_delivery_clears_an_older_peer_failure():
    """last_delivery_error is sticky (cron/jobs.py:978 only overwrites it when THAT
    job next delivers). On 2026-08-16 a Telegram timeout burst left dead errors on
    four infrequent jobs; the channel healed the same night, but the canary kept
    exiting 1. If ANY origin job delivered clean after the failure, the failure is
    history, not an outage."""
    now = time.time()
    jobs = [_peer("weekly-progress-digest", "Telegram send failed: Timed out", age_s=-3600),
            _peer("daily-self-reflection", None, age_s=-600)]
    healed = dc.last_successful_delivery(jobs)
    assert healed is not None
    assert dc.peer_delivery_failures(jobs, now, healed) == []


def test_a_peer_failure_with_no_later_clean_delivery_still_alarms(tmp_path, monkeypatch, capsys):
    """The other direction: the newest thing that happened on the channel is a
    failure, so it is a live outage and must still exit 1."""
    now = time.time()
    jobs = [_peer("weekly-progress-digest", "Telegram send failed: Timed out", age_s=-600),
            _peer("daily-self-reflection", None, age_s=-3600)]
    healed = dc.last_successful_delivery(jobs)
    assert peer_names(dc.peer_delivery_failures(jobs, now, healed)) == ["weekly-progress-digest"]

    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"jobs": [_job(last_run_at=_iso(-7200))] + jobs}))
    monkeypatch.setattr(dc, "JOBS", jobs_file)
    monkeypatch.setattr(dc, "PROOF", tmp_path / "delivery_proof.json")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", HOME_CHAT)
    assert dc.main() == 1
    assert "weekly-progress-digest" in capsys.readouterr().out


def test_an_unparseable_peer_timestamp_is_still_reported():
    """Unknown age must fail loud. A peer we cannot date cannot be proved healed, so
    it keeps the alarm rather than slipping through the healed-since test."""
    now = time.time()
    broken = {"name": "mystery-job", "deliver": "origin",
              "last_delivery_error": "boom", "last_run_at": "not-a-timestamp"}
    jobs = [broken, _peer("daily-self-reflection", None, age_s=-600)]
    healed = dc.last_successful_delivery(jobs)
    assert peer_names(dc.peer_delivery_failures(jobs, now, healed)) == ["mystery-job"]


def test_last_successful_delivery_ignores_failed_and_local_jobs():
    clean = _peer("clean-one", None, age_s=-600)
    jobs = [_peer("failed-one", "boom", age_s=-60),
            _peer("local-one", None, age_s=-60, deliver="local"),
            clean]
    healed = dc.last_successful_delivery(jobs)
    assert healed == dc._parse_iso(clean["last_run_at"])
    assert dc.last_successful_delivery([_peer("failed-one", "boom")]) is None


# --------------------------------------------------------------------------
# main() — stdout must never be empty, in either direction
# --------------------------------------------------------------------------

@pytest.mark.parametrize("job,expect_code", [
    (_job(), 0),
    (_job(last_delivery_error="boom"), 1),
    (_job(last_run_at=None), 0),
])
def test_main_always_prints_something(job, expect_code, tmp_path, monkeypatch, capsys):
    """The scheduler only attempts delivery when stdout is non-empty. A silent
    success would leave last_delivery_error untouched, and the next run would read
    that stale None as fresh proof — a canary that proves itself."""
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [job]}))
    monkeypatch.setattr(dc, "JOBS", jobs)
    monkeypatch.setattr(dc, "PROOF", tmp_path / "delivery_proof.json")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", HOME_CHAT)

    assert dc.main() == expect_code
    out = capsys.readouterr().out.strip()
    assert out, "empty stdout means the scheduler delivers nothing and the chain is untested"
    assert json.loads((tmp_path / "delivery_proof.json").read_text())["checked_at"] > 0


def test_unreadable_jobs_file_fails_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dc, "JOBS", tmp_path / "nope.json")
    monkeypatch.setattr(dc, "PROOF", tmp_path / "delivery_proof.json")
    assert dc.main() == 1
    assert "cannot read" in capsys.readouterr().out
    rec = json.loads((tmp_path / "delivery_proof.json").read_text())
    assert rec["verified"] is False


def test_proof_file_is_written_on_every_run_not_only_on_success(tmp_path, monkeypatch):
    """verify_estate.sh reads this file's age. If it were only written when things
    were fine, a broken channel would look merely stale rather than failing."""
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(last_delivery_error="boom")]}))
    monkeypatch.setattr(dc, "JOBS", jobs)
    monkeypatch.setattr(dc, "PROOF", tmp_path / "delivery_proof.json")
    dc.main()
    rec = json.loads((tmp_path / "delivery_proof.json").read_text())
    assert rec["verified"] is False and rec["checked_at"] >= time.time() - 60
