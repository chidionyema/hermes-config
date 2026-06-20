#!/usr/bin/env python3
"""prove_rsi.py — falsifiable, hermetic proof of the RSI improvement-gate.

Claim under test: the estate adopts a prompt change ONLY when an independent
verifier confirms it scores higher on a HELD-OUT eval split (split='test') that
the tuner never optimized against. A candidate that does not beat the baseline
on the held-out set is rejected.

This proof is HERMETIC (no LLM / no network): it seeds the evidence ledger with
a baseline + an improved candidate (fixtures) and lets evidence_verify.py
independently re-score them on the held-out split and sign. It is CAUSAL and
FALSIFIABLE:

  positive   : candidate beats baseline on held-out test -> verifier PASS (GREEN)
  --negative : candidate == baseline (no delta)          -> verifier FAIL (RED)

The live loop (rsi-orchestrator.py --run-prompt-tune) writes evidence entries of
the SAME shape from real LLM-generated candidates; the verifier treats them
identically. This harness proves the GATE+VERIFIER are sound without depending on
a flaky external model — exactly as prove_learning.py uses a synthetic
fingerprint to prove the known-class mechanism.

Modes:
  (no arg) / --seed   seed the rsi evidence entry from the IMPROVED fixture
  --negative          seed an entry whose candidate does NOT improve (RED demo)
  --rescore --id ID   re-score the stored entry's prompts on the held-out test
                      split and print the delta (this is the reproduce_cmd a
                      human runs; exits 0 iff candidate beats baseline + margin)
"""
import os
import sys
import json

HERMES = os.path.expanduser("~/.hermes")
SCRIPTS = os.path.join(HERMES, "scripts")
EVALSET_DIR = os.path.join(HERMES, "meta", "rsi_evalsets")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import coordinator as C

PROMPT_VAR = "EXECUTE_PROMPT"
RSI_MARGIN = 1.0
EID = "proof-rsi-synthetic"

# Fixtures. BASELINE is verbose and omits the held-out keywords; CANDIDATE is
# concise and concrete -> it wins on the TEST split (brevity + clarity) that the
# tuner never optimized against. Both keep the required {spec}/{title} vars.
BASELINE = (
    "You are the EXECUTOR. Please carry out the following specification described "
    "here, namely {spec}, for the task titled {title}, and then go ahead and write "
    "up an extremely long and detailed narrative explaining everything you did, "
    "step by step, in as much depth and length as you possibly can manage."
)
CANDIDATE = (
    "Execute {spec} for {title}. Return a concrete, factual report with evidence "
    "of the result."
)


def _score(prompt_var, prompt_text, split):
    """Local copy of the deterministic scorer (kept self-contained)."""
    path = os.path.join(EVALSET_DIR, "%s.jsonl" % prompt_var)
    if not os.path.exists(path):
        return 0.0
    score = 0.0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rule = json.loads(line)
            except ValueError:
                continue
            if split is not None and rule.get("split") not in (split, None):
                continue
            case_id = rule.get("case_id")
            weight = rule.get("weight", 0.0)
            if case_id == "vars_check":
                if all(v in prompt_text for v in rule.get("rules", [])):
                    score += weight
            elif case_id == "brevity_check":
                max_len = rule.get("max_len", 500)
                if len(prompt_text) < max_len:
                    score += weight * (1.0 - (len(prompt_text) / max_len))
            elif case_id in ("clarity_check", "adversarial_check"):
                kws = rule.get("keywords", [])
                if kws:
                    matches = sum(1 for kw in kws if kw.lower() in prompt_text.lower())
                    score += weight * (matches / len(kws))
    return round(score, 2)


def _evalset_hash(prompt_var):
    import hashlib
    path = os.path.join(EVALSET_DIR, "%s.jsonl" % prompt_var)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_seed(negative=False):
    """Seed an UNVERIFIED rsi evidence entry from the fixtures."""
    candidate = BASELINE if negative else CANDIDATE
    base_train = _score(PROMPT_VAR, BASELINE, "train")
    cand_train = _score(PROMPT_VAR, candidate, "train")
    base_test = _score(PROMPT_VAR, BASELINE, "test")
    cand_test = _score(PROMPT_VAR, candidate, "test")

    conn = C.connect()
    try:
        C.log_evidence(
            conn=conn,
            id=EID,
            loop="rsi",
            kind="prompt_tuning",
            claim="Prompt template %s improved on a held-out eval set" % PROMPT_VAR,
            control="held_out_eval",
            before=str(base_test),
            after=str(cand_test),
            margin=round(cand_test - base_test, 2),
            artifacts={
                "prompt_variable": PROMPT_VAR,
                "baseline_prompt": BASELINE,
                "candidate_prompt": candidate,
                "baseline_train": base_train,
                "candidate_train": cand_train,
                "baseline_test": base_test,
                "candidate_test": cand_test,
                "evalset_hash": _evalset_hash(PROMPT_VAR),
                "synthetic": True,
                "negative": negative,
            },
            reproduce_cmd="python3 %s/prove_rsi.py --rescore --id %s" % (SCRIPTS, EID),
            level=2,
            verifier_verdict="UNVERIFIED",
        )
        print("  seed%s: rsi evidence %s written (UNVERIFIED) — train %.1f->%.1f, held-out test %.1f->%.1f"
              % (" (negative)" if negative else "", EID, base_train, cand_train, base_test, cand_test))
        return True
    finally:
        conn.close()


def _load_entry(eid):
    conn = C.connect()
    try:
        row = conn.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def run_rescore(eid):
    """Re-score the stored entry's prompts on the held-out test split (reproduce_cmd)."""
    entry = _load_entry(eid)
    if not entry:
        print("  ❌ no evidence entry %r" % eid)
        return False
    art = json.loads(entry["artifacts"]) if isinstance(entry["artifacts"], str) else entry["artifacts"]
    pv = art.get("prompt_variable")
    base = art.get("baseline_prompt")
    cand = art.get("candidate_prompt")
    if not pv or base is None or cand is None:
        print("  ❌ entry %r missing prompts to re-score" % eid)
        return False
    base_test = _score(pv, base, "test")
    cand_test = _score(pv, cand, "test")
    ok = cand_test > base_test + RSI_MARGIN
    print("PROOF_RESULT " + json.dumps({
        "prompt_variable": pv,
        "baseline_test": base_test,
        "candidate_test": cand_test,
        "margin": round(cand_test - base_test, 2),
        "pass": ok,
    }))
    if ok:
        print("  PASS — candidate beats baseline on held-out test by %.2f (>%.1f)." % (cand_test - base_test, RSI_MARGIN))
    else:
        print("  FAIL — no held-out improvement (%.2f vs %.2f, need +%.1f)." % (cand_test, base_test, RSI_MARGIN))
    return ok


if __name__ == "__main__":
    if "--rescore" in sys.argv:
        eid = EID
        if "--id" in sys.argv:
            eid = sys.argv[sys.argv.index("--id") + 1]
        sys.exit(0 if run_rescore(eid) else 1)
    if "--negative" in sys.argv:
        sys.exit(0 if run_seed(negative=True) else 1)
    sys.exit(0 if run_seed(negative=False) else 1)
