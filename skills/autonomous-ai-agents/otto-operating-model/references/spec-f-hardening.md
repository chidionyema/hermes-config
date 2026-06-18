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

## Verified build order (updated 2026-06-18)

1. **E:** Introspection surface ✅ Done — `otto-introspect.py`, `otto-learn.py`, injection log live
2. **F1:** Retrieval layer ✅ Done — ONNX embedding recall (all-MiniLM-L6-v2, 384-dim) + tag-filter + self-query routing. Injects only relevant policy slice per task. Files: `scripts/retrieval/embedding_recall.py`, `scripts/retrieval/tag_filter.py`
3. **F2:** Eval regression ✅ Done — confidence spectrum (0.0-1.0) replaces binary PASS/FAIL. Passive divergence detection uses user corrections as holdout. Files: `scripts/eval-confidence.py`
4. **B:** Self-detected failure ✅ Done — `scripts/self-detect.py` scans recent evaluations during idle, auto-writes policies for FAILs
5. **A:** Policy composition ✅ Done — co-firing analysis + auto-apply in idle pipeline. `scripts/policy-composer.py`
6. **F3:** Conflict resolution ✅ Done — scope analysis + contradiction detection + specific-over-general resolution + escalation. `scripts/conflict-resolver.py`
7. **C:** Idle work ✅ Done — consolidation, self-regression, gap-finding in idle pipeline
8. **F4:** Confidence calibration ⏳ Holdout corpus needs 5+ corrections to calibrate. No active work needed
9. **D:** Ceiling-breaking ✅ Done — meta-improver, SHA-256 hash verification, snapshots, rollback
