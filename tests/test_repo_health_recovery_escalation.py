"""Proof for the repo-health recovery-paging fix (2026-08-18).

The failure this pins: lux went dirty -> skip -> pass (it was briefly absent, then
came back green) and repo-health-check.py paged the RECOVERY as an incident, which
the downstream titler rendered as "failure: lux: skip -> pass". Two defects made it
possible and both are covered here:

  1. main() escalated EVERY state transition at severity "warn", so a transition
     INTO 'pass' was queued exactly like a regression.
  2. The 'pass' summary was the raw last line of test output. For lux that is
     vitest's "Duration 33.52s (...)" line, which differs every run, so
     hermes_queue.drain — which fingerprints on the message — could never dedup it.

These tests prove the fix has teeth in BOTH directions: recoveries are silent but
still printed, and every regression still pages.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

_SRC = Path.home() / ".hermes" / "scripts" / "repo-health-check.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rhc = _load()


def _clean_repo(tmp_path):
    """A git repo whose `git status --short` is empty, so check_repo sees dirty=0."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("*\n")  # ignores itself too
    return tmp_path


# ---------------------------------------------------------------- the predicate

def test_transitions_into_pass_are_silent():
    """skip->pass and dirty->pass are recoveries, not incidents."""
    assert rhc.should_escalate_change("pass") is False


def test_every_regression_still_escalates():
    """Teeth: leaving 'pass' in any direction must still page."""
    for new in ("fail", "skip", "dirty"):
        assert rhc.should_escalate_change(new) is True, new


# ------------------------------------------------------------ the stable summary

def test_pass_summary_is_identical_across_runs_with_different_durations(tmp_path):
    """The exact lux bug: two green runs must mint the SAME message.

    hermes_queue fingerprints on the message, so a per-run duration in the summary
    defeats dedup on every single green tick.
    """
    root = _clean_repo(tmp_path)
    info = {"path": str(root), "requires": [],
            "test_cmd": "echo '  Duration  33.52s (transform 7.37s, collect 14.63s)'"}
    _, first = rhc.check_repo("lux", info)

    info["test_cmd"] = "echo '  Duration  14.22s (transform 2.11s, collect 4.03s)'"
    _, second = rhc.check_repo("lux", info)

    assert first["state"] == "pass" and second["state"] == "pass", (first, second)
    assert first["summary"] == second["summary"], (first, second)
    assert "Duration" not in first["summary"], first
    assert first["summary"] == "lux: tests pass", first


def test_fail_summary_still_carries_the_diagnostic(tmp_path):
    """The raw last line stays where it is useful: the failure branch."""
    root = _clean_repo(tmp_path)
    _, res = rhc.check_repo("lux", {
        "path": str(root), "requires": [],
        "test_cmd": "echo 'FAIL src/thing.test.ts > it works'; exit 1",
    })
    assert res["state"] == "fail", res
    assert "it works" in res["summary"], res


# ------------------------------------------------------------------ end-to-end

def _run_main(monkeypatch, tmp_path, prev_states, new_states):
    """Drive main() with a fake history and fake repo results; capture submits."""
    hist = tmp_path / "repo-health.jsonl"
    hist.write_text(json.dumps(
        {"timestamp": "2026-08-18T00:00:00Z",
         "results": {n: {"state": s, "summary": f"{n}: old"} for n, s in prev_states.items()}}
    ) + "\n")

    monkeypatch.setattr(rhc, "HISTORY_FILE", hist)
    monkeypatch.setattr(rhc, "LOG_DIR", tmp_path)
    monkeypatch.setattr(rhc, "REPOS", {n: {"path": "/nonexistent"} for n in new_states})

    submitted = []
    monkeypatch.setattr(rhc, "submit", lambda msg, sev: submitted.append((sev, msg)))
    monkeypatch.setattr(rhc, "check_repo",
                        lambda n, i: (n, {"state": new_states[n],
                                          "summary": f"{n}: summary"}))
    rc = rhc.main()
    return rc, submitted


def test_recovery_is_not_queued_but_regression_is(monkeypatch, tmp_path, capsys):
    """The live lux sequence: skip -> pass must queue NOTHING."""
    rc, submitted = _run_main(
        monkeypatch, tmp_path,
        prev_states={"lux": "skip", "signalengine": "pass"},
        new_states={"lux": "pass", "signalengine": "fail"},
    )
    assert rc == 0
    msgs = [m for _, m in submitted]
    assert not any("lux" in m for m in msgs), submitted
    assert ("warn", "signalengine: pass -> fail: signalengine: summary") in submitted, submitted
    assert ("crit", "signalengine: summary") in submitted, submitted

    # ...but the recovery is still REPORTED on stdout — silent queue, not silent run.
    out = capsys.readouterr().out
    assert "lux: skip -> pass" in out, out


def test_dirty_to_pass_is_also_silent(monkeypatch, tmp_path):
    rc, submitted = _run_main(monkeypatch, tmp_path,
                              prev_states={"lux": "dirty"}, new_states={"lux": "pass"})
    assert rc == 0
    assert submitted == [], submitted


def test_pass_to_skip_still_pages(monkeypatch, tmp_path):
    """Teeth: the incomplete-tree path must not be able to go silent."""
    rc, submitted = _run_main(monkeypatch, tmp_path,
                              prev_states={"lux": "pass"}, new_states={"lux": "skip"})
    assert rc == 0
    assert submitted == [("warn", "lux: pass -> skip: lux: summary")], submitted
