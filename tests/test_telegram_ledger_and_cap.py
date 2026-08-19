"""The Telegram ledger and the hourly alert ceiling.

Written 2026-08-19 with the noise cap itself, because the cap decides what the operator
does and does not see. A cap that drops an alert without recording it is worse than no
cap: the estate goes quiet and nobody knows why.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    mod = importlib.import_module("telegram_ledger")
    importlib.reload(mod)
    monkeypatch.setattr(mod, "LEDGER", tmp_path / "telegram_sent.jsonl")
    return mod


@pytest.fixture
def alert(ledger, monkeypatch):
    mod = importlib.import_module("estate_alert")
    importlib.reload(mod)
    monkeypatch.setattr(mod, "telegram_ledger", ledger)
    monkeypatch.setattr(mod, "_env", lambda k: "tok" if "TOKEN" in k else "chat")
    monkeypatch.setattr(mod, "_debounced", lambda key, window: False)
    return mod


class _Resp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture
def wire(monkeypatch):
    """Everything that would go on the wire, in order."""
    seen: list[str] = []

    def fake(req, *a, **kw):
        import urllib.parse
        seen.append(urllib.parse.parse_qs(req.data.decode())["text"][0])
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


# ── the ledger ────────────────────────────────────────────────────────────────────────

def test_a_send_a_suppression_and_a_misconfiguration_are_all_recorded(alert, ledger, wire,
                                                                      monkeypatch):
    """Three different silences look identical in a channel. They must not in the ledger."""
    alert.send_operator_alert("a real alert")
    monkeypatch.setattr(alert, "_debounced", lambda key, window: True)
    alert.send_operator_alert("a debounced alert", debounce_key="k")
    monkeypatch.setattr(alert, "_debounced", lambda key, window: False)
    monkeypatch.setattr(alert, "_env", lambda k: None)
    alert.send_operator_alert("an alert with no credentials")

    outcomes = [r["outcome"] for r in ledger.read()]
    assert outcomes == ["sent", "suppressed", "no-creds"], outcomes


def test_a_dry_run_is_not_a_send_and_is_not_recorded(alert, ledger, wire):
    """A dry run that landed in the ledger would inflate every noise measurement taken
    from a terminal, which is exactly where they get taken."""
    assert alert.send_operator_alert("dry", dry_run=True) is True
    assert ledger.read() == []
    assert wire == []


def test_a_failed_send_is_recorded_as_failed_not_sent(alert, ledger, monkeypatch):
    def boom(*a, **kw):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    assert alert.send_operator_alert("will not arrive") is False
    assert [r["outcome"] for r in ledger.read()] == ["failed"]


def test_read_skips_a_malformed_line_instead_of_dying(ledger):
    ledger.record("s", "sent", "one")
    with ledger.LEDGER.open("a") as fh:
        fh.write("{not json\n\n")
    ledger.record("s", "sent", "two")
    assert len(ledger.read()) == 2


def test_the_ledger_bounds_itself(ledger, monkeypatch):
    """Adding an unbounded log to fix a storage problem is the joke version of this work."""
    monkeypatch.setattr(ledger, "_TRIM_ABOVE_BYTES", 1)
    monkeypatch.setattr(ledger, "_KEEP_LINES", 10)
    for i in range(40):
        ledger.record("s", "sent", f"line {i}")
    rows = ledger.read()
    assert len(rows) <= 11, len(rows)
    assert rows[-1]["head"] == "line 39"          # it keeps the NEWEST, not the oldest


def test_recording_never_raises_when_the_ledger_cannot_be_written(ledger, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER", Path("/proc/nonexistent/telegram.jsonl"))
    ledger.record("s", "sent", "x")               # must not raise


def test_read_ignores_rows_outside_the_window(ledger):
    ledger.record("s", "sent", "old")
    rows = [json.loads(l) for l in ledger.LEDGER.read_text().splitlines()]
    rows[0]["ts"] = time.time() - 7200
    ledger.LEDGER.write_text(json.dumps(rows[0]) + "\n")
    ledger.record("s", "sent", "new")
    assert [r["head"] for r in ledger.read(3600.0)] == ["new"]


# ── the hourly ceiling ────────────────────────────────────────────────────────────────

def test_alerts_past_the_ceiling_do_not_reach_the_channel(alert, ledger, wire, monkeypatch):
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 3)
    for i in range(6):
        alert.send_operator_alert(f"alert {i}")
    # three alerts, then ONE notice; the rest are held.
    assert len(wire) == 4, wire
    assert "Alert ceiling reached" in wire[3]
    assert sum(1 for r in ledger.read() if r["outcome"] == "rate-capped") == 3


def test_a_held_alert_is_recorded_in_full_so_nothing_is_lost(alert, ledger, wire, monkeypatch):
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 1)
    alert.send_operator_alert("the one that got through")
    alert.send_operator_alert("the disk is full and nobody will hear about it")

    held = [r for r in ledger.read() if r["outcome"] == "rate-capped"]
    assert len(held) == 1
    assert "disk is full" in held[0]["head"]


def test_exactly_one_cap_notice_per_hour_not_one_per_held_alert(alert, ledger, wire,
                                                                monkeypatch):
    """A cap that announces itself once per suppressed alert IS the noise it was built
    to stop — and it would be louder, because the announcement never debounces."""
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 2)
    for i in range(20):
        alert.send_operator_alert(f"alert {i}")
    notices = [t for t in wire if "Alert ceiling reached" in t]
    assert len(notices) == 1, len(notices)


def test_the_ceiling_only_counts_the_last_hour(alert, ledger, wire, monkeypatch):
    """Otherwise the first busy hour silences the channel permanently."""
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 2)
    for i in range(5):
        alert.send_operator_alert(f"old alert {i}")
    aged = []
    for line in ledger.LEDGER.read_text().splitlines():
        row = json.loads(line)
        row["ts"] -= 7200
        aged.append(json.dumps(row))
    ledger.LEDGER.write_text("\n".join(aged) + "\n")

    wire.clear()
    alert.send_operator_alert("a new hour, a real alert")
    assert wire == ["a new hour, a real alert"], wire


def test_the_cap_notice_names_the_command_that_shows_what_was_held(alert, wire, monkeypatch):
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 1)
    alert.send_operator_alert("one")
    alert.send_operator_alert("two")
    notice = [t for t in wire if "Alert ceiling reached" in t][0]
    assert "telegram_noise.py" in notice


def test_a_zero_ceiling_means_no_ceiling_not_total_silence(alert, wire, monkeypatch):
    """0 is the off switch. Reading it as 'allow zero alerts' mutes the estate."""
    monkeypatch.setattr(alert, "ALERT_HOURLY_CAP", 0)
    for i in range(30):
        alert.send_operator_alert(f"alert {i}")
    assert len(wire) == 30


# ── the report ────────────────────────────────────────────────────────────────────────

def test_the_report_does_not_count_an_edit_as_a_message_in_the_channel(ledger, monkeypatch,
                                                                       capsys):
    """The coordinator's progress stream edits ONE message per task instead of posting a
    line per step. Counting edits as sends would rank the quietest design as the loudest."""
    mod = importlib.import_module("telegram_noise")
    importlib.reload(mod)
    monkeypatch.setattr(mod, "telegram_ledger", ledger)
    ledger.record("coordinator.progress", "sent", "step 1")
    for i in range(2, 40):
        ledger.record("coordinator.progress", "edited", f"step {i}")

    monkeypatch.setattr(sys, "argv", ["telegram_noise.py", "--since", "24h"])
    mod.main()
    out = capsys.readouterr().out
    assert "1 message(s) reached the channel" in out, out


def test_the_report_names_the_repeated_message_when_one_sender_loops(ledger, monkeypatch,
                                                                     capsys):
    mod = importlib.import_module("telegram_noise")
    importlib.reload(mod)
    monkeypatch.setattr(mod, "telegram_ledger", ledger)
    for _ in range(12):
        ledger.record("watchdog", "sent", "gateway WEDGED")
    ledger.record("selfcheck", "sent", "something else entirely")

    monkeypatch.setattr(sys, "argv", ["telegram_noise.py"])
    mod.main()
    out = capsys.readouterr().out
    assert "gateway WEDGED" in out.split("MOST REPEATED")[1]


def test_parse_since_understands_the_units_people_type():
    mod = importlib.import_module("telegram_noise")
    assert mod.parse_since("90m") == 5400
    assert mod.parse_since("24h") == 86400
    assert mod.parse_since("7d") == 604800
    assert mod.parse_since("2") == 7200          # a bare number is hours
