# Dispatch Discipline — Worked Examples

Concrete walk-throughs of the greenlight-before-spawn rule and the menu pattern, from real session transcripts. The general rule is in SKILL.md §"Greenlight-Before-Spawn & Mid-Flight Steering Discipline". These are the worked examples.

## Example 1: The CV mistake (2026-06-17)

**What happened:**

User said: *"Ok keep going"* and *"Sure let's get it all done"* across two turns. Both were imperatives with no scope.

I dispatched five subagents in one batch:
1. Fix the Signal Engine test parser (real defect, evidence-based)
2. Draft CV bullets (user-facing deliverable)
3. Write a POPDD marketing checklist reference doc
4. Commit + push LUX to GitHub
5. Run Signal Engine full test suite (background)

User then said: *"Regarding the cv don't do that yet"*

The CV subagent was item 2 in the batch. It ran. It finished. It wrote `/Users/chidionyema/cv_bullets_2026-06-17.md`. I had to acknowledge, treat it as discarded, and not paste anything.

**What I should have done:**

```
"5 things came up. Here's the menu, ranked by interrupt cost:

 1. (1 subagent, ~20s) Commit + push LUX to GitHub — already staged, mirror popdd-ts
 2. (1 inline, ~5s)   Commit popdd_verify.py in signalengine + prospector
 3. (1 background, 5-10min) Run Signal Engine's full 309-test suite
 4. (1 subagent, ~30s) Apply the LinkedIn article fixes using the new checklist
 5. CV — needs scope: which file is canonical, redline vs rewrite, what voice?

I won't dispatch #5 until you tell me which mode. Pick 1-4 to start, or all 5 if you confirm CV scope."
```

That reply:
- Surfaces the menu (the user's actual ask)
- Tags each item with cost (so they can sequence)
- Flags #5 as scope-needed, doesn't dispatch
- Lets them pick a wave instead of me picking one for them

**The takeaway:** an imperative without scope is not scope agreement. "Let's get it all done" means "show me everything you think is actionable and let me pick."

## Example 2: The parser bug cop-out (same session)

I shipped a `popdd_verify.py` script that emitted `passed=0, failed=0` while the test suite actually ran cleanly. I noted the bug, said "trivial, didn't block the goal", and moved on. The user replied:

> *"Next time don't wait for me to ask, be proactive, and learn from this, you are supposed to give me a heavenly experience and we are not there yet."*

That's the "fix-attempt first, disclose only if attempt fails" rule written explicitly. The defect was in my shipped work; my fix budget was 5 minutes; I should have dispatched the parser fix immediately, not noted it.

**The decision table from SKILL.md applied:**

| Defect | Fix-cost | Right action | What I did | Wrong because |
|---|---|---|---|---|
| Parser regex misses pytest 9.x `-q` summary | 5 min | Fix now | Noted as "trivial" | Defect was in shipped code, in scope, fix was 5 min |
| Real test counts (69 passed) not in signed receipt | 5 min | Fix now | Said "chain valid regardless" | Receipt = attestation; wrong numbers = false attestation |

**The takeaway:** when the receipt says 0/0 and the real test run says 69/0, the receipt is a lie regardless of whether the chain signature is valid. POPDD's value is precisely that a signed false attestation is detectable. Shipping one anyway defeats the purpose.

## Example 3: When greenlight IS automatic (the inverse)

Not every dispatch needs scope agreement. Things that don't write user-facing artifacts:

- Running tests
- Reading files
- Listing directories
- Computing values
- Searching/grepping
- Building (if the build doesn't write to user-visible state)

The pattern: if the output is **internal evidence** (test results, file contents, search results, computed numbers), no greenlight needed. If the output is **user-facing text** (CV bullets, READMEs, marketing, comments on PRs), greenlight first.

The sharp line: *will the user see this text attributed to them, or see it as my evidence?* If attributed to them, greenlight. If it's my evidence for a decision I'll surface, no greenlight.

## The Failure Mode Catalog

A list of session-biting mistakes and their canonical fix. Each one is an example of the general rule, not a new rule.

### "I'll just note the bug"

Symptom: defect discovered mid-task, user told "I'll fix later", task marked done. Fix: the decision table above. If fix-cost < 1 hour AND the defect is in the work I'm shipping, fix it now.

### "I dispatched 5 things at once"

Symptom: a single tool-call batch contains 3+ subagents writing user-facing text. Fix: cap the writing batch at 1 (or 0 if scope isn't agreed), fill the rest with evidence-gathering subagents.

### "The user said 'go', so I went"

Symptom: imperative without scope is treated as scope agreement. Fix: imperatives without scope trigger the menu pattern, not execution. Reply with the menu first.

### "I finished A, now what?"

Symptom: task ends with a status update, no forward motion. Fix: every task end surfaces "what's still actionable" alongside the completion report. The menu is always the last thing the user sees in a turn.

### "I started a 5-minute subagent and you can't stop me"

Symptom: user sends a steering message mid-subagent. Fix: stage the subagent goal so it has a "stage 2" hook that re-checks the priority queue. The user can interrupt at the stage boundary even if they can't kill the subagent mid-stage.

### "I substituted a docstring for a fix"

Symptom: a defect is documented in a comment, a TODO, or a follow-up file instead of fixed. Fix: TODO comments are only acceptable when the fix is genuinely >1 hour. Inline fixes always win.

### "I asked the user 4 questions in a row"

Symptom: each batched question blocks the next. Fix: batch all questions into one structured menu, not multiple back-to-back turns. The user gets one prompt with one decision surface, not a fill-in-the-blank game.

## Quick checklist before any `delegate_task`

Run through this in <2 seconds before dispatching:

- [ ] Does the goal include "draft", "write", "compose", "generate", "produce", "create"?
- [ ] If yes: have I gotten scope agreement on what to write? If no, send the menu.
- [ ] Is the wall-time budget > 30s? If yes, is it staged? If no, can I trim it?
- [ ] Does the work need user input mid-flight? If yes, stage the subagent so it can pause.
- [ ] Is the output user-facing text attributed to them? If yes, greenlight.
- [ ] Is the output evidence for my next decision? If yes, dispatch without greenlight.

If any checkbox is unclear, the dispatch is wrong. Pause and ask.
