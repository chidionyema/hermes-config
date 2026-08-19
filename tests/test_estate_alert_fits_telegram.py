"""estate_alert must not lose a whole page because it grew.

Telegram rejects a sendMessage over 4096 characters outright — the whole message, not the
tail. So the alert that says the most is the one most likely to arrive as nothing at all.
Measured 2026-08-19: the self-check's estate section builds 2767 characters from 11 faults,
which is one long fault line away from the ceiling.

The cap lives in the SENDER so every caller inherits it. These tests hold it there.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path.home() / ".hermes" / "scripts" / "estate_alert.py"


def _load():
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("estate_alert_undertest", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _long_alert(n: int = 60) -> str:
    return "\n".join(f"NEW FAIL: fault number {i} " + "x" * 120 for i in range(n))


def test_an_oversized_alert_is_trimmed_below_the_telegram_ceiling():
    mod = _load()
    body = _long_alert()
    assert len(body) > mod.TELEGRAM_MAX_CHARS
    assert len(mod._fit(body)) <= mod.TELEGRAM_MAX_CHARS


def test_trimming_says_how_much_was_dropped():
    """A silent truncation reads as a complete report. It has to admit what it cut."""
    mod = _load()
    out = mod._fit(_long_alert())
    last = out.splitlines()[-1]
    assert "more line(s) trimmed" in last, last
    dropped = int(last.split()[1])
    kept = len(out.splitlines()) - 1        # -1 for the marker line itself
    assert dropped + kept == 60, (dropped, kept)


def test_trimming_cuts_on_a_line_boundary():
    """Half a fault line is worse than no fault line: it reads as a different fault."""
    mod = _load()
    out = mod._fit(_long_alert())
    for line in out.splitlines()[:-1]:
        assert line.endswith("x" * 120), line


def test_a_message_under_the_ceiling_is_untouched():
    mod = _load()
    body = "*Hermes self-check changed*\nNEW FAIL: estate: something — detail"
    assert mod._fit(body) == body


def test_the_sender_actually_applies_the_cap(monkeypatch):
    """A guard that exists but is never called is the defect it was written to prevent.

    The tests above all drive `_fit` directly, so deleting the one call to it inside
    send_operator_alert leaves them green. This one reads what would go on the wire.
    """
    import urllib.request

    mod = _load()
    monkeypatch.setattr(mod, "_env", lambda k: "fake-token" if "TOKEN" in k else "fake-chat")

    seen: list[bytes] = []

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, *a, **kw):
        seen.append(req.data)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert mod.send_operator_alert(_long_alert()) is True
    assert len(seen) == 1
    # The body is form-encoded, so it is longer than the text; the text field is what counts.
    import urllib.parse
    fields = urllib.parse.parse_qs(seen[0].decode())
    assert len(fields["text"][0]) <= mod.TELEGRAM_MAX_CHARS, len(fields["text"][0])
