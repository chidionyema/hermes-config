# Build Note 10 — Exponential Self-Improvement Architecture

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

> **⚠️ WARNING:** This spec extends an intentionally *convergent* architecture into an *exponential* one. The safety mechanisms in Section 6 are non-negotiable. Any deployment that removes the off-switch, rollback, or audit trail is a deployment of an uncontrolled system. Do not do that.

---

## 1. What "Exponential" Actually Means Here

Exponential self-improvement does **not** mean unbounded growth of the policy store, infinite compute consumption, or runaway recursion. It means:

**Compounding improvement velocity.** Each improvement makes the *next* improvement faster, cheaper, or more effective — producing a compound curve on the metric of *improvement throughput per unit human attention*, not on policy count or compute spend.

Concrete metric: **policies-per-correction** increases over time. Otto's first correction required a manual policy-add. With the meta-improver, Otto can auto-detect, auto-test, auto-merge, and auto-generate fixes — converting the same human correction into 3× the policy coverage in 1/3 the time.

### The compounding stack

```
Layer 3: Meta-improvement  ── can optimize layers 0-2
Layer 2: Gap-finding       ── surfaces what's missing
Layer 1: Consolidation     ── sharpens existing policies
Layer 0: Correction loop   ── adds policies from user corrections
```

Each layer operates on the layer below. **The meta-improver (Layer 3) is the exponential lever** — it improves the improvement pipeline itself, creating compounding returns.

### What compounds

| Dimension | Before (convergent) | After (exponential) |
|-----------|--------------------|--------------------|
| Policy coverage | +1 per correction | +1 per correction + auto-generated gap patches |
| Regression coverage | Manual corpus harvest | Auto-harvest + auto-test generated fix candidates |
| Duplicate detection | Word-overlap only | Semantic similarity + rule-space dedup |
| Fix generation | Human writes the rule | System proposes fix candidates for human signoff |
| Meta-pipeline | Static | Self-tuning thresholds, order, and frequency |

### Hard bounds (non-negotiable)

- Policy store size: **max 200 active policies** (enforced by meta-improver)
- Each improvement cycle: **max 2 min runtime**, **max 1 strategist call**
- Meta-improver: **never modifies external systems, never deploys code, never accesses credentials**
- Human override: **always wins**, no automatic override of explicit human direction

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
│  ┌──────────────┐    ┌────────────────┐    ┌──────────────┐ │
│  │ Check off-   │───▶│ Snapshot all   │───▶│ Log run start│ │
│  │ switch status│    │ policies + logs│    │ to audit     │ │
│  └──────────────┘    └────────────────┘    └──────────────┘ │
│                                                              │
│  Phase 1: META-IMPROVEMENT (NEW - see Section 5)             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Load all pipeline metrics (latency, yield, quality)   ││
│  │ 2. Identify bottlenecks in the improvement pipeline       ││
│  │ 3. Generate candidate improvements (thresholds, order,   ││
│  │    new gap-detectors, fix-generators)                    ││
│  │ 4. Evaluate candidate against safety constraints         ││
│  │ 5. Queue for human signoff                               ││
│  │ 6. If approved: apply. If not: log + skip.               ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 2: GAP-FINDING (enhanced from existing)               │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Scan failure corpus for uncovered domains             ││
│  │ 2. Generate fix CANDIDATES (not auto-apply)              ││
│  │ 3. Rank by failure frequency + severity                  ││
│  │ 4. Write to gap report with fix proposals                ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 3: SELF-REGRESSION (enhanced)                        │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Harvest new failures from logs + reflections          ││
│  │ 2. Run full regression suite                             ││
│  │ 3. Test auto-generated fix candidates against corpus     ││
│  │ 4. Coverage % report with trend                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 4: CONSOLIDATION (enhanced)                          │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 1. Semantic duplicate detection (beyond word overlap)    ││
│  │ 2. Auto-merge candidates with HIGH confidence            ││
│  │ 3. Contradiction detection                               ││
│  │ 4. Stale policy retirement                               ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Phase 5: POSTFLIGHT                                         │
│  ┌──────────────┐    ┌────────────────┐    ┌──────────────┐ │
│  │ Snapshot all  │───▶│Write audit log │───▶│ Update       │ │
│  │ state after   │    │ with diff from │    │ pipeline     │ │
│  │ changes       │    │ preflight      │    │ metrics      │ │
│  └──────────────┘    └────────────────┘    └──────────────┘ │
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
| `~/.hermes/logs/meta-improver/YYYY-MM-DD-HHMMSS_<change-id>.json` | Per-change audit trail with before/after snapshots | L3 |
| `~/.hermes/scripts/generate-fix-candidates.py` | Generate candidate policy fixes from gap analysis (read-only, no application) | L2 |
| `~/.hermes/scripts/meta-audit-report.py` | Human-readable audit report of all meta-improvements | L3 |
| `~/.hermes/meta/pipeline-config.json.template` | Template/example config | L3 |

### Modified files

| File | Change | Layer |
|------|--------|-------|
| `~/.hermes/scripts/idle-learning-run.sh` | Add Phase 0 (preflight), Phase 1 (meta), Phase 5 (postflight) | L3 |
| `~/.hermes/scripts/idle-consolidation.py` | Add `--apply` mode for auto-merge at confidence >= 0.9 | L2 |
| `~/.hermes/scripts/self-regression.py` | Generate coverage trends, accept automated test candidates | L2 |
| `~/.hermes/scripts/gap-finding.py` | Generate fix candidates (not just gap descriptions) | L2 |
| `~/.hermes/scripts/otto-learn.py` | Add `propose` subcommand that reads gap candidates | L2 |
| `~/.hermes/specs/otto-system/00-MASTER.md` | Section 2: this is now a **compound** improvement system (exponential layers) | L0 |

---

## 4. Data Flow — The Meta-Improvement Loop

### Normal flow (every 2h idle cycle)

```
1. PREFLIGHT
   meta-improver.py --preflight
   ├── Check OFF_SWITCH file exists ===> if missing, abort all learning
   ├── Snapshot ALL policies to meta/snapshots/preflight-<timestamp>.json
   ├── Snapshot all configurable thresholds
   └── Log to meta/metrics.jsonl (timestamp, policy_count, coverage_pct, etc.)

2. META-IMPROVEMENT (core exponential lever)
   meta-improver.py --analyze
   ├── Load last N cycles of metrics (default: 10)
   ├── Detect bottlenecks:
   │   ├── Consolidation latency > threshold? → flag threshold as candidate
   │   ├── Gap generation never leads to action? → flag follow-through
   │   ├── Regression coverage flat for 3+ cycles? → flag detector quality
   │   └── Policy-to-correction ratio dropping? → flag fix quality
   ├── Generate candidate changes:
   │   ├── Threshold tuning (demote ratio, similarity, promote min hits)
   │   ├── Pipeline reordering (which phase runs first)
   │   └── New patterns for gap detection
   ├── Validate each candidate against SAFETY RULES (Section 6)
   ├── Write candidates to meta/pending-changes.json
   └── NOTIFY user: "Suggested pipeline optimization: X"

3. GAP-FINDING + FIX CANDIDATES
   gap-finding.py --report --generate-candidates
   ├── Existing gap analysis
   ├── NEW: For each uncovered domain, generate a candidate policy
   │   Format: {trigger, rule, scope, confidence: "proposed"}
   └── Write to meta/fix-candidates.json

4. SELF-REGRESSION
   self-regression.py --report --test-candidates
   ├── Existing regression
   ├── NEW: Test each fix candidate against the failure corpus
   └── Score candidates: {precision, recall, coverage_gain}

5. CONSOLIDATION (if --apply flag is set — never auto-applies)
   idle-consolidation.py [--apply]
   ├── Existing duplicate/contradict analysis
   └── Auto-merge ONLY if confidence >= 0.9 AND both policies have
       been active for >= 7 days AND no human ever manually created either

6. POSTFLIGHT
   meta-improver.py --postflight
   ├── Snapshot all state again
   ├── Compute diff from preflight
   ├── Write audit record to logs/meta-improver/
   ├── Update metrics
   └── Clear pending-change flags
```

### Human approval flow (async)

```
1. meta-improver.py --analyze produces candidates
2. Weekly context: user sees "Pending pipeline improvements" in daily briefing
3. User runs: meta-improver.py --review (shows all pending candidates)
4. For each candidate:
   ├── User says "approve <id>" → meta-improver.py --approve <id>
   │   └── Apply the change, log it, update snapshot
   └── User says "reject <id>" → meta-improver.py --reject <id>
       └── Log rejection, never re-propose the same candidate
5. Critical path changes (e.g., new gap-detection scripts) always require
   human review. Non-critical (threshold tuning) may auto-apply after 3 idle cycles.
```

---

## 5. Meta-Improver — What It Can and Cannot Do

### CAN do (automated, no human needed)

1. **Measure pipeline performance** — collect latency, yield, quality metrics on every phase
2. **Detect bottlenecks** — flag phases that consistently underperform
3. **Tune numeric thresholds** — adjust demote ratio, Jaccard threshold, promote min-hits within bounded ranges
4. **Re-order pipeline phases** — change the execution order of consolidation/regression/gap-finding based on which is most bottlenecked
5. **Generate fix candidates** — propose new policies for uncovered failure domains (NEVER auto-applies)
6. **Auto-retire stale policies** — policies with zero hits for 30+ days get archived (reversible)
7. **Log everything** — every measurement, every candidate, every decision

### CANNOT do (requires human approval gate)

1. **Modify its own evaluation criteria** — the safety rules in Section 6 are hardcoded in the meta-improver scaffold. The script cannot rewrite itself.
2. **Apply fix candidates automatically** — every `generate-fix` output must pass through human signoff before becoming a real policy
3. **Modify scripts outside `meta/` and `scripts/` directory** — no touching `policy-enforcer.py`, `dispatch_gate.py`, `daily_reflection.py`, or any Hermes core
4. **Access external systems** — no web requests, no API calls, no git push
5. **Spend money** — no compute resource allocation beyond what exists
6. **Deploy code** — no modification of project repos (Signal Engine, LUX, Prospector)
7. **Remove the off-switch** — the off-switch is checked at every cycle start
8. **Modify human audit trail** — audit logs are append-only and immutable

### CAN do (but bounded)

1. **Re-order pipeline phases** — only within provided sequences; cannot add new phases
2. **Tune thresholds** — only within pre-defined ranges (no setting demote_ratio to 0.0)
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

Check performed: at the START of every run, before any action. If the file is missing, the script prints "OFF_SWITCH absent — aborting all automatic learning" and exits with code 0.

To re-enable: `touch ~/.hermes/meta/OFF_SWITCH`

### 6.2 Rollback Mechanism

Every change is structured as a **reversible transaction**:

```
logs/meta-improver/2026-06-18-140000_improver-001.json
{
  "change_id": "improver-001",
  "applied_at": "2026-06-18T14:00:00Z",
  "change_type": "threshold_tuning" | "pipeline_reorder" | "policy_merge" | "candidate_proposal",
  "description": "Merged pol-001 and pol-005 (confidence 0.92, overlap 0.71)",
  "preflight_snapshot": "snapshot-20260618-135500.json",
  "postflight_snapshot": "snapshot-20260618-140100.json",
  "before_state": { ... },
  "after_state": { ... },
  "rollback_command": "meta-improver.py --rollback improver-001",
  "rollback_valid_until": "2026-07-18T14:00:00Z",
  "human_approved": false,  // true only if explicitly approved
  "reversible": true
}
```

Rollback restores the `before_state` exactly. Rollbacks are valid until 30 days after the change.

### 6.3 Audit Trail

```
logs/meta-improver/ — directory with one JSON file per change
logs/meta-improver/audit-index.jsonl — chronological index of ALL changes
meta/metrics.jsonl — time-series pipeline performance data
meta/pending-changes.json — current candidates awaiting human review
```

Every audit entry includes:
- Full before/after state (policies, config, metrics)
- The exact command that would reverse the change
- Whether human approved
- Timestamp + context at time of change

### 6.4 Human Approval Gate

The gate is implemented programmatically in `meta-improver.py`:

```python
APPROVAL_REQUIRED_CHANGES = [
    "add_pipeline_phase",      # Adding a new phase
    "modify_evaluation_fn",    # Changing how improvement is measured
    "modify_safety_rule",      # Changing safety constraints
    "auto_apply_fix",          # Auto-applying a fix candidate
    "modify_script",           # Modifying any .py file outside meta/
]

APPROVAL_OPTIONAL_CHANGES = [
    "threshold_tuning",        # Numeric threshold adjustment
    "pipeline_reorder",        # Phase execution order
    "policy_merge",            # Merging near-duplicate policies
    "retire_stale",            # Archiving zero-hit policies
]
```

**Approval-required** changes go into `meta/pending-changes.json` and stay there until human runs `meta-improver.py --approve <id>`. They are surfaced in the daily briefing.

**Approval-optional** changes auto-apply after 3 idle cycles (6 hours) of remaining pending, OR immediately if the improvement is statistically significant (p < 0.05 on before/after metrics).

### 6.5 Circular Self-Reference Boundary

The meta-improver **cannot modify its own evaluation criteria**. This is enforced by:

1. **Code structure**: The safety rules in `meta-improver.py` Section 6 are hardcoded as a module-level constant. The script's main loop reads this constant but never writes to it.
2. **File-level lock**: The script `meta-improver.py` is read by the script itself at startup and its SHA-256 is compared against a reference hash. If the file has changed since the last audit, the script aborts.
3. **Domain boundary**: The meta-improver operates on a different data store (`meta/`) from the policies it improves (`policies/`). It never modifies `policies/` directly — only through approved merge/retire operations.
4. **No code generation**: The script never writes new Python files. It only toggles config values, reorders phases, and generates JSON proposals.

### 6.6 Observability

- Every cycle writes a structured report to `logs/meta-improver/YYYY-MM-DD.md`
- The `meta-improver.py --status` command shows current pipeline health
- The `meta-improver.py --history` command shows last 30 days of changes
- The daily briefing (9am) shows a "Meta-Improver" section with pending changes

---

## 7. Concrete Metrics

### What gets measured

```
pipeline_metrics = {
    "cycle_duration_seconds": <float>,        # Total idle runtime
    "phase_timing_ms": {                      # Per-phase latency
        "consolidation": <int>,
        "regression": <int>,
        "gap_finding": <int>,
        "meta_improvement": <int>
    },
    "policy_count": <int>,                    # Total active policies
    "coverage_pct": <float>,                  # Regression coverage %
    "gap_count": <int>,                       # Uncovered failure domains
    "corrections_this_cycle": <int>,          # New user corrections since last run
    "proposed_fixes": <int>,                  # Fix candidates generated
    "pending_approvals": <int>,               # Changes awaiting human signoff
    "pipeline_throughput": <float>,           # Policies per correction per cycle
    "meta_changes_applied": <int>,            # Changes to the pipeline itself
    "off_switch_status": <bool>               # Is auto-learning enabled?
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

---

## 8. Implementation Plan

### Phase 1 — Scaffold (Day 1)
1. Create `~/.hermes/meta/` directory with config template
2. Write `meta-improver.py` with safety checks, preflight/postflight, audit logging
3. Create off-switch file
4. Wire `idle-learning-run.sh` to call meta phases
5. Test: run `meta-improver.py --preflight --postflight` with no changes to verify logging

### Phase 2 — Measure (Day 2-3)
1. Collect baseline metrics for 3-4 idle cycles
2. Fix any metric collection gaps
3. Write `meta-audit-report.py` for human-readable output

### Phase 3 — Analyze (Day 4-5)
1. Implement bottleneck detection (Section 5 — CAN do part)
2. Generate threshold-tuning candidates
3. Wire into daily briefing so Chidi sees "Pending improvements"

### Phase 4 — Act (Day 6+)
1. Implement approval-optional auto-apply for threshold tuning
2. Test with real corrections over several days
3. Measure whether pipeline throughput increases

---

## 9. Relationship to Existing Architecture

| Existing | New | Relationship |
|----------|-----|-------------|
| `08-goetic-piece.md` (off-switch) | This spec's Section 6.1 | Off-switch becomes file-based, checked at every idle cycle |
| `01-correction-learning-loop.md` | Unchanged | Still the core learning mechanism; meta-improver makes it faster |
| `04-idle-consolidation.md` | Enhanced (auto-merge at high confidence) | Lower threshold work automated |
| `05-self-regression.md` | Enhanced (trend tracking, candidate testing) | More analytical, not just pass/fail |
| `06-gap-finding.md` | Enhanced (fix candidate generation) | From "here's a gap" to "here's a gap and a proposed fix" |
| `09-idle-continuous-learning.md` | Superseded by this spec | This spec replaces 09; all idle learning now runs through meta-improver pipeline |

---

## 10. Failure Modes and Recovery

| Failure Mode | Detection | Recovery |
|-------------|-----------|----------|
| Meta-improver introduces buggy threshold | Metrics degrade (coverage drops, latency spikes) | `meta-improver.py --rollback <change_id>` restores last good config |
| Off-switch file accidentally deleted | Otto stops improving; no auto-learning runs | `touch ~/.hermes/meta/OFF_SWITCH` to re-enable |
| Fix candidate generation is low quality | Acceptance rate stays at 0% | Tune generation prompt; or disable fix-candidate phase |
| Pipeline phase hangs | Runtime exceeds 2-min cap | Idle-learning-run.sh kills the phase; next cycle skips it |
| Meta-improver detects (false positive) bottleneck | Unnecessary threshold tuning | Rollback to previous; improve bottleneck detection criteria |
| Circular self-reference attempt (meta-improver modifies its own metrics) | SHA-256 hash mismatch on meta-improver.py | Script aborts; requires human to verify integrity |
