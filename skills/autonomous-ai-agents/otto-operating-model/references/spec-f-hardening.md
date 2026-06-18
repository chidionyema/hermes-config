# Section F — Hardening (Added 2026-06-18)

## Build order changes

The spec now has two hard prerequisites before A and B can ship:

1. **Injection + outcome log (E)** — already built
2. **Retrieval layer** (tag-filter + embedding recall net + routing self-query) — **NOT built, blocks A & B**

Without retrieval, policy bloat causes lost-in-the-middle degradation the moment more policies inject than fit in context. A and B *actively make Otto worse* if shipped before retrieval is live.

## The four bottlenecks

### F1 — Retrieval is a prerequisite, not optimisation
- Tag-filter + embedding + self-query routing must be live before A or B ships
- Inject only the relevant policy slice per task
- Blocked by: needs design + implementation

### F2 — Eval regression (human-graded)
Most dangerous item. Self-detection (B) + a gameable eval = optimising for the wrong thing at speed. The policy store fills with rules that satisfy the metric and defeat intent (Goodhart).
- Held-out human-graded sample: periodically *user*, not Otto, grades a random slice of self-declared "successes"
- If Otto's self-grade diverges from user's → eval is drifting → self-detection throttles until re-tuned
- Eval has its own regression test, graded by user
- Without this, autonomous learning is autonomous *mis*-learning

### F3 — Conflict resolution
- "Specific overrides general" is the right default — but only safe if the specific policy's scope is correctly tight
- Route genuine contradictions (two colliding specifics) to strategist or user — no static precedence rule resolves a conflict it wasn't designed for
- Prefer scope + explicit conflict-flagging over opaque policy weights (keeps why-one-won auditable)

### F4 — Confidence calibration
- Grade outcomes on confidence spectrum, not pass/fail
- Auto-flag sub-threshold runs (<85%) for human review
- Calibrate threshold against held-out sample (F2) — uncalibrated confidence is its own Goodhart surface

## Verified build order

1. **E:** Introspection surface ✅ Done
2. **F1:** Retrieval layer ❌ Need to build
3. **F2:** Eval regression ❌ Need to build (blocks B)
4. **B:** Self-detected failure ✅ Script exists, gated by F1+F2
5. **A:** Policy composition ✅ Script exists, gated by F1
6. **F3:** Conflict resolution ❌ Need to build (ships with A)
7. **C:** Idle work ✅ Done
8. **F4:** Confidence calibration ❌ Depends on F2
9. **D:** Ceiling-breaking ✅ Improver versioning done
