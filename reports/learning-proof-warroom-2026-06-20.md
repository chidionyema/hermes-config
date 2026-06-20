# War-Room Build Spec — Provable Autonomous Learning & Improvement

**Date:** 2026-06-20 · **Author:** Claude (Opus 4.8, design) · **Execute on:** Fable 5, fresh session
**Mandate (founder, mission-critical):** *"I need to see provable evidence of autonomous learning and improvement."*
**Scope chosen:** Both loops + full evidence ledger (the largest option).

---

## 0. The hard truth this spec is built on (3 independent audits, 2026-06-20)

Three separate recon agents audited disjoint parts of the estate. They independently agreed:

**Autonomous OPERATION works** (~67% of failures fixed with no human; the verifier is independent — no self-grading; `EscalationWithoutDiagnosis` is structurally enforced). **Autonomous LEARNING does not exist** — the loops are open / write-only:

1. **RSI (`scripts/rsi-orchestrator.py`)** — L0 FAIL. Three dimensions (skill-gen lines 101–223, prompt-tune 309–441, code-refactor 505–665). **Never autonomously invoked** (manual CLI only — no daemon/cron/launchd ref). The single receipt `meta/proofs/proof-prompt_tuning-1781974643.json` **fails signature verification** under the current key. `get_signing_key()` (line 53) self-generates+holds the key → receipts are **forgeable by the writer**. Every gate is **regression-only** ("tests still pass"), never **improvement** ("metric moved vs control").
2. **Operational learning (`coordinator.py propose_known_class` ~line 1051)** — BROKEN EDGE. Writes proposals to `queue/known-class-proposals.jsonl` (line ~1066). **Nothing ever reads that file.** Registry (`known_classes.py`) is 10 static hardcoded classes. Even if a class recurred it would re-escalate identically. Also: **zero recurrence** in the data (18 unique fingerprints, each once) — loop is untested anyway.
3. **Reflection / idle-learning / pulse** — THEATER. `reflect-on-correction` appends identical hardcoded strings ~13×/day; `improvement-pulse` writes blank templates; idle-learning's only success metric is `exit 0`. **Zero** policies created / skills retired / prompts changed / behaviors altered traceable to any of it. *"Outputs are terminal nodes in a graph with no outgoing edges."*

**Two structural defects underneath everything:** (a) no feedback edge (analysis → markdown nothing reads); (b) regression gates, not improvement gates.

---

## 1. Definition of "provable" (the bar — do not lower it)

Every ledger entry must be all three:
- **Independent** — verdict produced by a process/key the *changing* agent does not control.
- **Falsifiable** — re-runnable to a hard PASS/FAIL via a stored `reproduce_cmd`.
- **Causal** — improvement attributable to a specific change vs a recorded control, not a drifting number.

Evidence-strength levels (label every entry): **L0** did-it-run · **L1** passed-independent-gate · **L2** causally-improved-vs-control · **L3** compounding-over-time. Target: reach **L2** for both loops, design for L3.

---

## 2. Component 0 — The Evidence Ledger (the spine; build first)

**Goal:** a durable, independently-signed record of falsifiable learning proofs. Starts RED (0 verified). This *is* the thing the founder looks at.

- **Store:** new sqlite table `evidence` in `coordinator.db` (queryable + trends) PLUS append-only mirror `meta/evidence/ledger.jsonl` (tamper-evident).
- **Entry schema:** `id, ts, loop ('known_class'|'rsi'), kind, claim (human str), control (pre-change outcome/metric), before, after, margin, artifacts {fingerprint_hash, evalset_hash, git_sha, test_output_sha}, reproduce_cmd (exact CLI to re-run the proof), level (L0..L3), verifier_verdict ('PASS'|'FAIL'|'UNVERIFIED'), verifier_sig`.
- **Independent verifier:** `scripts/evidence_verify.py` — a SEPARATE process that, per entry, re-runs `reproduce_cmd`, compares to recorded before/after, and signs the verdict with a key at `meta/.evidence_verifier_key` (generated once, `chmod 600`, **never** read by `rsi-orchestrator.py` or the executor). Independence = the writer can't mint a PASS.
- **Surfaces:** `coordinator.py evidence` (CLI) + Telegram "Otto, prove you're learning" → renders GREEN/RED with `verified_count` and, per proof, the `reproduce_cmd` the founder can run themselves. Replace the reflect view's self-claimed RSI block with this ledger.
- **Acceptance:** ledger renders RED with 0 verified entries on first run (honest baseline). `evidence_verify.py` on an empty ledger returns "0 verified — no learning proven yet."

---

## 3. Component A — Close the operational-learning loop (known-class) → first GREEN

**Fix the broken edge, then prove it with a controlled replay.**

1. `coordinator.load_proposals()` — read `queue/known-class-proposals.jsonl`, merge into the active registry consulted during `ingest_failures`/classification. Dedup by fingerprint. Auto-handlers must respect the Phase-0 read-only probe guard (no money/identity/contract auto-action — fence stays).
2. Wire `load_proposals()` into the classification path so a proposed class is auto-handled on recurrence. On auto-handling a class that was *previously escalated*, emit event `class_auto_learned` and write an evidence entry.
3. **Proof harness `scripts/prove_learning.py`** (runs against a SANDBOX coordinator.db or a clearly-namespaced synthetic `__proof__` fingerprint it cleans up — never pollute live state):
   - **Control:** ensure class unknown → inject synthetic fingerprint → assert **ESCALATES** (no handler). Record.
   - **Learn:** run propose→`load_proposals` so the class becomes known with a safe probe handler.
   - **Treatment:** re-inject the **same** fingerprint → assert **AUTO-RESOLVES**, zero escalation, zero human ping. Record.
   - Write ledger entry: `control=escalated, after=auto_resolved, reproduce_cmd="python3 scripts/prove_learning.py --replay"`, level L2. `evidence_verify.py` independently re-runs control+treatment to sign PASS.

**Result:** ≥1 independently-verified, re-runnable, causal proof of operational learning. Ledger flips GREEN.

---

## 4. Component B — RSI improvement-gate (replace regression gate with improvement proof)

1. **Held-out eval sets:** per tunable prompt (EXECUTE_PROMPT, VERIFY_PROMPT) a fixed corpus `meta/rsi_evalsets/<prompt>.jsonl` of `(input, expected)` with a deterministic scorer + stored hash.
2. **Acceptance = improvement, not regression:** baseline_score on held-out set → apply candidate → candidate_score on the **same** set → ACCEPT only if `candidate_score > baseline_score + margin` (margin beyond measured noise) AND regression tests still pass. Record both numbers.
3. **Receipt becomes a ledger entry** signed by the **independent verifier key** — `evidence_verify.py` re-runs the eval set itself; it does not trust the orchestrator's reported numbers. Kill the self-signed-as-proof pattern (orchestrator may still sign for integrity, but acceptance requires the verifier's signature).
4. **Autonomous invocation, fenced:** wire RSI to run on a safe cadence (launchd/cron). Auto-apply ONLY low-risk prompt tunes that pass the improvement-gate. Anything touching money/identity/contract/code → Telegram Double-Key Lock (human merge). This is the founder-fence; do not decouple it.

**Result:** ≥1 independently-verified RSI improvement proof (before/after numbers on a held-out set), re-runnable.

---

## 5. Component C — Kill the theater (honesty pass)

- Stop `reflect-on-correction` emitting hardcoded "Policy 004 has 0 hits" lies and `improvement-pulse` emitting blank templates — they pollute the strategist audit and the reflect view with false "improvement" signal.
- Reflect/learning surfaces must source **only** from the evidence ledger (verified proofs), never from self-claimed markdown.

---

## 6. Constraints / risks (carry into the build)

- **Founder-fence:** auto-apply low-risk only; money/identity/contract self-mods stay human-merge.
- **Lane guard:** `coordinator.py | config.yaml | plugins/otto-inbound/ | gateway/` need `HERMES_LANE=claude` to commit. `scripts/` (new modules) + `meta/` are free.
- **Concurrency:** Gemini edits `~/.hermes/scripts` — keep new modules self-contained; verify on disk (never trust self-attestation — that's the whole point here).
- **Runtime:** daemon = system py3.14, venv = 3.11 → keep modules 3.14-clean.
- **No live pollution:** proof harness uses sandbox db or a self-cleaning synthetic fingerprint with no real side effects.
- **Pre-commit gate** compiles staged .py + enforces lane — commit protected files with `HERMES_LANE=claude`.

## 7. Build order (for the Fable session)

1. Component 0 ledger + `evidence_verify.py` + independent key + `coordinator.py evidence` + Telegram surface → prove it renders RED.
2. Component A `load_proposals` + wiring + `prove_learning.py` → flip ledger GREEN with the operational-learning replay. **This is the first provable win — do it before B.**
3. Component B eval sets + improvement-gate + fenced autonomous invocation → second GREEN.
4. Component C honesty pass.
5. Fold in the earlier observability work (decoupled hourly snapshot via launchd `ai.hermes.progress`, already designed) so the autonomy trend accrues hang-proof alongside the ledger.

## 8. Definition of done

`Otto, prove you're learning` returns ≥2 independently-verified proofs (1 operational, 1 RSI), each with a `reproduce_cmd` the founder runs to re-confirm PASS, signed by a key the modifying agent never held. Ledger went RED→GREEN on real, controlled, falsifiable evidence — not attestation.
