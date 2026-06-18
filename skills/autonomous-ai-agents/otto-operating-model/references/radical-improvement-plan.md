# Otto — Radical Improvement Plan (Consolidated)

*Maximises rate of improvement and autonomy. Aggressive on slope; deliberate on ceiling-breaking. The one carve-out — recursive in-loop self-modification of the improver — is excluded on engineering grounds: it removes saturation, which is what makes the system auditable and stoppable. Everything else is here.*

## A. Slope maximisation (climb faster, superlinear early phase)

- Broad-scope early policies — when the store is sparse, prefer wide-coverage rules; disproportionate capability per correction.
- Explicit policy composition — let policies combine and chain so two rules unlock tasks neither enabled alone. Track which compositions fire together and which combos correlate with success.
- Composition surfacing — Otto proposes new general policies synthesised from frequently co-firing specifics. (Promote via the existing confidence/hit logic.)

## B. Autonomous learning (learn without waiting on you)

- Self-detected failure — outcome check per task against explicit success criteria; self-detected failure triggers the same reflect→policy loop a human correction does.
- *Limit kept honest:* errors the system can't see in itself, it won't catch. Self-detection augments your corrections; you stay in the loop for the unseeable class.
- Reflect-on-success too — not just failures: when a task goes unusually well, capture *why* as a positive policy.

## C. Continuous idle work (never idle)

- Self-regression — re-run past failures against current policies; passes feed promotion, fails flag open gaps.
- Gap-finding — scan registry + logs for domains of repeated stumbling with no skill; surface ranked build candidates to you.
- Consolidation — merge duplicates, retire decayed policies, flag conflicts; emit a maintenance report.
- Idle work is pre-emptible by real tasks; compute-capped.

## D. Ceiling-breaking via chained sigmoids (the real "exponential with a limit")

The growth curve is a sigmoid: steep, then asymptote. The asymptote is set by the improver (model + reflection mechanism + eval quality). To break it, improve the improver — manually, between runs. Each upgrade = a fresh sigmoid from a higher floor. Chain them for compounding gains over time.

- Eval quality is the biggest lever — it sets *where* the asymptote sits. Invest most here: better success criteria, better verification signal. Higher eval = higher ceiling.
- Improver versioning — swap stronger models, upgrade the reflection prompt, sharpen eval as discrete, logged, reversible upgrades. Measure the new sigmoid against the old.
- DO between runs, as a human. DON'T wire in-loop/automatic — that removes the saturation that keeps the system predictable and stoppable.

## E. Introspection surface (see and steer all of it)

- `otto-learn list` / `otto-learn trace` — live ruleset, confidence, history, trajectory.
- `otto-why <decision>` — strategist reconstructs rationale from logged context (reconstruction, not ground truth).
- `otto-introspect` — queue, in-flight subagents, memory use, recent failures + recovery.
- Injection log — `~/hermes/logs/injection-log.jsonl`
- Regression dashboard — % of past failures Otto would now pass; the headline improvement metric over time.

## F. Hardening (the four bottlenecks that decide whether this holds or rots)

### F1 — Retrieval is a prerequisite, not a later optimisation
Policy bloat is the *first* wall, and it arrives before you have enough policies for consolidation to help. Inject only the relevant slice per task. A/B gated behind it.

### F2 — The eval needs its own human-graded regression test (most dangerous item)
Self-detection (B) + a gameable eval = optimising for the wrong thing *at speed*; the policy store fills with rules that satisfy the metric and defeat the intent (Goodhart). Principle: the eval must be harder to game than the task is to solve. Teeth:
- Keep a held-out human-graded sample — periodically *you*, not Otto, grade a random slice of self-declared "successes."
- If Otto's self-grade diverges from yours, the eval is drifting → self-detection throttles until re-tuned.
- The eval has its own regression test, graded by you. Without this, autonomous learning is autonomous *mis*-learning.

### F3 — Conflict resolution: precedence + correct scoping, not precedence alone
- "Specific overrides general" is the right *default* — but only safe if the specific policy's scope is correctly tight.
- Route genuine contradictions (two colliding specifics) to the strategist or to you — no static precedence rule resolves a conflict it wasn't designed for.
- Prefer scope + explicit conflict-flagging over opaque policy weights (keeps *why one won* auditable).

### F4 — Confidence spectrum + calibrated flagging
- Grade outcomes on a confidence spectrum, not pass/fail.
- Auto-flag sub-threshold runs (e.g. <85%) for human review.
- Calibrate the threshold against the held-out human sample (F2) — an uncalibrated confidence score is its own Goodhart surface.

## Build order

1. **Injection + outcome log + introspection surface (E)** — see before you scale.
2. **Retrieval layer** — gate for A/B (prerequisite).
3. **Self-detected failure (B)** — the autonomy lever. *Do not enable before the eval-check (F2) below.*
4. **Slope maximisation (A)** — composition + broad early policies.
5. **Idle work (C)** — self-regression, gap-finding, consolidation.
6. **Ceiling-breaking (D)** — eval-quality investment + improver versioning process.

## The one boundary (engineering, not caution)

Improve *what Otto does* and *how fast it does it* freely. Improve *how Otto improves* deliberately, by hand, between runs — never automatically in-loop. That single line is what keeps the system convergent-per-run, auditable, and stoppable. Crossing it removes the ceiling you can see and the off-switch you can reason about — i.e. it takes the system out of your control, which defeats the purpose of building it.
