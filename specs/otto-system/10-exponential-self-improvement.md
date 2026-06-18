# Build Note 10 — Exponential Self-Improvement Architecture

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

> **⚠️ WARNING:** This spec extends an intentionally *convergent* architecture into an *exponential* one. The safety mechanisms in Section 6 are non-negotiable. Any deployment that removes the off-switch, rollback, or audit trail is a deployment of an uncontrolled system. Do not do that.

---

## 1. What "Exponential" Actually Means Here

Exponential self-improvement does **not** mean unbounded growth of the policy store, infinite compute consumption, or runaway recursion. It means:

**Compounding improvement velocity.** Each improvement makes the *next* improvement faster, cheaper, or more effective — producing a compound curve on the metric of *improvement throughput per unit human attention*, not on policy count or compute spend.

### The compounding stack

```
Layer 3: Meta-improvement  ── optimizes the improvement pipeline itself
Layer 2: Gap-finding       ── surfaces what's missing + proposes fixes
Layer 1: Consolidation     ── sharpens existing policies
Layer 0: Correction loop   ── adds policies from user corrections
```

Each layer operates on the layer below. **The meta-improver (Layer 3) is the exponential lever** — it improves the improvement pipeline itself. But critically, the meta-improver also tracks whether its own improvements actually *worked* — creating a second-order feedback loop.

### What compounds

| Dimension | Before (convergent) | After (exponential) |
|-----------|--------------------|--------------------|
| Policy coverage | +1 per correction | +1 per correction + auto-generated gap patches |
| Regression coverage | Manual corpus harvest | Auto-harvest + auto-test generated fix candidates |
| Duplicate detection | Word-overlap only | Semantic similarity + rule-space dedup |
| Fix generation | Human writes the rule | System proposes fix candidates for human signoff |
| Meta-pipeline | Static | Self-tuning thresholds, order, and frequency |
| **Improvement velocity** | **Not tracked** | **Measured and optimized — the actual compound metric** |
| **Previous-change validation** | **None** | **Tracks if past meta-changes actually improved throughput** |

### The exponential mechanism — what makes it actually compound

The standard approach says: "detect bottlenecks, tune thresholds, repeat." That's linear iteration, not compounding.

**The real compound mechanism** is a two-loop system:

```
Loop 1 (inner):  Pipeline optimization
  1. Measure pipeline throughput (policies-per-correction, coverage gain per cycle)
  2. Identify bottleneck phase
  3. Tune threshold or reorder
  4. Measure again next cycle
  5. If throughput increased → reinforce that tuning direction
  6. If throughput decreased → revert and try opposite direction

Loop 2 (outer):  Meta-pattern discovery
  1. Collect all historical (change_type, before_metric, after_metric) tuples
  2. Cluster: which types of changes consistently improve throughput?
  3. Prioritize future candidates toward proven-successful change types
  4. Suppress future candidates toward change types that never help
```

The outer loop is what makes it exponential: over time, the system **learns which kinds of improvements actually work** and biases toward them. This is not rewriting evaluation criteria — it's learning a *search heuristic* over change types, which is safe (the set of change types is fixed and bounded).

### Hard bounds (non-negotiable)

- Policy store size: **max 200 active policies** (enforced by meta-improver)
- Each improvement cycle: **max 2 min runtime**, **max 1 strategist call**
- Meta-improver: **never modifies external systems, never deploys code, never accesses credentials**
- Human override: **always wins**, no automatic override of explicit human direction
- **Change types are fixed**: the meta-improver cannot invent new change types. Only the 5 types in Section 5.

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│              HUMAN OPERATOR (Chidi)                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Corrections  │  │ Signoff Gate │  │ Off-Switch     │ │
│  │ (triggers    │  │ (approves     │  │ (stops ALL     │ │
│  │  learning)   │  │  meta-changes)│  │  auto-learning)│ │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘ │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌──────────────────────────────────────────────────────────────┐
│                    IDLE LEARNING PIPELINE                      │
│  Every 2h (pre-emptible, 2-min max)                          │
│                                                              │
│  Phase 0: PREFLIGHT                                          │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Check off-switch + script integrity hash              ││
│  │ 2. Snapshot ALL policies + config + metrics              ││
│  │ 3. Log run start to audit                                ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 1: META-IMPROVEMENT (core exponential lever)          │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ INNER LOOP (pipeline optimization):                      ││
│  │ 1. Load last N cycles of pipeline metrics                ││
│  │ 2. Compute improvement velocity metric                   ││
│  │ 3. Validate previous meta-changes: did they improve?     ││
│  │    - If yes → reinforce direction                        ││
│  │    - If no → revert + suppress similar candidates        ││
│  │ 4. Detect current bottleneck                             ││
│  │ 5. Generate candidate change(s) for this bottleneck      ││
│  │                                                          ││
│  │ OUTER LOOP (meta-pattern discovery):                     ││
│  │ 6. Load historical (change, outcome) table               ││
│  │ 7. Cluster change types by success rate                  ││
│  │ 8. Prioritize high-success-rate change types             ││
│  │ 9. Suppress low-success-rate change types                ││
│  │                                                          ││
│  │ 10. Validate candidates against safety constraints       ││
│  │ 11. Write to pending-changes.json                        ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 2: GAP-FINDING + FIX CANDIDATES                      │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Scan failure corpus for uncovered domains             ││
│  │ 2. Generate fix CANDIDATES (not auto-apply)              ││
│  │ 3. Rank by failure frequency + severity                  ││
│  │ 4. Write to gap report with fix proposals                ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 3: SELF-REGRESSION                                   │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Harvest new failures from logs + reflections          ││
│  │ 2. Run full regression suite                             ││
│  │ 3. Test auto-generated fix candidates against corpus     ││
│  │ 4. Coverage % report with trend                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 4: CONSOLIDATION                                     │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Semantic duplicate detection (beyond word overlap)    ││
│  │ 2. Auto-merge candidates with HIGH confidence only       ││
│  │ 3. Contradiction detection                               ││
│  │ 4. Stale policy retirement                               ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 5: POSTFLIGHT                                         │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Snapshot all state after changes                      ││
│  │ 2. Compute diff from preflight                           ││
│  │ 3. Compute improvement velocity:                         ││
│  │    velocity = (coverage_gain + candidates_generated      ││
│  │               - policy_churn) / cycle_duration           ││
│  │ 4. Update metrics + mark any applied changes as          ││
│  │    "improved" or "did_not_improve" in outcome table      ││
│  │ 5. Write audit record                                    ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────┐
│                    DATA STORES                                │
│                                                              │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ ~/.hermes/     │  │ ~/.hermes/logs/  │  │ ~/.hermes/   │  │
│  │ policies/      │  │ meta-improver/   │  │ meta/        │  │
│  │ (policy JSONs) │  │ (audit trail)    │  │ (pipeline    │  │
│  └────────────────┘  └──────────────────┘  │ config +     │  │
│                                             │ metrics)    │  │
│  ┌────────────────┐  ┌──────────────────┐  └──────────────┘  │
│  │ ~/.hermes/     │  │ ~/.hermes/logs/  │                   │
│  │ policies/      │  │ self-regression- │                   │
│  │ archived/      │  │ corpus.json      │                   │
│  └────────────────┘  └──────────────────┘                   │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ ~/.hermes/meta/change-outcomes.jsonl                     ││
│  │ ← NEW: time-series of (change_id, before, after,        ││
│  │   improved_flag) for the outer loop                      ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## 3. File Map

### New files

| File | Purpose | Layer |
|------|---------|-------|
| `~/.hermes/scripts/meta-improver.py` | Core meta-improvement loop — optimizes the improvement pipeline itself | L3 |
| `~/.hermes/meta/pipeline-config.json` | Configurable thresholds for the improvement pipeline | L3 |
| `~/.hermes/meta/metrics.jsonl` | Time-series metrics for pipeline performance | L3 |
| `~/.hermes/meta/change-outcomes.jsonl` | **NEW** — Time-series of every applied change + whether it improved throughput | L3 |
| `~/.hermes/meta/reference-script-hash.json` | **NEW** — SHA-256 of meta-improver.py at last known-good state. Used for circular-self-reference detection. Stored *outside* the script itself. | L3 |
| `~/.hermes/logs/meta-improver/YYYY-MM-DD-HHMMSS_<change-id>.json` | Per-change audit trail with before/after snapshots | L3 |
| `~/.hermes/scripts/meta-audit-report.py` | Human-readable audit report of all meta-improvements | L3 |

### Modified files

| File | Change | Layer |
|------|--------|-------|
| `~/.hermes/scripts/idle-learning-run.sh` | Add Phase 0 (preflight), Phase 1 (meta), Phase 5 (postflight) | L3 |
| `~/.hermes/scripts/idle-consolidation.py` | Add `--apply` mode for auto-merge at confidence >= 0.9 | L2 |
| `~/.hermes/scripts/self-regression.py` | Generate coverage trends, accept automated test candidates | L2 |
| `~/.hermes/scripts/gap-finding.py` | Generate fix candidates (not just gap descriptions) | L2 |
| `~/.hermes/specs/otto-system/00-MASTER.md` | Section 2: this is now a **compound** improvement system (exponential layers) | L0 |

---

## 4. Data Flow — The Meta-Improvement Loop

### Normal flow (every 2h idle cycle)

```
1. PREFLIGHT
   meta-improver.py --preflight
   ├── Check OFF_SWITCH file exists ===> if missing, abort all learning
   ├── Check script integrity hash against ~/.hermes/meta/reference-script-hash.json
   │   └── If mismatch → abort. Requires human to verify and update reference hash.
   ├── Snapshot ALL policies to meta/snapshots/preflight-<timestamp>.json
   ├── Snapshot all configurable thresholds
   └── Log to meta/metrics.jsonl (timestamp, policy_count, coverage_pct, etc.)

2. META-IMPROVEMENT — Core exponential lever
   meta-improver.py --analyze
   ├── INNER LOOP: Pipeline optimization
   │   ├── Load last N cycles of metrics (default: 10)
   │   ├── Compute improvement velocity: delta_coverage / cycles_elapsed
   │   ├── Validate previous meta-changes against change-outcomes.jsonl
   │   │   ├── If last change improved velocity → reinforce direction
   │   │   ├── If last change degraded velocity → generate reversion candidate
   │   │   └── Update change-outcomes.jsonl with outcome
   │   ├── Detect current bottleneck:
   │   │   ├── Which phase has the worst latency trend?
   │   │   ├── Which phase generates least useful output?
   │   │   └── Is coverage converging (no gain in 3+ cycles)?
   │   └── Generate candidate change for the worst bottleneck
   │
   ├── OUTER LOOP: Meta-pattern discovery
   │   ├── Load change-outcomes.jsonl (all historical changes)
   │   ├── For each change_type: compute success_rate and avg_velocity_delta
   │   ├── Cluster change_types by performance:
   │   │   ├── HIGH_YIELD: success_rate >= 0.5 — prioritize these
   │   │   ├── LOW_YIELD: success_rate < 0.2 — deprioritize
   │   │   └── UNKNOWN: insufficient data — neutral
   │   └── Apply weight to candidate generation: favor HIGH_YIELD types
   │
   ├── Validate each candidate against SAFETY RULES (Section 6)
   ├── Write candidates to meta/pending-changes.json
   └── Surface to user

3. GAP-FINDING + FIX CANDIDATES
   gap-finding.py --report --generate-candidates
   ├── Existing gap analysis (unchanged from 06-gap-finding.md)
   ├── NEW: For each uncovered domain, generate a candidate policy
   └── Write to meta/fix-candidates.json

4. SELF-REGRESSION
   self-regression.py --report --test-candidates
   ├── Existing regression (unchanged from 05-self-regression.md)
   ├── NEW: Test each fix candidate against the failure corpus
   └── Score candidates: {precision, recall, coverage_gain}

5. CONSOLIDATION
   idle-consolidation.py
   ├── Existing duplicate/contradiction analysis (unchanged)
   └── Auto-merge ONLY if confidence >= 0.9 AND both policies have
       been active for >= 7 days AND no human ever manually created either

6. POSTFLIGHT
   meta-improver.py --postflight
   ├── Snapshot all state again
   ├── Compute diff from preflight
   ├── Compute improvement velocity metrics
   ├── Evaluate pending changes: if any were applied this cycle,
   │   create initial entry in change-outcomes.jsonl with baseline velocity
   │   (outcome will be determined next cycle when velocity delta is measurable)
   ├── Update metrics.jsonl
   └── Write audit record
```

### Human approval flow (async)

```
1. meta-improver.py --analyze produces candidates
2. Daily briefing surfaces "Pending pipeline improvements"
3. User runs: meta-improver.py --review (shows all pending candidates)
4. For each candidate:
   ├── User says "approve <id>" → meta-improver.py --approve <id>
   │   └── Apply the change, log it, create outcome record
   └── User says "reject <id>" → meta-improver.py --reject <id>
       └── Log rejection, never re-propose the same candidate
5. Approval-required changes always need human review.
   Approval-optional changes auto-apply after 3 idle cycles (6 hours).
```

### Outcome evaluation flow (critical — this is what makes it exponential)

```
After a change is applied:
Cycle N:     Change applied. Baseline velocity recorded.
Cycle N+1:   compare velocity with baseline.
             If velocity increased → mark change as "improved" in change-outcomes.jsonl
             If velocity decreased → mark as "degraded"
             If velocity unchanged → mark as "neutral"
Cycle N+2+:  Re-check (some improvements take multiple cycles to show)

The outer loop reads change-outcomes.jsonl and learns which change types work.
```

---

## 5. Meta-Improver — What It Can and Cannot Do

### Change types (fixed, bounded set — the meta-improver cannot invent new ones)

| Change Type | Category | Description | Auto-apply? |
|------------|----------|-------------|-------------|
| `threshold_tuning` | Numeric | Adjust demote_ratio, similarity_threshold, promote_min_hits within bounds | After 3 cycles |
| `pipeline_reorder` | Structural | Change phase execution order (respecting DAG) | After 3 cycles |
| `policy_merge` | Policy action | Merge near-duplicate policies | After 3 cycles |
| `retire_stale` | Policy action | Archive zero-hit policies | After 3 cycles |
| `add_pipeline_phase` | Structural | Add a new phase (script reference only) | Always requires approval |

### CAN do (automated)

1. **Measure pipeline performance** — collect latency, yield, quality metrics on every phase
2. **Compute improvement velocity** — the actual compound metric
3. **Validate previous changes** — check if applied changes improved velocity
4. **Learn which change types work** — outer loop meta-pattern discovery over change-outcomes.jsonl
5. **Detect bottlenecks** — flag phases that consistently underperform
6. **Tune numeric thresholds** — within bounded ranges defined in safety rules
7. **Re-order pipeline phases** — respecting DAG dependency constraints
8. **Generate fix candidates** — propose new policies for uncovered failure domains (NEVER auto-applies)
9. **Auto-retire stale policies** — policies with zero hits for 30+ days get archived (reversible)
10. **Log everything** — every measurement, every candidate, every decision

### CANNOT do (requires human approval gate or structurally prevented)

1. **Modify its own evaluation criteria** — the change types are hardcoded. The outer loop learns *which change types to prefer*, not *what counts as an improvement*.
2. **Modify its own safety rules** — SAFETY_RULES is a module-level constant. The script reads it but never writes to it.
3. **Modify itself** — script integrity hash is stored EXTERNALLY. The script cannot update the reference hash; only a human can.
4. **Apply fix candidates automatically** — every generate-fix output needs human signoff
5. **Modify scripts outside meta/ and scripts/ directory** — no touching policy-enforcer.py, dispatch_gate.py, daily_reflection.py, or any Hermes core
6. **Access external systems** — no web requests, no API calls, no git push
7. **Spend money** — no compute resource allocation beyond what exists
8. **Deploy code** — no modification of project repos (Signal Engine, LUX, Prospector)
9. **Remove the off-switch** — the off-switch is checked at every cycle start
10. **Modify human audit trail** — audit logs are append-only and immutable
11. **Invent new change types** — only the 5 types above. No code generation.
12. **Remove the DAG constraint** — pipeline_reorder cannot create cycles or run phases with unsatisfied dependencies

### CAN do (but bounded)

1. **Re-order pipeline phases** — only within provided sequences; preflight must be first, postflight last; meta_improvement must come before gap_finding if fix_candidates are expected
2. **Tune thresholds** — only within pre-defined ranges
3. **Merge policies** — only when confidence >= 0.9 and both policies are >= 7 days old
4. **Propose new gap-detection patterns** — only from the existing domain taxonomy

---

## 6. Safety Mechanisms (Non-Negotiable)

### 6.1 Off-Switch

```
~/.hermes/meta/OFF_SWITCH
```

A file that, if present, **enables** all meta-improvement. If deleted, ALL automatic improvement stops:
- Idle learning skips all phases (including existing consolidation/regression/gap-finding)
- Correction learning loop still works (user corrections always accepted)
- The meta-improver will NOT re-create the off-switch file

Check performed: at the START of every run, before any action. If the file is missing, the script prints "⛔ OFF_SWITCH absent — aborting all automatic learning" and exits with code 0.

To re-enable: `touch ~/.hermes/meta/OFF_SWITCH`

### 6.2 Script Integrity — Circular Self-Reference Protection

The script hash mechanism prevents the meta-improver from modifying itself. This is structurally sound because:

1. **External reference hash**: The SHA-256 of `meta-improver.py` is stored in `~/.hermes/meta/reference-script-hash.json`. This is a separate file that the script never writes to.
2. **Checked at preflight**: The script computes its own hash and compares against the reference. Mismatch → abort.
3. **Human-only update**: The reference hash file is only updated by explicit human action (or by a bootstrap script that requires human confirmation).
4. **No self-modification**: The script never writes to its own source file. The change types are module-level constants.

```
Reference hash file format:
{
  "script_path": "~/.hermes/scripts/meta-improver.py",
  "sha256": "abcdef123456...",
  "recorded_at": "2026-06-18T14:00:00Z",
  "recorded_by": "human_bootstrap"
}
```

### 6.3 Rollback Mechanism

Every change is structured as a **reversible transaction**:

```
logs/meta-improver/2026-06-18-140000_improver-001.json
{
  "change_id": "improver-001",
  "applied_at": "2026-06-18T14:00:00Z",
  "change_type": "threshold_tuning",
  "description": "Lowered promote_min_hits from 3 to 2",
  "preflight_snapshot": "snapshot-preflight-20260618-135500.json",
  "postflight_snapshot": "snapshot-postflight-20260618-140100.json",
  "before_state": { ... },
  "after_state": { ... },
  "rollback_command": "meta-improver.py --rollback improver-001",
  "rollback_valid_until": "2026-07-18T14:00:00Z",
  "human_approved": false,
  "reversible": true
}
```

Rollback restores the `before_state` exactly from the preflight snapshot. Rollbacks are valid until 30 days after the change.

### 6.4 Audit Trail

```
logs/meta-improver/ — directory with one JSON file per change
logs/meta-improver/audit-index.jsonl — chronological index of ALL changes
meta/metrics.jsonl — time-series pipeline performance data
meta/change-outcomes.jsonl — time-series of each change's effectiveness
meta/pending-changes.json — current candidates awaiting human review
meta/rejected-changes.jsonl — never re-propose these
```

Every audit entry includes:
- Full before/after state (policies, config, metrics)
- The exact command that would reverse the change
- Whether human approved
- Timestamp + context at time of change
- Outcome tracking ID (linked to change-outcomes.jsonl)

### 6.5 Human Approval Gate

The gate is implemented programmatically in `meta-improver.py`:

```python
APPROVAL_REQUIRED_CHANGES = [
    "add_pipeline_phase",      # Adding a new phase — structural change
]

APPROVAL_OPTIONAL_CHANGES = [
    "threshold_tuning",        # Numeric threshold adjustment
    "pipeline_reorder",        # Phase execution order
    "policy_merge",            # Merging near-duplicate policies
    "retire_stale",            # Archiving zero-hit policies
]
```

**Approval-required** changes go into `meta/pending-changes.json` and stay there until human runs `meta-improver.py --approve <id>`. They are surfaced in the daily briefing.

**Approval-optional** changes auto-apply after 3 idle cycles (6 hours) of remaining pending.

### 6.6 Observability

- Every cycle writes a structured report to `logs/meta-improver/YYYY-MM-DD.md`
- The `meta-improver.py --status` command shows current pipeline health + improvement velocity trend
- The `meta-improver.py --history` command shows last 30 days of changes
- The `meta-improver.py --outcomes` command shows which change types are working
- The daily briefing (9am) shows a "Meta-Improver" section with pending changes

---

## 7. Concrete Metrics

### What gets measured

```python
pipeline_metrics = {
    "cycle_duration_seconds": <float>,
    "phase_timing_ms": {
        "consolidation": <int>,
        "regression": <int>,
        "gap_finding": <int>,
        "meta_improvement": <int>
    },
    "policy_count": <int>,
    "coverage_pct": <float>,
    "gap_count": <int>,
    "corrections_this_cycle": <int>,
    "proposed_fixes": <int>,
    "pending_approvals": <int>,
    "improvement_velocity": <float>,  # NEW: delta coverage / cycles elapsed
    "meta_changes_applied": <int>,
    "off_switch_status": <bool>
}
```

### Change outcome tracking

```python
change_outcome = {
    "change_id": "improver-001",
    "change_type": "threshold_tuning",
    "applied_at": "2026-06-18T14:00:00Z",
    "velocity_before": 3.2,       # improvement_velocity at time of application
    "velocity_after_N1": None,     # velocity after 1 cycle — filled at next postflight
    "velocity_after_N3": None,     # velocity after 3 cycles — more stable signal
    "outcome": "pending",          # "improved" | "degraded" | "neutral" | "pending"
    "outcome_determined_at": None,
}
```

### Success criteria

| Metric | Initial | Target (30 days) | Target (90 days) |
|--------|---------|-------------------|-------------------|
| Coverage % | ~40% | 70% | 90%+ |
| Corrections-to-policy latency | 30s | 10s | 5s |
| Duplicate policies | 2-3 per 10 | <1 per 20 | <1 per 50 |
| Fix candidate acceptance rate | 0% (new) | 40% | 60%+ |
| Pipeline throughput (policies/correction) | 1:1 | 2:1 | 3:1 |
| Meta-improvements human-approved | 0 | 3 | 10+ |
| **Improvement velocity** | **0 (not tracked)** | **Positive** | **Compounding >5%/cycle** |
| **HIGH_YIELD change type accuracy** | **0 (no data)** | **60%+** | **80%+ (outer loop learned)** |

---

## 8. Implementation Plan

### Phase 1 — Scaffold (Day 1)
1. Create `~/.hermes/meta/` directory with config template + reference-script-hash.json
2. Write `meta-improver.py` with safety checks, preflight/postflight, audit logging
3. Create off-switch file
4. Wire `idle-learning-run.sh` to call meta phases
5. Test: run `meta-improver.py --preflight --postflight` with no changes to verify logging

### Phase 2 — Measure (Day 2-3)
1. Collect baseline metrics for 3-4 idle cycles
2. Fix any metric collection gaps
3. Write `meta-audit-report.py` for human-readable output
4. **Crucially**: establish baseline improvement_velocity (even if zero)

### Phase 3 — Inner Loop (Day 4-5)
1. Implement bottleneck detection
2. Implement previous-change validation (check change-outcomes.jsonl)
3. Generate threshold-tuning + pipeline-reorder candidates
4. Wire into daily briefing

### Phase 4 — Outer Loop (Day 6-7)
1. Implement change-outcomes.jsonl tracking
2. Implement change_type clustering (HIGH_YIELD / LOW_YIELD / UNKNOWN)
3. Implement priority weighting based on historical success
4. Auto-apply approval-optional changes with convergence check

### Phase 5 — Convergence (Day 8+)
1. Implement diminishing-returns detection (stop proposing when velocity improvement < 1% per cycle)
2. Implement auto-reversion for changes that clearly degraded velocity
3. Monitor with real corrections over several days

---

## 9. Relationship to Existing Architecture

| Existing | Relationship |
|----------|-------------|
| `00-MASTER.md` Section 2 | Extended: L3 now has exponential layers instead of convergent only |
| `01-correction-learning-loop.md` | Unchanged — still core; meta-improver accelerates it |
| `04-idle-consolidation.md` | Unchanged core; meta-improver tunes its thresholds |
| `05-self-regression.md` | Unchanged core; meta-improver consumes its coverage % metric |
| `06-gap-finding.md` | Unchanged core; meta-improver evaluates its yield |
| `09-idle-continuous-learning.md` | Superseded by this spec |
| `policy-enforcer-redesign.md` | Independent — meta-improver doesn't touch enforcement |

### Dependency DAG for pipeline phases

```
preflight (no deps)
  → meta_improvement (needs: preflight snapshot)
  → gap_finding (needs: meta candidates for reference; can run independently)
  → self_regression (needs: gap candidates for testing; can run independently)
  → consolidation (needs: nothing; can run independently)
  → postflight (needs: all prior phases)

Valid reorderings: any topological ordering of [gap_finding, self_regression, consolidation]
must keep preflight first and postflight last.
meta_improvement must run before gap_finding if --generate-candidates mode is on.
```

---

## 10. Failure Modes and Recovery

| Failure Mode | Detection | Recovery |
|-------------|-----------|----------|
| Meta-improver introduces bad threshold | Metrics degrade | `--rollback <id>` restores last good config |
| Outer loop converges on wrong change type | HIGH_YIELD accuracy is negative | Human can reset `change-outcomes.jsonl` |
| Off-switch file accidentally deleted | Otto stops improving | `touch OFF_SWITCH` to re-enable |
| Script hash mismatch (legitimate update) | Preflight fails | Human must update reference-script-hash.json |
| Script hash mismatch (malicious modification) | Preflight fails | Investigate + restore from git backup |
| Pipeline phase hangs | Runtime exceeds 2-min cap | Idle-learning-run.sh kills the phase; next cycle skips it |
| Coverage converging to plateau | Improvement velocity → 0 | Outer loop stops proposing changes; manual review needed |
| Fix candidate generation is low quality | Acceptance rate stays at 0% | Tune generation prompt; or disable fix-candidate phase |
| Change outcome never determined | Too few cycles elapsed | Automatic: wait for N+3 cycles before marking outcome |
