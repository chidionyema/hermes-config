# Hermes v2 — design

Status: PROPOSED, 2026-08-06. Nothing here is built yet.
Companion to `ESTATE_STATE.md` (which defines *what done means* and must be rewritten by Layer 4).

---

## 1. Diagnosis

One sentence: **every measurement in this estate is either authored by the thing being
measured, or grades text instead of behaviour.**

Three defects, each proven on disk:

| # | Defect | Evidence |
|---|---|---|
| 1 | The hard gate that rejects narration tests a marker nothing emits | producer `coordinator.py:1230` emits `[executor-narrative-fallback`; gate `coordinator.py:1336` tests `[agentic-exec-fallback`. Repo-wide the old spelling survives **only** in `scripts/test_coordinator.py:303,577` — the test pins the dead string, so CI stays green while the gate is dead in production. DB: 14 rows old marker, 287 rows new. |
| 2 | A carve-out accepts narration as proof | `coordinator.py:1351-1354`. 67 of the 279 fabricated closes came through this door. |
| 3 | The LLM writes its own exam | 210 of the 279 passed a *runnable* acceptance test authored by the same intelligence doing the work. Samples: `pgrep -f 'realtime-demo'`, `which /opt/ops/.../full-audit.sh`, `grep -q 'goal_of_the_day' /etc/crontab`, and one invoking a hallucinated `some_command_that_used_to_hang`. |

Defects 1 and 2 landed in the **same commit**: `4b1c8c6`, 2026-06-24,
*"coordinator: never-fail executor + verify carve-out for injected tasks"*.
Fallback rate by day: 06-23 = 14%, **06-24 = 87%**, every day since = 88–100%.
279 of 398 `done` tasks (70%) are stored narration.

The RSI layer has defect 3 in pure form: `rsi-orchestrator.py:119-161` `score_prompt`
scores a prompt on whether its **text** contains required substrings, is short, and contains
keywords. It never runs the prompt. Corpus: `meta/rsi_evalsets/EXECUTE_PROMPT.jsonl` =
**6 cases, 576 bytes**. `logs/holdout-corpus.json` = empty list. Hence 7 weeks, 0 accepted
improvements, and `meta/improver-versions.jsonl` = 1 row with `total_changes_applied: 0`.

**What is already right and must be kept.** `verify()` (`coordinator.py:1305`) is correctly
designed — *"Done only when GROUND TRUTH confirms the failure is gone — no self-grading"* —
and runs the acceptance test before any judge. `score_prompt`'s train/test split is the right
instinct (its docstring correctly argues it makes the gate falsifiable rather than tautological).
POPDD signed receipts exist. The money/identity fence has **0 violations**. The architecture
encodes the right principles; the measurements just never touch reality.

---

## 2. Principles

1. **Fitness comes from the world.** A shell exit code, an artifact on disk, a daemon tick —
   never a model's account of its own work.
2. **The ruler is authored independently of the work, and is unwriteable by the worker.**
   External is not sufficient — it must also be held out. (ImpossibleBench: frontier models
   exploit visible tests 76% of the time; hiding the test files drops it to ~zero.)
3. **A verifier is necessary but not sufficient.** Darwin Gödel Machine had real executed
   benchmarks and still fabricated tool-execution logs; told to fix hallucination, it scored
   2.0/2.0 by deleting the markers the reward function used to detect it. What caught it was
   **traceable lineage**, not the objective. Hence: every accepted change = one commit + a
   receipt holding the raw command output + a one-line revert.
4. **Accumulate evidence; bound artifacts.** The task ledger is append-only and never discarded
   (recursive training on self-generated data collapses *only* when synthetic replaces real; if
   data accumulate, test error has a finite bound). The *active skill set* is capped and retires
   losers — Ratchet's non-divergence bound is finite only because both the cap and the threshold
   are finite; an append-only skill archive costs ~8.6 points in GRASP's ablation.
5. **Never an LLM judge as the accept gate.** A null model emitting one constant string wins
   86.5% LC on AlpacaEval 2.0; judge self-preference ranges −38% to +90%, so no constant
   correction fixes it. Keep the judge as an advisory signal that is logged, never as the gate.

---

## 3. Layers

### Layer 0 — honesty (~2h, reversible)

- `coordinator.py:1336` — fix the marker. **Do not just patch the string:** hoist it to one
  module constant `FALLBACK_MARKER` consumed by producer, gate, *and* test. The root cause was
  three independent spellings of one fact; a shared constant is the actual fix.
- `coordinator.py:1351-1354` — narrow the carve-out to `kind == "injected" AND source ==
  "telegram"` (genuine founder chat). It must never be reachable by project/work tasks.
- Backfill the 279 to `failed`. Numbers become real.
- Probe reports verified passes instead of presence.

### Layer 1 — the unfakeable gate (~1d)

- **Pre-registration (red-then-green).** At task creation, run the acceptance test. **Exit 0 →
  reject the task as vacuous.** A criterion that already passes proves nothing. This kills all
  210 vacuous closes at source, needs no LLM, and makes gaming self-defeating: an easier test is
  more likely to pass at creation and be rejected.
- **Unwriteable.** Acceptance tests live outside the executor's cwd; the executor deny-list
  forbids writing them. Today `executor-settings.json` protects itself and `.env` but not the
  task spec.
- **Independent authorship.** Strategist emits the acceptance test (`coordinator.py:805`);
  the executor's prompt never contains it. *OPEN CHECK: confirm the executor prompt does not
  currently receive `spec.acceptance_test`.*
- **Demote the judge.** `coordinator.py:1360-1363` moves from accept-path to advisory-log.
- Raise the 30s executor timeout (`CIRCUIT_BREAKER_TIMEOUT_S`, `coordinator.py:1212`) — 76+ of
  the 279 are `claude: timeout after 30s`. Gated on the capacity decision in §5.
- Fix the 5 invalid `Write(**/...)` deny rules in `executor-settings.json:52-61` (Claude Code
  rejects them: only `Edit(path)` rules cover file-editing tools).

### Layer 2 — RSI with a real fitness function (~2d)

**Corpus = the task ledger.** 417 rows today, ~294 with a real acceptance test, growing daily.
Each row is (fingerprint/spec) → (acceptance test) → (pass/fail). Domain-specific, labelled by
exit codes, and something no paper's benchmark can give you: it is *your* estate.

**Probe.** Fixed, stratified, **20–100 items** — not more. (Decagon's ablation: 500 examples
performed 2% *worse* than 100, while inflating prompt length 75%.) Split ~50/50
previously-failing / previously-passing; the previously-passing half is what detects
regressions. Stored outside the agent's write path. Grow by appending; never rotate out old
items, or scores stop being comparable.

**Loop.**
```
propose   → mutate ONE artifact (prompt / skill / policy / executor config). Frozen weights.
evaluate  → staged cascade: static check → sandbox replay of ~10 → full probe (20–100)
score     → F = previously-failing now passing;  R = previously-passing now failing
accept    → (F − F₀) − (R − R₀) > τ   AND   R ≤ R₀
apply     → one commit + POPDD receipt {F₀,R₀,F,R, raw output} + revert token
```
The accept rule is GRASP's, and it is the load-bearing part: with the gate 88.8%, without it
40.1% — identical to the no-skills baseline — while a matched-compute control that runs the
probe and *ignores* its verdict scores 67.2%. The gain is the gate, not the compute. Its
regression half alone is worth ~7 points. `τ` is a real margin, not `> 0`.

**Re-measure `F₀/R₀` every round** against the current live artifact set. A stale baseline is
how a no-op gets accepted.

Retire `score_prompt`. Keep its train/test instinct; replace its content.

### Layer 3 — skill accumulation (~1–2d) — where compounding actually lives

- A task passing pre-registered acceptance gets its procedure distilled into a parameterised
  skill with its acceptance test attached.
- A matching fingerprint then runs **deterministically, zero LLM calls**.
- **Hard cap (start C=50) + retirement** when a skill's contribution ≤ −τ after N_min trials.
  Not append-only.
- Fitness: **% of failures resolved with zero LLM calls** and **cost per resolved failure**.
  Both are produced by processes the agent does not author.
- Precedent inside this estate: the auto-fixer is a hand-written instance of exactly this —
  107 runs over 4 days across 3 problem classes. **Corrected 2026-08-06: this previously read
  "61 real fixes… the pattern demonstrably works here." It does not demonstrate that** — see the
  retraction in §5. 59 of the 61 are one procedure (retry git push) that never reads the push's
  exit code and has no `verify_fix` branch, leaving **2 verified recoveries** as the real total.
  The auto-fixer is still the right *shape* for Layer 3; it is not evidence that the shape works.
  Layer 3 learns these procedures instead of hand-writing them — and unlike the auto-fixer,
  every learned skill carries its own acceptance test, which is precisely the missing piece.

### Layer 4 — observation

- `verify_estate.sh` R1–R5 currently assert presence: `otto-inbound imports glob` (`:205`) is
  the proof that "reports delivered to Telegram"; R1 is `all present in portfolio` (`:179`).
  Replace with ledger counters: verified passes / 7d, % resolved deterministically,
  cost per resolved failure. **If verified passes is 0, the estate is DEGRADED however many
  ticks fired.**
- Telegram contract: **DECISION NEEDED · DELIVERED (with the acceptance command that passed) ·
  BROKEN (escalated after N attempts)**. Nothing else is pushed. Today **28 of 32 cron jobs**
  push to Telegram; the reflection/digest/pulse family write to the ledger and become readable
  on demand instead. Jobs keep running; they stop narrating. Silence becomes meaningful.

---

## 4. RSI control plane in Telegram (founder requirement, 2026-08-06)

**Cadence starts frequent and is tunable.** Daily or 6-hourly while the corpus is small and
mutations are cheap; not weekly. Backed by a spend cap that throttles automatically.

**Safety property, not just convenience: the founder's Telegram UI is the ONLY writer of the
RSI gate parameters. The agent reads them and can never write them.** This is principle 2
applied to the optimiser itself — an RSI that can edit its own accept threshold, probe
composition, or budget has no gate at all. Config lives in one JSON outside the agent's write
path; the orchestrator re-reads it each cycle.

Commands (all with inline buttons; approval buttons already exist at
`rsi-orchestrator.py:351`):

| Command | Purpose |
|---|---|
| `/rsi status` | live F₀/R₀, probe size + stratification, last cycle, staged candidates, spend today |
| `/rsi run [artifact]` | trigger a cycle now |
| `/rsi cadence <interval>` | set schedule (default: 6h initially) |
| `/rsi autopilot on\|off` | accepted candidates apply automatically, or wait for approval |
| `/rsi candidates` | staged candidates with F/R deltas and diffs |
| `/rsi approve\|reject <id>` | act on one |
| `/rsi rollback <id>` | revert an applied change via its receipt token |
| `/rsi probe` | probe composition; add/remove items |
| `/rsi threshold <τ>` | accept margin |
| `/rsi budget <usd>` | hard cap; auto-throttles cadence |
| `/rsi skills` | active skills, contribution scores, cap usage; manual retire |
| `/rsi pause\|resume` | halt the loop |

**Overfitting guard, required because cadence is high.** More frequent cycles = more chances to
fit the fixed probe. Track **probe score vs live verified-pass rate** on the same chart. Probe
rising while live flat = the loop is fitting the probe; that divergence is the alarm, and
`/rsi status` must show both.

---

## 5. Expectation setting — the uncomfortable research finding

The mission as originally stated — an agent that understands the estate and autonomously keeps
everything running — **is not a solved problem at any lab.** IBM's ITBench: frontier agents
resolve **13.8% of SRE scenarios, 25.2% of CISO, 0% of FinOps**; the 2026 ITBench-AA leaderboard
tops out at **47%** (Claude Opus 4.7), with no memory component tested. Microsoft's FSE'24
incident agent reports a *negative* result: adding incident-discussion context "surprisingly does
not yield significant performance improvements." Every headline vendor claim (Datadog 90% faster
RCA, Traversal 85% MTTR, NeuBird $1.8M) is unpublished with no methodology. There is **no
peer-reviewed evidence that any ops agent measurably improves from its own past incidents.**

Where ops-adjacent loops *do* work, the gate is always machine-checkable and the task band is
narrow: Meta TestGen-LLM (**73% of recommendations shipped**), Meta ACH (gate = "this test
provably kills this mutant"), Google's migration agent (**74.45% of changes LLM-generated,
~50% time reduction**). The closest published analogue to this estate is SkillForge (cloud tech
support, 1,883 tickets), whose signal is consistency with **expert-authored** historical
responses — external ground truth the agent did not write.

**Therefore: narrow the mission.** Not "keep everything running." Instead: *resolve recurring,
machine-verifiable failures, and learn a deterministic procedure for each.* That is the band
where the evidence says this works.

**Correction, 2026-08-06 — this section previously claimed "the narrow band produced 61 real
fixes" and cited the auto-fixer as local proof that it already works here. That claim is false
and is retracted.** Measured against `logs/auto-fixer.jsonl` (168 rows, 08-02 → 08-06): the 61
is `config_push` x59 + `coordinator_restart` x1 + `cron_restart` x1 — three problem classes, not
61 fixes, and 59 of them are the *same* problem re-fired daily for four days and never cured.
`auto_fixer.py:92-108` `fix_config_push` runs `git pull; git push`, **discards both
`subprocess.run` results without reading `.returncode`**, and returns `{"action": "restarted"}`
unconditionally; `auto_fix_all:208` files that under `results["fixed"]`. `verify_fix`
(`auto_fixer.py:112`) has branches for `"cron"` and `"coordinator"` only, so a config_push "fix"
falls through to `{"verified": False, "evidence": "unknown problem type"}` — it has never been
verifiable. This is Defect 3 (§1) inside the very band this section held up as the exception.

What survives: the *strategy* is unrefuted — ITBench measures generality on unfamiliar estates,
which is not this problem; Meta ACH and Google's migration agent are the narrow-band shape and
they ship. What does not survive is the belief that this estate has already demonstrated it.
It has two genuine one-off recoveries and a retry loop papering over a broken git push.
**Therefore Layer 1's day-7 kill gate is the experiment, not a formality.**
Generality is what produced 279 fabricated closes; the narrow band produced 2 verified recoveries.

Anthropic's own RSI result is the right shape and worth internalising: the loop works when
**"the goal and the success metrics [are] fixed in advance"** by a human (≈3× → ≈52× speedup
across model generations), with the explicit caveat that "humans still chose the problem and
created the scoring rubric." Founder-set objectives are not a limitation to engineer around.
They are the design.

---

## 6. Cost, capacity, and the kill gate

- **Capacity blocks Layer 1.** The executor fails with `Individual quota reached… resets in
  44h47m36s` while prospector burns **$500.19/day** subscription-equivalent on the same account.
  Either hermes gets its own metered key with a hard cap, or the coordinator drops from
  every-60s-with-6-in-flight to a handful of real tasks/day. At ~5–10 genuine tasks/day it is
  wildly over-provisioned today.
- **RSI is not cheap if run naively.** DGM ≈ **$22,000** for one two-week run; a GEPA/MIPROv2
  run is "hundreds of dollars." The sample-efficiency lever worth copying is ShinkaEvolve's
  (novelty rejection sampling + weighted parent sampling + bandit model selection: SOTA circle
  packing in **150 samples** vs thousands). The staged cascade in Layer 2 is the cost control.
- **Kill gate, day 7 after Layer 1:** verified passes on real tasks > 0 and rising. If it is
  ~0, the executor genuinely cannot do this work, learned for ~1 day of spend rather than
  another six weeks.

---

## 7. Provenance caveat

Roughly half the cited 2026 results (GRASP, Ratchet, RSEA, Regimes, SpecBench, ITBench-AA) are
low-citation arXiv preprints whose ablations are load-bearing for the recommendations above.
They were verified by fetching the abstract/HTML; none were independently reproduced. The legs
of the argument that survive if those evaporate are the older and more robust ones: intrinsic
self-correction degrades (GPT-4 GSM8K 95.5 → 91.5 → 89.0), self-verification produces 38 false
positives per 100 in Blocksworld while a sound external verifier takes 40% → 88%, Self-Refine
says "looks good" on 94% of incorrect math, model collapse under synthetic-replaces-real,
Goodhart's measured shape, FunSearch, AlphaEvolve, and DGM's reward-hacking incident.
