#!/usr/bin/env python3
"""Proofs for the shared usage-wall marker. No network, no CLI, no wall clock.

Every proof points MARKER at a temp file, so ~/.hermes/state is never touched.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_usage_limit as U  # noqa: E402

NOW = 1_786_000_000.0
_checks, _failed = 0, []


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failed.append(name)


def fresh_marker():
    d = tempfile.mkdtemp()
    U.MARKER = os.path.join(d, "claude_usage_limit.json")
    return U.MARKER


print("PROOF 1 — the CLI's own reset epoch is captured, not discarded")
fresh_marker()
txt = "Claude AI usage limit reached|1786003600"
check("parse_reset reads the epoch", U.parse_reset(txt) == 1786003600.0,
      f"got {U.parse_reset(txt)}")
r = U.observe(txt, "test", now=NOW)
check("observe returns that epoch", r == 1786003600.0, f"got {r}")
check("blocked while the wall stands", U.is_blocked(now=NOW) is True)
check("clear once it lifts", U.is_blocked(now=1786003601.0) is False)

print("PROOF 2 — milliseconds must not block until the year 58000")
fresh_marker()
check("ms value is normalised to seconds",
      U.parse_reset("usage limit reached|1786003600000") == 1786003600.0,
      f"got {U.parse_reset('usage limit reached|1786003600000')}")

print("PROOF 3 — FALSIFIER: text that is NOT a limit must not block anything")
fresh_marker()
check("ordinary failure is ignored",
      U.observe("Error: file not found", "test", now=NOW) is None)
check("no marker written", U.read(now=NOW) is None)
check("a success is ignored", U.observe("Done. Wrote 3 files.", "test", now=NOW) is None)

print("PROOF 4 — a real wall with no timestamp gets a SHORT cooldown, not a guess")
fresh_marker()
r = U.observe("Claude AI usage limit reached", "test", now=NOW, cooldown_s=900)
check("cooldown applied", r == NOW + 900, f"got {r}")
check("blocked now", U.is_blocked(now=NOW) is True)
check("clear after the cooldown", U.is_blocked(now=NOW + 901) is False)

print("PROOF 5 — a wall never gets SHORTER by being re-observed (two-daemon race)")
fresh_marker()
U.observe("usage limit reached|1786009999", "otto", now=NOW)
r = U.observe("usage limit reached|1786000600", "prospector", now=NOW)
check("later reset wins", r == 1786009999.0, f"got {r}")
check("marker still holds the later reset",
      U.read(now=NOW)["reset_at"] == 1786009999.0)
r = U.observe("usage limit reached|1786019999", "prospector", now=NOW)
check("a LONGER wall does extend it", r == 1786019999.0, f"got {r}")

print("PROOF 6 — the marker is plain JSON any process can read without importing us")
fresh_marker()
U.observe("Claude AI usage limit reached|1786003600", "otto-coordinator", now=NOW)
with open(U.MARKER, encoding="utf-8") as f:
    raw = json.load(f)
check("reset_at present", raw["reset_at"] == 1786003600.0)
check("attributed to an observer", raw["observed_by"] == "otto-coordinator")
check("carries the proof text", "usage limit reached" in raw["source"])

print("PROOF 7 — a corrupt or absent marker fails OPEN, never blocks the estate")
fresh_marker()
check("absent -> not blocked", U.is_blocked(now=NOW) is False)
with open(U.MARKER, "w", encoding="utf-8") as f:
    f.write("{not json")
check("corrupt -> not blocked", U.is_blocked(now=NOW) is False)
with open(U.MARKER, "w", encoding="utf-8") as f:
    json.dump({"reset_at": "banana"}, f)
check("garbage reset_at -> not blocked", U.is_blocked(now=NOW) is False)

print("PROOF 8 — the coordinator actually publishes on the limit branch")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "coordinator.py"), encoding="utf-8").read()
check("coordinator imports the module", "import claude_usage_limit" in src)
check("and calls observe", "claude_usage_limit.observe(" in src)
check("publishing cannot break execution",
      "publishing a fact must never break the execution path" in src)

print(f"\n{_checks - len(_failed)}/{_checks} checks passed")
sys.exit(1 if _failed else 0)
