#!/usr/bin/env python3
"""Proofs for attempt-level attribution and the outcome-grounded ruler.

Every proof that needs a database builds its own in a temp dir. Production
coordinator.db is opened READ-ONLY and only by the two proofs that assert the LIVE
system is unblocked — which is the whole point of the change and must not be taken
on trust.
"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi_outcome_ledger as L  # noqa: E402
import build_rsi_evalset as B  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rsi_orch", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rsi-orchestrator.py"))
RSI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RSI)

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


def make_db(verify_rows, tasks=()):
    """verify_rows: (payload_dict_or_str, age_days). Returns the db path."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "coordinator.db")
    con = sqlite3.connect(p)
    con.execute("create table events (task_id text, kind text, payload text, created_at real)")
    con.execute("create table tasks (id text, title text, status text, result text, "
                "created_at real, completed_at real)")
    for i, (payload, age) in enumerate(verify_rows):
        body = payload if isinstance(payload, str) else json.dumps(payload)
        con.execute("insert into events values (?,?,?,?)",
                    (f"t{i}", "verify", body, NOW - age * 86400.0))
    for t in tasks:
        con.execute("insert into tasks values (?,?,?,?,?,?)", t)
    con.commit()
    con.close()
    return p


def fail(reason, age=1.0):
    return ({"ok": False, "reason": reason}, age)


print("PROOF 1 — every lever is classified from the verifier's OWN recorded reason")
cases = {
    "failure condition still present": "prompt_quality_unfixed",
    "executor could not act (fell back to chat) — no real work performed": "executor_fallback",
    "acceptance test failed (exit≠0): (exit 1, no output)": "ambiguous_exit_nonzero",
    "acceptance test failed (exit≠0): FAIL: uncommitted-watch next_run_at": "prompt_quality_noproof",
    "acceptance test failed (exit≠0): bash: line 1: some_cmd: command not found":
        "acceptance_test_broken",
    "The evidence only describes general analysis and creation of a report":
        "prompt_quality_prose",
    "": "unclassified",
}
for reason, expect in cases.items():
    got = L.classify_attempt(reason)
    check(f"{expect:<24} <- {reason[:44]!r}", got == expect, f"got {got}")

print("\nPROOF 2 — FALSIFIER: a population a prompt CANNOT reach must not inflate authority")
# If this passes when it should not, the gate waves through a rewrite that cannot
# possibly help — the exact failure the authority gate exists to prevent.
db = make_db([fail("executor could not act (fell back to chat) — no real work performed")] * 40)
a = L.attempt_attribute(L.load_attempts(db))
check("40 fallbacks -> 0% authority", a["prompt_authority"] == 0.0, f"got {a['prompt_authority']}")
check("gate would BLOCK", a["prompt_authority"] < RSI.RSI_MIN_PROMPT_AUTHORITY)
db = make_db([fail("acceptance test failed (exit≠0): bash: cmd: command not found")] * 40)
a = L.attempt_attribute(L.load_attempts(db))
check("40 broken acceptance tests -> 0% authority", a["prompt_authority"] == 0.0)

print("\nPROOF 3 — FALSIFIER: ambiguous rows stay OUT of the numerator, IN the denominator")
db = make_db([fail("acceptance test failed (exit≠0): (exit 1, no output)")] * 90
             + [fail("failure condition still present")] * 10)
a = L.attempt_attribute(L.load_attempts(db))
check("denominator counts all 100", a["failures"] == 100, f"got {a['failures']}")
check("numerator counts only the 10", a["prompt_reachable"] == 10, f"got {a['prompt_reachable']}")
check("authority is 10%, not 100%", a["prompt_authority"] == 0.10, f"got {a['prompt_authority']}")
check("ambiguous reported, not hidden", a["ambiguous"] == 90, f"got {a['ambiguous']}")

print("\nPROOF 4 — passed attempts are not failures; both payload spellings are read")
db = make_db([({"ok": True, "reason": "acceptance test passed"}, 1),
              ({"passed": False, "reason": "failure condition still present"}, 1),
              ({"ok": False, "reason": "failure condition still present"}, 1),
              ("{not json", 1)])
at = L.load_attempts(db)
check("only the 2 rejections load", len(at) == 2, f"got {len(at)}")
check("'passed' spelling is honoured too",
      all(x["lever"] == "prompt_quality_unfixed" for x in at))

print("\nPROOF 5 — the window is a real filter and `now` is injectable")
db = make_db([fail("failure condition still present", age=1)] * 5
             + [fail("executor could not act (fell back to chat)", age=40)] * 50)
recent = L.recent_attempt_authority(db, window_days=14, now=NOW)
alltime = L.attempt_attribute(L.load_attempts(db))
check("14d sees only the 5 recent", recent["failures"] == 5, f"got {recent['failures']}")
check("14d authority 100%", recent["prompt_authority"] == 1.0)
check("all-time is dragged down by the ghosts", alltime["prompt_authority"] < 0.10,
      f"got {alltime['prompt_authority']}")

print("\nPROOF 6 — a DB with no verify events returns None, so the caller can fall back")
# Reading an absent corpus as 0% would be the ghost bug in a new place: a gate that
# blocks forever on evidence that was never recorded.
db = make_db([])
check("no verify events -> None", L.recent_attempt_authority(db, now=NOW) is None)

print("\nPROOF 7 — outcome_demand scores the FRACTION of requirements met")
d = tempfile.mkdtemp()
_real_evalset_path = RSI.evalset_path      # restored before PROOF 11 touches production
RSI.evalset_path = lambda var: os.path.join(d, f"{var}.jsonl")
with open(os.path.join(d, "EXECUTE_PROMPT.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"case_id": "outcome_demand:x", "split": "train", "weight": 30.0,
                        "require": [["re-?run"], ["still present"], ["report fail"]]}) + "\n")
    f.write(json.dumps({"case_id": "length_guard", "split": "train",
                        "max_len": 100, "weight": 10.0}) + "\n")
sc = lambda t: RSI.score_prompt("EXECUTE_PROMPT", t, "train")  # noqa: E731
check("0 of 3 groups -> 0 pts (+10 guard)", sc("nothing here") == 10.0, f"got {sc('nothing here')}")
check("1 of 3 -> 10 pts (+10)", sc("rerun it") == 20.0, f"got {sc('rerun it')}")
check("3 of 3 -> 30 pts (+10)", sc("re-run; still present; report fail") == 40.0,
      f"got {sc('re-run; still present; report fail')}")
check("an alternative spelling satisfies its group", sc("rerun") == sc("re-run"))

print("\nPROOF 8 — FALSIFIER: length_guard has NO gradient (the brevity_check defect)")
# brevity_check gave got = weight * (1 - len/max_len): every deleted character paid.
# That is why the only reachable win was a shorter executor prompt.
short, long_ = "re-run", "re-run " + "x" * 80
check("short and long score identically under the cap", sc(short) == sc(long_),
      f"{sc(short)} vs {sc(long_)}")
check("over the cap earns nothing for the guard", sc("re-run " + "x" * 200) == 10.0,
      f"got {sc('re-run ' + 'x' * 200)}")

print("\nPROOF 9 — FALSIFIER: nothing on the ruler pays for DELETING an instruction")
# The single property the old ruler lacked. If any deletion can raise the score, RSI's
# best move is again to strip the executor prompt, which is how it does harm.
full = "re-run the check; if the failure condition is still present, report failed"
raised = [i for i in range(len(full))
          if RSI.score_prompt("EXECUTE_PROMPT", full[:i] + full[i + 1:], "train") > sc(full)]
check("no single-character deletion raises the score", not raised,
      f"{len(raised)} deletions did")
words = full.split()
raised_w = [w for i, w in enumerate(words)
            if RSI.score_prompt("EXECUTE_PROMPT",
                                " ".join(words[:i] + words[i + 1:]), "train") > sc(full)]
check("no single-word deletion raises the score", not raised_w, f"{raised_w} did")

print("\nPROOF 10 — the builder REFUSES rather than emit a ruler with no evidence")
db = make_db([])
check("empty corpus -> rc 2", B.main(["--db", db, "--out", os.path.join(d, "o.jsonl")]) == 2)
db = make_db([fail("failure condition still present")] * 4)     # under MIN_SUPPORT
check("below the support floor -> rc 2",
      B.main(["--db", db, "--out", os.path.join(d, "o.jsonl")]) == 2)

print("\nPROOF 11 — the LIVE ruler actually unblocks RSI (read-only on production)")
RSI.evalset_path = _real_evalset_path      # back to the production ruler
import coordinator as C  # noqa: E402
cur = C.DEFAULT_EXECUTE_PROMPT
hr = RSI.quality_headroom(RSI.score_breakdown("EXECUTE_PROMPT", cur, "train"))
check(f"train headroom {hr} >= RSI_MARGIN {RSI.RSI_MARGIN}", hr >= RSI.RSI_MARGIN)
check("the current prompt answers NONE of the recorded modes",
      all(v["got"] == 0.0 for k, v in
          RSI.score_breakdown("EXECUTE_PROMPT", cur, "train").items()
          if k.startswith("outcome_demand")))
live = L.recent_attempt_authority(os.path.expanduser("~/.hermes/coordinator.db"))
check(f"live authority {live['prompt_authority']:.1%} >= floor "
      f"{RSI.RSI_MIN_PROMPT_AUTHORITY:.0%}",
      live["prompt_authority"] >= RSI.RSI_MIN_PROMPT_AUTHORITY)

print("\nPROOF 12 — the orchestrator uses the attempt-level entry point")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "rsi-orchestrator.py"), encoding="utf-8").read()
check("calls recent_attempt_authority", "recent_attempt_authority(COORDINATOR_DB)" in src)
check("falls back to task level", "or _ledger.recent_authority(COORDINATOR_DB)" in src)
check("scores outcome_demand", 'case_id.startswith("outcome_demand")' in src)
# Parse case_id; do NOT grep. The new ruler NAMES brevity_check in the evidence text
# that explains what it replaced, so a substring test reports the defect still present
# in the file that removed it (memory: substring-http-codes-bench-a-live-brain).
_live = [json.loads(x) for x in open(os.path.expanduser(
    "~/.hermes/meta/rsi_evalsets/EXECUTE_PROMPT.jsonl"), encoding="utf-8") if x.strip()]
check("no gameable case survives on the live ruler",
      not [c for c in _live if c["case_id"] in RSI.GAMEABLE_CASES],
      f"found {[c['case_id'] for c in _live if c['case_id'] in RSI.GAMEABLE_CASES]}")
check("every case carries the evidence that put it there",
      all("evidence" in c for c in _live))
check("both splits are populated",
      {c["split"] for c in _live} == {"train", "test"})

print(f"\n{_checks - len(_failed)}/{_checks} checks passed")
if _failed:
    print("failed: " + ", ".join(_failed))
sys.exit(1 if _failed else 0)
