"""Proof that the RSI prompt tuner's retry attempts carry their own task.

Read-only against the live estate: R.route is stubbed, so no LLM call is made, and every
candidate is rejected before the code that writes prompts.json / meta/pending.

Before the fix, attempts 2..N were sent the feedback string ALONE. Measured consequence,
from ~/.hermes/logs/rsi-autorun.log on 2026-08-07: attempt 1 (full prompt) scored
train 81.76 / held-out 78.29 vs baseline 87.28 / 84.86; attempts 2 and 3 scored 20.0/0.0
and 30.0/20.0, the second rejected for "Missing required variables: {spec}, {title}" —
variables its own instruction never mentioned.
"""
import importlib.util
import io
import os
import sys
from contextlib import redirect_stdout

HERMES = os.path.expanduser("~/.hermes")
sys.path.insert(0, os.path.join(HERMES, "scripts"))

spec = importlib.util.spec_from_file_location(
    "rsi_orchestrator", os.path.join(HERMES, "scripts", "rsi-orchestrator.py")
)
RSI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RSI)

failures = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        failures.append(f"{label} :: {detail}")
        if detail:
            print(f"        {detail}")


def run(prompt_variable, candidate_factory):
    """Drive run_prompt_tuning with a stubbed router; return the prompts it generated."""
    seen = []

    class _Res:
        def __init__(self, text):
            self.text = text

    def fake_route(_role, prompt):
        seen.append(prompt)
        return _Res(candidate_factory(len(seen)))

    original = RSI.R.route
    RSI.R.route = fake_route
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = RSI.run_prompt_tuning(prompt_variable)
    finally:
        RSI.R.route = original
    return seen, rc, buf.getvalue()


print("=== PROOF 1: every retry carries the template, the variables and the reason ===")
# A candidate that keeps its variables but is otherwise weak: rejected by the IMPROVEMENT
# gate, which is the path that produces a feedback message and a retry.
weak = "Do the thing. Spec: {spec} Task: {title}"
prompts, rc, out = run("EXECUTE_PROMPT", lambda n: weak)

check("the tuner made all 3 attempts", len(prompts) == 3, f"got {len(prompts)}")
for i, p in enumerate(prompts, 1):
    check(f"attempt {i} names the template being tuned", "EXECUTE_PROMPT" in p)
    check(f"attempt {i} states the required variables", "{spec}" in p and "{title}" in p)
    check(f"attempt {i} includes the CURRENT template to edit", "Current template:" in p)
    check(f"attempt {i} states the score to beat", "beat train" in p)
for i in (2, 3):
    p = prompts[i - 1]
    check(f"attempt {i} states why the previous attempt was rejected", "REJECTED" in p)
    check(f"attempt {i} forbids starting from scratch", "do not start" in p.lower())
    # The regression itself: the old retry prompt was ~2 short lines and had no template.
    check(f"attempt {i} is not a bare feedback string", len(p) > len(weak) + 200,
          f"len={len(p)}")

print()
print("=== PROOF 2: VERIFY_PROMPT is told about ITS variables, not EXECUTE_PROMPT's ===")
vp = "Verify it. Acceptance test: {acceptance_test} Evidence: {evidence}"
prompts_v, rc_v, out_v = run("VERIFY_PROMPT", lambda n: vp)
first = prompts_v[0]
check("names {acceptance_test}", "{acceptance_test}" in first)
check("names {evidence}", "{evidence}" in first)
check("does NOT instruct about {spec} (EXECUTE_PROMPT's variable)",
      "{spec}" not in first.split("Current template:")[0],
      "the pre-fix instruction hardcoded 'like {spec}, {title}, etc.' for every variable")
check("does NOT instruct about {title}",
      "{title}" not in first.split("Current template:")[0])

print()
print("=== PROOF 3: a structurally invalid candidate is rejected BEFORE it is scored ===")
prompts_b, rc_b, out_b = run("EXECUTE_PROMPT", lambda n: "No variables at all here.")
missing_at = out_b.find("Missing required variables")
scored_at = out_b.find("Candidate scores")
check("the missing-variable rejection happened", missing_at != -1)
check("no score was printed for an invalid candidate",
      scored_at == -1 or scored_at > missing_at,
      f"score line at {scored_at} preceded rejection at {missing_at}")
check("the feedback lists the FULL required set, not just the absent ones",
      "must contain all of" in out_b)
check("an all-invalid run still exits nonzero", rc_b == 1, f"rc={rc_b}")

print()
if failures:
    print(f"VERDICT: FAIL — {len(failures)} check(s) failed")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("VERDICT: PASS — all checks passed")
