#!/usr/bin/env python3
"""Build the RSI evalset from RECORDED task outcomes instead of authored taste.

WHAT WAS WRONG WITH THE OLD RULER
`meta/rsi_evalsets/EXECUTE_PROMPT.jsonl` was 576 bytes written on 21 June and never
touched again. Its three cases scored the prompt's TEXT and had never once looked at
whether a task succeeded:

    vars_check     20  all-or-nothing on "{spec}"/"{title}"      -> baseline: full marks
    brevity_check  40  got = weight * (1 - len/max_len)          -> PAYS FOR A SHORTER PROMPT
    clarity_check  40  fraction of 4 keywords present            -> baseline: full marks

Non-gameable headroom was therefore 0.0 against RSI_MARGIN 1.0, so RSI exited
`rc=2 RULER EXHAUSTED` every night — correctly, because the only term with room left
rewarded DELETING instructions from the executor prompt.

WHAT THIS BUILDS INSTEAD
The 742 rejected verification attempts in coordinator.db each carry the verifier's own
reason for rejecting. `rsi_outcome_ledger.classify_attempt` sorts them into levers; the
`prompt_quality_*` ones are the population a better EXECUTE_PROMPT can move. Each becomes
one case, weighted by its MEASURED share, carrying the evidence that produced it.

The division of labour is deliberate and declared, not hidden:
  * DERIVED FROM DATA — which failure modes appear on the ruler at all, and what each is
    worth. A mode that stops occurring loses weight and then drops out entirely. The old
    ruler could not do this; it was frozen the day it was written.
  * AUTHORED ONCE — the remedy wording per mode (REMEDIES below). It is stated as several
    accepted spellings per requirement so the tuner may phrase it its own way, and every
    entry names the recorded reason string it answers.

HONEST LIMIT: a text scorer can still be satisfied by pasting the remedy phrasings in.
That is a real ceiling and it is not fixed here. What IS fixed is the defect that made
the old ruler actively harmful — there is no longer any term that pays for deletion, and
nothing on the ruler that the recorded failures did not put there.

HELD-OUT SPLIT
Attempts are ordered by time and cut in half: the older half sets the `train` weights, the
newer half sets `test`. The mode MIX differs between them (measured 2026-08-07: `unfixed`
dominates the older half, `noproof` the newer), so a prompt tuned to train's mix must still
answer a distribution it was not optimised against.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi_outcome_ledger as ledger  # noqa: E402

DEFAULT_DB = os.path.expanduser("~/.hermes/coordinator.db")
EVALSET_DIR = os.path.expanduser("~/.hermes/meta/rsi_evalsets")

# A mode with fewer than this many recorded attempts is noise; putting it on the ruler
# would pay the tuner for answering something that has barely happened.
MIN_SUPPORT = 10

# The prompt must keep rendering these or the applier rejects it outright.
REQUIRED_VARS = ["{spec}", "{title}"]

# A ceiling, NOT a gradient. `brevity_check` gave partial credit for every character
# removed, which is why the only reachable win was a shorter prompt. This is pass/fail:
# under the cap earns the full weight, over it earns nothing, and there is no incentive
# anywhere in between to delete an instruction.
LENGTH_CAP = 2400

# Remedies. Each requirement is a GROUP of accepted spellings; a group is satisfied when
# any one of them appears. `reason` quotes the verifier string this answers, so a reader
# can trace every case back to the rows that justify it.
REMEDIES = {
    "prompt_quality_unfixed": {
        "reason": "failure condition still present",
        "why": "the executor reported success while the condition it was sent to fix "
               "was still present in ground truth",
        "require": [
            [r"re-?run", r"run .{0,20}again", r"repeat the (check|test|command)"],
            [r"still (present|failing|broken|there)", r"confirm .{0,30}(gone|resolved|fixed)",
             r"verify .{0,30}(fixed|resolved)"],
            [r"report (it as )?fail", r"say .{0,15}failed", r"do not (claim|report) success"],
        ],
    },
    "prompt_quality_noproof": {
        "reason": "acceptance test failed (exit≠0): <diagnostic>",
        "why": "a ground-truth acceptance test rejected the work and named what was wrong",
        "require": [
            [r"exit code", r"exit status", r"non-?zero exit"],
            [r"exact command", r"literal command", r"command you ran", r"verbatim"],
            [r"acceptance test", r"ground truth"],
        ],
    },
    "prompt_quality_prose": {
        "reason": "the evidence does not contain concrete proof / only describes",
        "why": "the executor returned description or intention where output was required",
        "require": [
            [r"do not (describe|narrate|plan)", r"no (plans?|intentions?)",
             r"never .{0,30}would (have )?do"],
            [r"paste", r"include the (actual|real|raw) output", r"actual output"],
            [r"if you (cannot|could not|can'?t)", r"unable to run", r"without tools"],
        ],
    },
}


def build_cases(attempts, split_name):
    """Cases for one half of the corpus, weighted by measured share."""
    counts = {}
    for a in attempts:
        counts[a["lever"]] = counts.get(a["lever"], 0) + 1
    reachable = {k: n for k, n in counts.items()
                 if k.startswith(ledger.PROMPT_REACHABLE_PREFIX) and n >= MIN_SUPPORT}
    total_reachable = sum(reachable.values())

    cases = [
        {"case_id": "vars_check", "split": split_name, "rules": REQUIRED_VARS,
         "weight": 20.0,
         "evidence": {"why": "the applier rejects a template that stops rendering these"}},
        {"case_id": "length_guard", "split": split_name, "max_len": LENGTH_CAP,
         "weight": 10.0,
         "evidence": {"why": "a ceiling with no gradient — replaces brevity_check, which "
                             "paid for deleting instructions"}},
    ]
    if not total_reachable:
        return cases, counts

    for lever, n in sorted(reachable.items(), key=lambda kv: -kv[1]):
        spec = REMEDIES[lever]
        cases.append({
            "case_id": f"outcome_demand:{lever}",
            "split": split_name,
            "weight": round(100.0 * n / total_reachable, 2),
            "require": spec["require"],
            "evidence": {
                "n": n,
                "share_of_prompt_reachable": round(n / total_reachable, 4),
                "verifier_reason": spec["reason"],
                "why": spec["why"],
            },
        })
    return cases, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--prompt", default="EXECUTE_PROMPT")
    ap.add_argument("--out", default=None)
    ap.add_argument("--apply", action="store_true",
                    help="write the evalset; without this it is printed only")
    args = ap.parse_args(argv)

    # A VERIFY_PROMPT ruler CANNOT be built from this corpus, and building one silently would be
    # worse than not building one at all. `ledger.load_attempts` returns rejected EXECUTION
    # attempts, so every `outcome_demand:*` case below is a demand that the EXECUTOR prompt stop
    # producing a failure mode the verifier CAUGHT. Pointed at VERIFY_PROMPT those same cases
    # become demands that the verifier prevent the executor's mistakes — a category error. It
    # would manufacture headroom against the wrong target and let RSI "improve" the proof gate by
    # rewriting it toward executor behaviour, which is the one prompt in the estate where a bad
    # tune is invisible: a weakened verifier reports everything as passing.
    #
    # The evidence a VERIFY_PROMPT ruler actually needs is a record of the VERIFIER being wrong —
    # false rejects and false accepts. Checked 2026-08-08: coordinator.db holds 1,142 `kind='verify'`
    # events and every one is the verifier's judgement ABOUT executor output; no table records
    # whether a judgement was itself correct. Until that measurement exists there is nothing to
    # build from, and the honest output is a refusal.
    #
    # This is the same mistake the authority gate was added to catch (`rsi-tuned-a-lever-with-no-
    # authority`): do not optimise a lever whose authority over the recorded failures is unmeasured.
    # No --force escape hatch on purpose — an override here produces a plausible-looking ruler,
    # which is precisely the failure mode.
    if args.prompt == "VERIFY_PROMPT":
        print("REFUSING: this corpus is rejected EXECUTION attempts, so it can only express "
              "demands on EXECUTE_PROMPT. A VERIFY_PROMPT ruler needs recorded VERIFIER errors "
              "(false rejects / false accepts), and nothing in coordinator.db records whether a "
              "verify judgement was correct. Building from this corpus would score the verifier "
              "against the executor's failure modes.\n"
              "  To unblock: record verifier correctness first, then build from THAT corpus.")
        return 3

    attempts = ledger.load_attempts(args.db)
    if not attempts:
        print(f"REFUSING: no rejected verification attempts in {args.db} — there is no "
              f"recorded evidence to build a ruler from.")
        return 2

    mid = len(attempts) // 2          # already sorted by time in load_attempts
    older, newer = attempts[:mid], attempts[mid:]
    train, tc = build_cases(older, "train")
    test, sc = build_cases(newer, "test")

    demands = [c for c in train if c["case_id"].startswith("outcome_demand")]
    if not demands:
        print(f"REFUSING: no prompt-reachable failure mode clears the support floor "
              f"({MIN_SUPPORT}). Levers seen: {tc}")
        return 2

    print(f"corpus: {len(attempts)} rejected attempts  "
          f"(train={len(older)} older, test={len(newer)} newer)")
    for name, counts in (("train", tc), ("test", sc)):
        print(f"  {name}: " + "  ".join(f"{k}={v}" for k, v in
                                        sorted(counts.items(), key=lambda kv: -kv[1])))
    print("\ncases:")
    for c in train + test:
        w = c["weight"]
        ev = c.get("evidence", {})
        n = f" n={ev['n']}" if "n" in ev else ""
        print(f"  {c['split']:<5} {c['case_id']:<40} weight={w:<6}{n}")

    out = args.out or os.path.join(EVALSET_DIR, f"{args.prompt}.jsonl")
    if not args.apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply to write {out}")
        return 0

    if os.path.exists(out):
        bak = out + ".bak"
        if not os.path.exists(bak):
            os.replace(out, bak)
            print(f"\nprevious ruler preserved at {bak}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for c in train + test:
            f.write(json.dumps(c) + "\n")
    print(f"\nwrote {len(train) + len(test)} cases to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
