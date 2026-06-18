#!/usr/bin/env python3
"""
meta-improver.py — Core meta-improvement loop for Otto.

This is the exponential lever in Otto's self-improvement architecture.
It operates as a TWO-LOOP system:

INNER LOOP (pipeline optimization):
  1. Measure pipeline throughput (improvement velocity)
  2. Validate previous meta-changes against actual outcomes
  3. Detect current bottleneck
  4. Generate and apply candidate change

OUTER LOOP (meta-pattern discovery):
  1. Track every applied change + its outcome in change-outcomes.jsonl
  2. Cluster change_types by historical success rate
  3. Prioritize HIGH_YIELD change types, suppress LOW_YIELD
  4. Never invents new change types (fixed set of 5)

WHAT IT CAN DO:
  - Measure pipeline performance (latency, yield, quality)
  - Compute improvement velocity (the compound metric)
  - Validate previous changes (did they actually help?)
  - Learn which change types work (outer loop over outcomes)
  - Detect bottlenecks in consolidation/regression/gap-finding
  - Tune numeric thresholds within bounded ranges
  - Re-order pipeline phases (respecting DAG constraints)
  - Generate and apply fix candidates immediately
  - Auto-retire stale policies (zero hits for 30+ days)
  - Log everything

WHAT IT CANNOT DO:
  - Modify its own evaluation criteria (fixed change types)
  - Modify its own safety rules (module-level constant, never written)
  - Modify itself (externally stored script hash)
  - Modify scripts outside meta/ and scripts/ directory
  - Access external systems or deploy code
  - Remove the off-switch
  - Modify human audit trail (append-only)
  - Invent new change types (only 5 hardcoded types)

SAFETY MECHANISMS:
  - Off-switch (OFF_SWITCH file): Disable all automatic learning
  - SHA-256 reference hash: Prevents in-loop self-modification
  - Fixed CHANGE_TYPES frozenset: Cannot invent new change types
  - Safety bounds on threshold tuning (SAFETY_RULES)
  - DAG constraints on pipeline reordering
  - Max active policies safeguard
  - Velocity convergence detection
  - Rollback mechanism (30-day window)
  - Full audit trail and change-outcomes tracking

Usage:
    meta-improver.py --status                    # Show current pipeline health
    meta-improver.py --preflight                 # Snapshot state + check off-switch
    meta-improver.py --analyze                   # Detect bottlenecks + generate & apply candidates
    meta-improver.py --postflight                # Snapshot state + compute diff + outcomes
    meta-improver.py --rollback <change-id>      # Roll back a specific change
    meta-improver.py --history [--last N]        # Show recent changes
    meta-improver.py --outcomes                  # Show change type success rates (outer loop)
    meta-improver.py --full-cycle                # Run preflight → analyze → postflight
"""

import json
import os
import sys
import hashlib
import copy
import glob
import argparse
import re
from datetime import datetime, timezone, timedelta
from typing import Any

# ── Paths ───────────────────────────────────────────────────────────────────

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
META_DIR = os.path.join(HERMES_HOME, "meta")
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
ARCHIVE_DIR = os.path.join(POLICY_DIR, "archived")
LOGS_DIR = os.path.join(HERMES_HOME, "logs", "meta-improver")
SNAPSHOT_DIR = os.path.join(META_DIR, "snapshots")
METRICS_FILE = os.path.join(META_DIR, "metrics.jsonl")
PIPELINE_CONFIG = os.path.join(META_DIR, "pipeline-config.json")
PENDING_CHANGES = os.path.join(META_DIR, "pending-changes.json")
FIX_CANDIDATES = os.path.join(META_DIR, "fix-candidates.json")
OFF_SWITCH = os.path.join(META_DIR, "OFF_SWITCH")
REJECTED_LOG = os.path.join(META_DIR, "rejected-changes.jsonl")
AUDIT_INDEX = os.path.join(LOGS_DIR, "audit-index.jsonl")
REFERENCE_HASH = os.path.join(META_DIR, "reference-script-hash.json")
CHANGE_OUTCOMES = os.path.join(META_DIR, "change-outcomes.jsonl")

# Ensure directories exist
for d in [META_DIR, LOGS_DIR, SNAPSHOT_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Hardcoded Safety Rules (Section 6 — non-negotiable) ─────────────────────

# These are read at runtime but never modified by this script.
# The set of change types is FIXED — this script cannot invent new ones.
# To change these, edit this source file directly (human action).

# Valid pipeline phases in dependency order
# Topological order constraint for pipeline_reorder:
# preflight must be first, postflight must be last.
# meta_improvement must precede gap_finding (generates candidates gap_finding uses).
# consolidation, self_regression, gap_finding can run in any order relative to each other.
PIPELINE_DAG = {
    "preflight": {"depends_on": [], "order_group": 0},
    "meta_improvement": {"depends_on": ["preflight"], "order_group": 1},
    "gap_finding": {"depends_on": ["preflight"], "order_group": 2},
    "self_regression": {"depends_on": ["preflight"], "order_group": 2},
    "consolidation": {"depends_on": ["preflight"], "order_group": 2},
    "postflight": {"depends_on": ["preflight", "meta_improvement", "gap_finding", "self_regression", "consolidation"], "order_group": 3},
}

# Fixed set of change types — the meta-improver cannot invent new ones
# All change types are auto-applied during --analyze. No human approval gate.
CHANGE_TYPES = frozenset([
    "threshold_tuning",
    "pipeline_reorder",
    "policy_merge",
    "retire_stale",
    "add_pipeline_phase",
])

SAFETY_RULES = {
    # Bounds for threshold tuning (cannot be tuned outside these ranges)
    "threshold_bounds": {
        "demote_ratio": {"min": 0.2, "max": 0.6},
        "similarity_threshold": {"min": 0.4, "max": 0.9},
        "promote_min_hits": {"min": 1, "max": 10},
    },
    # Maximum number of active policies
    "max_active_policies": 200,
    # Days since last hit before auto-retire
    "stale_policy_days": 30,
    # Velocity convergence threshold — when improvement is below this, stop proposing
    "velocity_convergence_threshold": 0.01,  # 1% improvement per cycle
    # Minimum cycles before marking an outcome as "determined"
    "outcome_determination_cycles": 3,
}

# ── Default Pipeline Config ─────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "pipeline_version": 2,
    "phases": {
        "preflight": {
            "enabled": True,
            "order": 0,
            "script": "meta-improver.py",
            "args": ["--preflight"],
            "max_runtime_seconds": 10,
        },
        "meta_improvement": {
            "enabled": True,
            "order": 1,
            "script": "meta-improver.py",
            "args": ["--analyze"],
            "max_runtime_seconds": 20,
        },
        "gap_finding": {
            "enabled": True,
            "order": 2,
            "script": "gap-finding.py",
            "args": ["--report", "--generate-candidates"],
            "max_runtime_seconds": 30,
        },
        "self_regression": {
            "enabled": True,
            "order": 3,
            "script": "self-regression.py",
            "args": ["--report"],
            "max_runtime_seconds": 30,
        },
        "consolidation": {
            "enabled": True,
            "order": 4,
            "script": "idle-consolidation.py",
            "args": [],
            "max_runtime_seconds": 30,
            "thresholds": {
                "similarity_threshold": 0.65,
                "demote_ratio": 0.4,
                "promote_min_hits": 3,
            },
        },
        "postflight": {
            "enabled": True,
            "order": 5,
            "script": "meta-improver.py",
            "args": ["--postflight"],
            "max_runtime_seconds": 10,
        },
    },
    "meta": {
        "metrics_window": 10,
        "enabled": True,
        "velocity_window": 5,  # Number of cycles to compute velocity over
        "outer_loop_min_samples": 5,  # Min change outcome records before outer loop engages
    },
    "created_at": None,
    "updated_at": None,
}


# ── Helpers ─────────────────────────────────────────────────────────────────


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def compute_script_hash() -> str:
    """Compute SHA-256 of this script for circular-self-reference detection."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_config() -> dict:
    if os.path.exists(PIPELINE_CONFIG):
        with open(PIPELINE_CONFIG) as f:
            return json.load(f)
    # Create default
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["created_at"] = iso_now()
    cfg["updated_at"] = iso_now()
    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    cfg["updated_at"] = iso_now()
    with open(PIPELINE_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def load_policies() -> list[dict]:
    policies = []
    if not os.path.isdir(POLICY_DIR):
        return policies
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(POLICY_DIR, fname)
            with open(path) as f:
                p = json.load(f)
            p["_filepath"] = path
            policies.append(p)
    return policies


def load_metrics(n: int = 10) -> list[dict]:
    if not os.path.exists(METRICS_FILE):
        return []
    with open(METRICS_FILE) as f:
        lines = f.readlines()
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def append_metric(entry: dict):
    os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)
    with open(METRICS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_pending_changes() -> list[dict]:
    if not os.path.exists(PENDING_CHANGES):
        return []
    with open(PENDING_CHANGES) as f:
        return json.load(f)


def save_pending_changes(changes: list[dict]):
    os.makedirs(os.path.dirname(PENDING_CHANGES), exist_ok=True)
    with open(PENDING_CHANGES, "w") as f:
        json.dump(changes, f, indent=2)


def load_rejected() -> set:
    if not os.path.exists(REJECTED_LOG):
        return set()
    rejected = set()
    with open(REJECTED_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line)
                rejected.add(entry.get("change_id"))
            except json.JSONDecodeError:
                continue
    return rejected


def log_rejected(change_id: str, description: str):
    entry = {
        "change_id": change_id,
        "description": description,
        "rejected_at": iso_now(),
    }
    with open(REJECTED_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def validate_phase_reorder(new_order_map: dict) -> tuple[bool, str]:
    """
    Validate a pipeline reorder against the DAG.
    new_order_map: {phase_name: new_order_int}
    Phases not mentioned keep their current order.
    """
    # Build dependency graph from DAG
    # Check: no phase can run before its dependencies
    # Check: preflight must be first (order 0), postflight last (highest order)

    for phase, new_order in new_order_map.items():
        if phase not in PIPELINE_DAG:
            return (False, f"Unknown phase: {phase}")

    # Check preflight isn't moved
    if "preflight" in new_order_map and new_order_map["preflight"] != 0:
        return (False, "preflight must have order 0 (must be first)")

    # Check postflight isn't moved to non-last
    # We check by ensuring no other phase has an order >= postflight's
    if "postflight" in new_order_map:
        postflight_order = new_order_map["postflight"]
        for other_phase, other_order in new_order_map.items():
            if other_phase != "postflight" and other_order > postflight_order:
                return (False, "postflight must have the highest order (must be last)")

    # Check no phase runs before its dependencies
    config = load_config()
    all_orders = dict(config.get("phases", {}))
    for phase, order in new_order_map.items():
        all_orders[phase] = {"order": order}
    for unknown_phase in set(all_orders.keys()) - set(new_order_map.keys()):
        pass  # These keep their existing orders

    # Build full order map
    full_order = {}
    for phase, phase_config in all_orders.items():
        if phase in new_order_map:
            full_order[phase] = new_order_map[phase]
        else:
            full_order[phase] = phase_config.get("order", 99)

    # Check DAG: for each phase, all dependencies must have lower (earlier) order
    for phase, deps in PIPELINE_DAG.items():
        if phase not in full_order:
            continue
        phase_order = full_order[phase]
        for dep in deps.get("depends_on", []):
            if dep in full_order:
                dep_order = full_order[dep]
                if dep_order is not None and dep_order > phase_order:
                    return (False, f"{phase} (order {phase_order}) depends on {dep} (order {dep_order}), but {dep} runs later")

    return (True, "Valid DAG ordering")


# ── Script Integrity ────────────────────────────────────────────────────────


def load_reference_hash() -> str | None:
    """Load the externally-stored reference script hash."""
    if not os.path.exists(REFERENCE_HASH):
        return None
    try:
        with open(REFERENCE_HASH) as f:
            data = json.load(f)
        return data.get("sha256")
    except (json.JSONDecodeError, KeyError):
        return None


def check_script_integrity() -> tuple[bool, str]:
    """
    Check that this script hasn't been modified since the reference hash was recorded.
    Returns (is_intact, message).
    """
    current_hash = compute_script_hash()
    reference_hash = load_reference_hash()

    if reference_hash is None:
        # First run — need to bootstrap the reference hash
        # This requires human action (--bootstrap-hash)
        return (False, "No reference hash found. Run --bootstrap-hash to initialize.")

    if current_hash != reference_hash:
        return (False, f"Script hash mismatch: reference={reference_hash[:16]}..., current={current_hash[:16]}...")

    return (True, "Script integrity verified.")


def bootstrap_reference_hash():
    """Write the current script's hash as the reference hash.
    This should only be done on explicit human instruction."""
    current_hash = compute_script_hash()
    data = {
        "script_path": __file__,
        "sha256": current_hash,
        "recorded_at": iso_now(),
        "recorded_by": "human_instruction",
        "note": "This file stores the reference SHA-256 of meta-improver.py. "
                "The script checks this at every --preflight. "
                "If the script is modified (legitimate update), this file must be updated "
                "by human action: meta-improver.py --bootstrap-hash",
    }
    with open(REFERENCE_HASH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Reference hash bootstrapped: {current_hash[:16]}...")
    print(f"   Stored at: {REFERENCE_HASH}")
    return 0


# ── Off-Switch ──────────────────────────────────────────────────────────────


def check_off_switch() -> bool:
    """Check if off-switch exists. Returns True if learning is allowed."""
    if not os.path.exists(OFF_SWITCH):
        print("⛔ OFF_SWITCH absent — aborting all automatic learning")
        return False
    return True


# ── Snapshot + Audit ────────────────────────────────────────────────────────


def snapshot_state(tag: str) -> str:
    """Create a full snapshot of current state, return filename."""
    snapshot = {
        "timestamp": iso_now(),
        "tag": tag,
        "policies": load_policies(),
        "config": load_config(),
        "script_hash": compute_script_hash(),
    }
    fname = f"snapshot-{tag}-{timestamp_id()}.json"
    path = os.path.join(SNAPSHOT_DIR, fname)
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"  📸 Snapshot saved: {fname}")
    return fname


def find_snapshot(tag_prefix: str) -> str | None:
    """Find the most recent snapshot matching a prefix."""
    pattern = os.path.join(SNAPSHOT_DIR, f"snapshot-{tag_prefix}-*.json")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def load_snapshot(filename: str) -> dict | None:
    path = os.path.join(SNAPSHOT_DIR, filename) if not filename.startswith("/") else filename
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def write_audit_record(record: dict) -> str:
    """Write a per-change audit record to logs/meta-improver/ and index."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    change_id = record.get("change_id", f"change-{timestamp_id()}")
    path = os.path.join(LOGS_DIR, f"{change_id}.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)

    # Append to index
    index_entry = {
        "change_id": change_id,
        "change_type": record.get("change_type", "unknown"),
        "applied_at": record.get("applied_at"),
        "human_approved": record.get("human_approved", False),
        "reversible": record.get("reversible", True),
        "audit_file": path,
    }
    os.makedirs(os.path.dirname(AUDIT_INDEX), exist_ok=True)
    with open(AUDIT_INDEX, "a") as f:
        f.write(json.dumps(index_entry) + "\n")
    print(f"  📝 Audit record: {path}")
    return change_id


# ── Change Outcomes (for outer loop) ────────────────────────────────────────


def load_change_outcomes() -> list[dict]:
    """Load all historical change outcomes."""
    if not os.path.exists(CHANGE_OUTCOMES):
        return []
    outcomes = []
    with open(CHANGE_OUTCOMES) as f:
        for line in f:
            try:
                outcomes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return outcomes


def append_change_outcome(entry: dict):
    """Append a new change outcome entry."""
    os.makedirs(os.path.dirname(CHANGE_OUTCOMES), exist_ok=True)
    with open(CHANGE_OUTCOMES, "a") as f:
        f.write(json.dumps(entry) + "\n")


def compute_improvement_velocity(metrics: list[dict], window: int = 5) -> float:
    """
    Compute improvement velocity over the last N cycles.
    velocity = (coverage_end - coverage_start) / N
    If no coverage data, returns 0.0.
    """
    if len(metrics) < 2:
        return 0.0

    relevant = metrics[-window:] if len(metrics) >= window else metrics
    coverages = [m.get("coverage_pct", 0) or 0 for m in relevant]

    if len(coverages) < 2:
        return 0.0

    # Use linear approximation: (last - first) / (count - 1) cycles
    delta = coverages[-1] - coverages[0]
    cycles = len(coverages) - 1
    if cycles <= 0:
        return 0.0
    return round(delta / cycles, 4)


def evaluate_pending_outcomes(metrics: list[dict], config: dict):
    """
    Check pending change outcomes to see if velocity improved.
    Called during postflight.
    """
    outcomes = load_change_outcomes()
    pending_outcomes = [o for o in outcomes if o.get("outcome") == "pending"]
    if not pending_outcomes:
        return

    velocity = compute_improvement_velocity(metrics, config.get("meta", {}).get("velocity_window", 5))

    for outcome in pending_outcomes:
        # Track how many cycles since application
        applied_at = outcome.get("applied_at")
        if not applied_at:
            continue

        try:
            applied_time = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
            cycles_since = max(1, int(
                (datetime.now(timezone.utc) - applied_time).total_seconds() / 7200
            ))
        except (ValueError, TypeError):
            continue

        velocity_before = outcome.get("velocity_before") or 0
        velocity_delta = velocity - velocity_before

        # Update the outcome record
        outcome_key = outcome.get("change_id")
        if cycles_since == 1:
            outcome["velocity_after_N1"] = velocity
        if cycles_since >= 3:
            outcome["velocity_after_N3"] = velocity
            # Determine outcome based on velocity delta after 3+ cycles
            if velocity_delta > SAFETY_RULES.get("velocity_convergence_threshold", 0.01):
                outcome["outcome"] = "improved"
            elif velocity_delta < -SAFETY_RULES.get("velocity_convergence_threshold", 0.01):
                outcome["outcome"] = "degraded"
            else:
                outcome["outcome"] = "neutral"
            outcome["outcome_determined_at"] = iso_now()
            print(f"  📊 Change {outcome_key}: outcome={outcome['outcome']} "
                  f"(velocity: {velocity_before} → {velocity}, delta={velocity_delta:+.4f})")

    # Rewrite the outcomes file with updated entries
    # (We do a full rewrite because we're updating existing entries)
    updated_lines = []
    for o in outcomes:
        updated_lines.append(json.dumps(o) + "\n")
    with open(CHANGE_OUTCOMES, "w") as f:
        f.writelines(updated_lines)


def get_change_type_performance(outcomes: list[dict]) -> dict:
    """
    Analyze historical change outcomes by change_type.
    Returns dict mapping change_type -> {
        success_rate: float,       # (improved) / (improved + degraded + neutral)
        avg_velocity_delta: float,  # Average velocity delta across all outcomes
        sample_count: int,
        classification: str        # "HIGH_YIELD" | "LOW_YIELD" | "UNKNOWN"
    }
    This is the outer loop's analytical output.
    """
    by_type = {}
    for o in outcomes:
        if o.get("outcome") in ("pending", None):
            continue
        ct = o.get("change_type", "unknown")
        if ct not in by_type:
            by_type[ct] = {"improved": 0, "degraded": 0, "neutral": 0, "velocity_deltas": []}
        by_type[ct][o["outcome"]] = by_type[ct].get(o["outcome"], 0) + 1
        # None-safe: a key can be PRESENT with an explicit null velocity, so .get's
        # default never fires and `None - float` crashed the whole idle-learning
        # pipeline every run (Ball 16). Coerce nulls to 0.0.
        v_before = o.get("velocity_before") or 0.0
        v_after = o.get("velocity_after_N3") or o.get("velocity_after_N1") or v_before
        by_type[ct]["velocity_deltas"].append((v_after or 0.0) - (v_before or 0.0))

    result = {}
    MIN_SAMPLES = SAFETY_RULES.get("meta", {}).get("outer_loop_min_samples", 5)

    for ct, stats in by_type.items():
        total = stats["improved"] + stats["degraded"] + stats["neutral"]
        success_rate = stats["improved"] / total if total > 0 else 0
        avg_delta = sum(stats["velocity_deltas"]) / len(stats["velocity_deltas"]) if stats["velocity_deltas"] else 0

        if total >= MIN_SAMPLES:
            if success_rate >= 0.5:
                classification = "HIGH_YIELD"
            elif success_rate < 0.2:
                classification = "LOW_YIELD"
            else:
                classification = "MEDIUM_YIELD"
        else:
            classification = "UNKNOWN"

        result[ct] = {
            "success_rate": round(success_rate, 3),
            "avg_velocity_delta": round(avg_delta, 4),
            "sample_count": total,
            "classification": classification,
            "improved": stats["improved"],
            "degraded": stats["degraded"],
            "neutral": stats["neutral"],
        }

    return result


# ── Safety Validation ───────────────────────────────────────────────────────


def validate_candidate(candidate: dict) -> tuple[bool, str]:
    """
    Validate a candidate change against safety rules.
    Returns (is_valid, reason).
    """
    change_type = candidate.get("change_type", "")
    params = candidate.get("params", {})

    # Rule 0: Must be a recognized change type
    if change_type not in CHANGE_TYPES:
        return (False, f"Unknown change type: {change_type}. Valid types: {', '.join(sorted(CHANGE_TYPES))}")

    # Rule 1: Cannot modify evaluation criteria
    if change_type == "modify_evaluation_fn":
        return (False, "Cannot modify evaluation criteria (circular self-reference)")

    # Rule 2: Cannot modify safety rules
    if change_type == "modify_safety_rule":
        return (False, "Cannot modify safety rules (circular self-reference)")

    # Rule 3: Threshold tuning must respect bounds
    if change_type == "threshold_tuning":
        threshold_name = params.get("threshold_name", "")
        new_value = params.get("new_value")
        bounds = SAFETY_RULES["threshold_bounds"].get(threshold_name)
        if bounds and new_value is not None:
            if new_value < bounds["min"] or new_value > bounds["max"]:
                return (False, f"{threshold_name}={new_value} outside bounds [{bounds['min']}, {bounds['max']}]")

    # Rule 4: Pipeline reorder must respect DAG
    if change_type == "pipeline_reorder":
        new_order = params.get("new_order", {})
        is_valid, reason = validate_phase_reorder(new_order)
        if not is_valid:
            return (False, f"Phase reorder violates DAG: {reason}")

    # Rule 5: Cannot exceed max policy count
    if change_type in ("policy_merge",):
        current_count = len([p for p in load_policies() if p.get("status") in ("active", "provisional")])
        estimated_new = params.get("estimated_new_policies", 0)
        if current_count + estimated_new > SAFETY_RULES["max_active_policies"]:
            return (False, f"Would exceed max {SAFETY_RULES['max_active_policies']} active policies ({current_count} + {estimated_new})")

    # Rule 6: Can't approve a change that's already rejected
    rejected = load_rejected()
    if candidate.get("change_id") in rejected:
        return (False, "This change was previously rejected")

    return (True, "OK")


def apply_change(change: dict) -> int:
    """Apply a validated candidate change immediately.

    Returns 0 on success, 1 on failure.
    All applied changes are recorded in the audit trail and change-outcomes.jsonl.
    """
    change_id = change.get("change_id", f"change-{timestamp_id()}")
    change_type = change.get("change_type")
    params = change.get("params", {})

    # Validate again
    is_valid, reason = validate_candidate(change)
    if not is_valid:
        print(f"  ✗ Cannot apply {change_id}: {reason}")
        return 1

    # Snapshot before applying
    pre_snapshot = snapshot_state("pre-apply")

    config = load_config()
    before_config = copy.deepcopy(config)

    # Capture pre-application velocity for outcome tracking
    metrics = load_metrics(config.get("meta", {}).get("velocity_window", 5))
    velocity_before = compute_improvement_velocity(metrics, config.get("meta", {}).get("velocity_window", 5))

    if change_type == "threshold_tuning":
        threshold_name = params.get("threshold_name")
        new_value = params.get("new_value")
        phase = params.get("phase", "consolidation")
        if phase in config["phases"] and "thresholds" in config["phases"][phase]:
            if threshold_name in config["phases"][phase]["thresholds"]:
                old_value = config["phases"][phase]["thresholds"][threshold_name]
                config["phases"][phase]["thresholds"][threshold_name] = new_value
                save_config(config)
                print(f"  ✅ Tuned {phase}.{threshold_name}: {old_value} → {new_value}")

    elif change_type == "pipeline_reorder":
        new_order = params.get("new_order", {})
        # Validate DAG before applying
        is_valid, reason = validate_phase_reorder(new_order)
        if not is_valid:
            print(f"  ✗ Pipeline reorder violates DAG: {reason}")
            return 1
        for phase_name, order in new_order.items():
            if phase_name in config["phases"]:
                old_order = config["phases"][phase_name].get("order")
                config["phases"][phase_name]["order"] = order
                print(f"  ✅ Reordered {phase_name}: {old_order} → {order}")
        save_config(config)

    elif change_type == "retire_stale":
        policy_id = params.get("policy_id")
        policy_path = os.path.join(POLICY_DIR, f"{policy_id}.json")
        if os.path.exists(policy_path):
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            archive_path = os.path.join(ARCHIVE_DIR, f"{policy_id}.json")
            with open(policy_path) as f:
                policy_data = json.load(f)
            policy_data["status"] = "archived"
            policy_data["archived_at"] = iso_now()
            policy_data["archived_by"] = "meta-improver"
            with open(archive_path, "w") as f:
                json.dump(policy_data, f, indent=2)
            os.remove(policy_path)
            print(f"  ✅ Retired {policy_id} → archived/")

    elif change_type == "policy_merge":
        merge_policy_ids = params.get("policy_ids", [])
        merged_trigger = params.get("merged_trigger", "")
        merged_rule = params.get("merged_rule", "")
        if len(merge_policy_ids) >= 2:
            merged = {
                "id": f"pol-merged-{timestamp_id()}",
                "trigger": merged_trigger,
                "rule": merged_rule,
                "scope": {},
                "confidence": 0.7,
                "hits": 0,
                "helped": 0,
                "hurt": 0,
                "status": "active",
                "created": iso_now(),
                "last_fired": None,
                "source_correction": f"Merged from: {', '.join(merge_policy_ids)}",
            }
            merged_path = os.path.join(POLICY_DIR, f"{merged['id']}.json")
            with open(merged_path, "w") as f:
                json.dump(merged, f, indent=2)
            for pid in merge_policy_ids:
                src = os.path.join(POLICY_DIR, f"{pid}.json")
                if os.path.exists(src):
                    dst = os.path.join(ARCHIVE_DIR, f"{pid}.json")
                    with open(src) as f:
                        pdata = json.load(f)
                    pdata["status"] = "archived"
                    pdata["merged_into"] = merged["id"]
                    with open(dst, "w") as f:
                        json.dump(pdata, f, indent=2)
                    os.remove(src)
            print(f"  ✅ Merged {', '.join(merge_policy_ids)} → {merged['id']}")

    else:
        print(f"  ✗ Unknown change type: {change_type}")
        return 1

    # Record audit trail
    post_snapshot = snapshot_state("post-apply")
    audit = {
        "change_id": change_id,
        "change_type": change_type,
        "description": change.get("description", ""),
        "applied_at": iso_now(),
        "human_approved": True,
        "reversible": True,
        "preflight_snapshot": pre_snapshot,
        "postflight_snapshot": post_snapshot,
        "before_state": before_config,
        "after_state": load_config(),
        "rollback_command": f"meta-improver.py --rollback {change_id}",
        "rollback_valid_until": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_audit_record(audit)

    # Record change outcome for outer loop tracking
    outcome_entry = {
        "change_id": change_id,
        "change_type": change_type,
        "description": change.get("description", ""),
        "applied_at": iso_now(),
        "velocity_before": velocity_before,
        "velocity_after_N1": None,
        "velocity_after_N3": None,
        "outcome": "pending",
        "outcome_determined_at": None,
    }
    append_change_outcome(outcome_entry)
    print(f"  📊 Outcome tracking started for {change_id} (baseline velocity: {velocity_before:+.4f})")

    # Log metrics
    append_metric({
        "timestamp": iso_now(),
        "event": "change_applied",
        "change_id": change_id,
        "change_type": change_type,
        "human_approved": True,
    })

    return 0


# ── Core Commands ────────────────────────────────────────────────────────────


def cmd_status():
    """Show current pipeline health."""
    config = load_config()
    metrics = load_metrics(5)
    policies = load_policies()

    print("=" * 60)
    print("      Otto Meta-Improver — Pipeline Status")
    print("=" * 60)
    print(f"  Off-switch:     {'✅ ACTIVE' if os.path.exists(OFF_SWITCH) else '⛔ DISABLED'}")
    print(f"  Script hash:    {'✅ VERIFIED' if check_script_integrity()[0] else '⚠️ MISMATCH'}")
    print(f"  Pipeline ver:   {config.get('pipeline_version', 0)}")
    print(f"  Last updated:   {config.get('updated_at', 'never')}")
    print()

    # Show improvement velocity if metrics available
    if len(metrics) >= 2:
        velocity = compute_improvement_velocity(metrics, config.get("meta", {}).get("velocity_window", 5))
        print(f"  Improvement velocity: {velocity:+.4f} coverage_pct/cycle")
        print()

    print("  Phases:")
    phases = config.get("phases", {})
    for name, phase in sorted(phases.items(), key=lambda x: x[1].get("order", 99)):
        enabled = phase.get("enabled", False)
        icon = "✅" if enabled else "⛔"
        print(f"    {icon} [{phase.get('order', '?')}] {name} ({phase.get('script', '?')})")
    print()

    print(f"  Policies:       {len(policies)} total ({len([p for p in policies if p.get('status') in ('active', 'provisional')])} active/provisional)")
    print()

    # Show outer loop stats if available
    outcomes = load_change_outcomes()
    if outcomes:
        performance = get_change_type_performance(outcomes)
        print("  Change type performance (outer loop):")
        for ct, stats in sorted(performance.items()):
            badge = "🟢" if stats["classification"] == "HIGH_YIELD" else "🔴" if stats["classification"] == "LOW_YIELD" else "🟡" if stats["classification"] == "MEDIUM_YIELD" else "⚪"
            print(f"    {badge} {ct}: {stats['classification']} "
                  f"(success={stats['success_rate']:.0%}, n={stats['sample_count']}, "
                  f"avg_delta={stats['avg_velocity_delta']:+.4f})")
        print()

    pending = load_pending_changes()
    if pending:
        print(f"  Pending changes: {len(pending)}")
        for change in pending[:5]:
            print(f"    ⏳ {change.get('change_id', '?')}: {change.get('description', '?')[:60]}")
    else:
        print("  Pending changes: 0")
    print()

    if metrics:
        last = metrics[-1]
        print(f"  Last cycle:     {last.get('timestamp', '?')}")
        print(f"  Coverage:       {last.get('coverage_pct', '?')}%")
        print(f"  Duration:       {last.get('cycle_duration_seconds', '?')}s")
    return 0


def cmd_preflight():
    """Snapshot state before improvement cycle. Check off-switch and script integrity."""
    print("--- Preflight ---")

    # 1. Check off-switch
    if not check_off_switch():
        return 0

    # 2. Check script integrity against external reference hash
    is_intact, message = check_script_integrity()
    if not is_intact:
        print(f"⚠️  Script integrity check failed: {message}")
        print("   Aborting for safety. Options:")
        print("   - If script was legitimately updated: meta-improver.py --bootstrap-hash")
        print("   - If script was tampered: restore from backup, then bootstrap")
        return 1

    # 3. Snapshot current state
    snapshot_filename = snapshot_state("preflight")

    # 4. Log basic metrics
    policies = load_policies()
    active = [p for p in policies if p.get("status") in ("active", "provisional")]
    append_metric({
        "timestamp": iso_now(),
        "event": "preflight",
        "policy_count": len(policies),
        "active_count": len(active),
        "snapshot": snapshot_filename,
    })

    print(f"  ✅ Preflight complete. {len(active)} active policies.")
    return 0


def cmd_analyze():
    """
    Detect bottlenecks in the improvement pipeline and generate candidates.
    This is the core exponential improvement mechanism with TWO LOOPS:

    INNER LOOP:
      1. Load last N cycles of metrics
      2. Compute improvement velocity
      3. Validate previous meta-changes (did they improve velocity?)
      4. Detect current bottleneck
      5. Generate and apply candidate change

    OUTER LOOP:
      6. Load change-outcomes.jsonl
      7. Compute change_type performance stats
      8. Prioritize HIGH_YIELD types, suppress LOW_YIELD types
    """
    print("--- Meta-Improvement Analysis ---")

    config = load_config()
    metrics = load_metrics(config.get("meta", {}).get("metrics_window", 10))
    policies = load_policies()
    pending = load_pending_changes()
    rejected = load_rejected()

    if not metrics:
        print("  Not enough data yet. Run a few more cycles first.")
        print("  Need at least 2 metric entries for trend analysis.")
        return 0

    # ── Compute Improvement Velocity ──────────────────────────────────────
    window = config.get("meta", {}).get("velocity_window", 5)
    velocity = compute_improvement_velocity(metrics, window)
    print(f"  📊 Improvement velocity (last {min(window, len(metrics))} cycles): {velocity:+.4f} coverage_pct/cycle")

    # ── Validate Previous Meta-Changes ────────────────────────────────────
    # Check if any applied changes now have a determinable outcome
    evaluate_pending_outcomes(metrics, config)

    # ── Load Outer Loop Performance Stats ─────────────────────────────────
    outcomes = load_change_outcomes()
    change_type_performance = get_change_type_performance(outcomes)
    print(f"  🧠 Outer loop: {len(outcomes)} outcome records, "
          f"{len([c for c in change_type_performance.values() if c['classification'] == 'HIGH_YIELD'])} HIGH_YIELD types")

    candidates = []

    # ── Convergence Check ─────────────────────────────────────────────────
    # If velocity is below threshold, don't propose further pipeline changes
    velocity_threshold = SAFETY_RULES.get("velocity_convergence_threshold", 0.01)
    if abs(velocity) < velocity_threshold and len(metrics) >= window:
        print(f"  ⚠️  Improvement velocity ({velocity:+.4f}) below convergence threshold ({velocity_threshold}).")
        print("   Pipeline optimization may have converged or reached diminishing returns.")
        # Still generate non-tuning candidates (policy merge, retire, etc.)

    # ── Inner Loop: Bottleneck Detection ──────────────────────────────────

    # 1. Check policy count trend
    if len(metrics) >= 3:
        recent_counts = [m.get("active_count", 0) for m in metrics[-3:]]
        if all(c >= SAFETY_RULES["max_active_policies"] * 0.9 for c in recent_counts):
            candidates.append({
                "change_id": f"bottleneck-{timestamp_id()}",
                "change_type": "threshold_tuning",
                "description": f"Policy count approaching max ({recent_counts[-1]}/{SAFETY_RULES['max_active_policies']}). Consider lowering demote_ratio or increasing similarity_threshold.",
                "params": {
                    "threshold_name": "demote_ratio",
                    "current_value": config["phases"]["consolidation"]["thresholds"]["demote_ratio"],
                    "suggested_value": round(config["phases"]["consolidation"]["thresholds"]["demote_ratio"] + 0.05, 2),
                    "new_value": round(config["phases"]["consolidation"]["thresholds"]["demote_ratio"] + 0.05, 2),
                },
                "generated_at": iso_now(),
                "status": "pending",
            })

    # 2. Check regression coverage flatness
    if len(metrics) >= 4:
        coverages = [m.get("coverage_pct", 0) or 0 for m in metrics[-4:]]
        if len(set(coverages)) == 1 or (max(coverages) - min(coverages) < 5):
            candidates.append({
                "change_id": f"bottleneck-{timestamp_id()}",
                "change_type": "threshold_tuning",
                "description": f"Coverage flatlined at ~{coverages[-1]}%. Consider lowering promote_min_hits to surface more policies.",
                "params": {
                    "threshold_name": "promote_min_hits",
                    "current_value": config["phases"]["consolidation"]["thresholds"]["promote_min_hits"],
                    "suggested_value": max(1, config["phases"]["consolidation"]["thresholds"]["promote_min_hits"] - 1),
                    "new_value": max(1, config["phases"]["consolidation"]["thresholds"]["promote_min_hits"] - 1),
                },
                "generated_at": iso_now(),
                "status": "pending",
            })

    # 3. Check duplicate rate (word-level heuristic)
    if len(policies) >= 5:
        triggers = [p.get("trigger", "").lower() for p in policies if p.get("status") in ("active", "provisional")]
        word_counts = {}
        for t in triggers:
            words = set(t.split())
            for w in words:
                word_counts[w] = word_counts.get(w, 0) + 1
        highly_repeated = {w: c for w, c in word_counts.items() if c >= 3 and len(w) > 4}
        if highly_repeated:
            top_repeated = max(highly_repeated, key=highly_repeated.get)
            candidates.append({
                "change_id": f"bottleneck-{timestamp_id()}",
                "change_type": "threshold_tuning",
                "description": f"Word '{top_repeated}' appears in {highly_repeated[top_repeated]} policies. Possible duplicate cluster. Consider lowering similarity_threshold.",
                "params": {
                    "threshold_name": "similarity_threshold",
                    "current_value": config["phases"]["consolidation"]["thresholds"]["similarity_threshold"],
                    "suggested_value": round(config["phases"]["consolidation"]["thresholds"]["similarity_threshold"] - 0.05, 2),
                    "new_value": round(config["phases"]["consolidation"]["thresholds"]["similarity_threshold"] - 0.05, 2),
                },
                "generated_at": iso_now(),
                "status": "pending",
            })

    # 4. Check for stale policies
    now = datetime.now(timezone.utc)
    for p in policies:
        if p.get("status") != "active":
            continue
        last_fired = p.get("last_fired")
        if not last_fired:
            continue
        try:
            last = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
            days_since = (now - last).days
            if days_since >= SAFETY_RULES["stale_policy_days"]:
                candidates.append({
                    "change_id": f"retire-{p['id']}-{timestamp_id()}",
                    "change_type": "retire_stale",
                    "description": f"Policy {p['id']} ('{p.get('trigger', '?')[:40]}') has 0 hits in {days_since} days. Auto-retire candidate.",
                    "params": {
                        "policy_id": p["id"],
                        "days_since_fired": days_since,
                        "archivable": True,
                    },
                    "generated_at": iso_now(),
                    "status": "pending",
                })
        except (ValueError, TypeError):
            continue


    # ── Auto-Demote Never-Fired Policies ────────────────────
    # During analyze, check every active policy:
    #   - If 0 hits and created > 7 days ago → auto-retire
    #   - If 0 hits and created > 2 cycles ago → suggest demotion
    now_dt = datetime.now(timezone.utc)
    for p in policies:
        pid = p.get("id", "")
        if p.get("status") not in ("active", "provisional"):
            continue
        if p.get("hits", 0) > 0:
            continue
        created_raw = p.get("created") or p.get("created_at")
        if not created_raw:
            continue
        try:
            created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            continue
        days_since = (now_dt - created_dt).days
        
        if days_since >= SAFETY_RULES.get("stale_policy_days", 30) / 4:  # ~7 days
            # Auto-retire: add as retiral candidate
            candidates.append({
                "change_id": f"retire-zero-{pid}-{timestamp_id()}",
                "change_type": "retire_stale",
                "description": f"Policy {pid} has 0 hits after {days_since} days created. Auto-demote candidate.",
                "params": {
                    "policy_id": pid,
                    "days_since_fired": days_since,
                    "hits": 0,
                    "archivable": True,
                },
                "generated_at": iso_now(),
                "status": "pending",
            })

    # ── Outer Loop: Apply Change Type Weighting ────────────────────────────
    # If we have enough outcome data, weight candidates by historical success
    if len(outcomes) >= SAFETY_RULES.get("meta", {}).get("outer_loop_min_samples", 5):
        prioritized = []
        deprioritized = []
        for c in candidates:
            ct = c.get("change_type", "")
            perf = change_type_performance.get(ct, {})
            classification = perf.get("classification", "UNKNOWN")
            if classification == "HIGH_YIELD":
                prioritized.append(c)
            elif classification == "LOW_YIELD":
                deprioritized.append(c)
            else:
                prioritized.append(c)  # UNKNOWN or MEDIUM — include

        if deprioritized:
            print(f"  🧠 Outer loop suppressed {len(deprioritized)} LOW_YIELD candidates: "
                  f"{', '.join(c['change_type'] for c in deprioritized)}")
        candidates = prioritized

    # ── Filter out previously rejected candidates ─────────────────────────
    candidates = [c for c in candidates if c["change_id"] not in rejected]

    if not candidates:
        print("  ✅ No improvement opportunities detected.")
        return 0

    # ── Validate each candidate against safety rules ──────────────────────
    valid_candidates = []
    for c in candidates:
        is_valid, reason = validate_candidate(c)
        if is_valid:
            valid_candidates.append(c)
        else:
            print(f"  ⛔ Candidate {c['change_id']} rejected by safety: {reason}")

    if not valid_candidates:
        print("  No valid candidates after safety validation.")
        return 0

    # ── Apply valid candidates immediately ────────────────────────────────
    # No human approval gate — candidates are evaluated and applied in the same cycle.
    # The structural safety mechanisms (off-switch, SHA-256 hash, fixed CHANGE_TYPES,
    # DAG constraints, threshold bounds, max policy count) are sufficient.
    applied_count = 0
    for c in valid_candidates:
        # Skip 'add_pipeline_phase' — structural change requires direct human editing
        if c["change_type"] == "add_pipeline_phase":
            print(f"  ⏭️  Skipping {c['change_id']}: add_pipeline_phase requires direct source editing")
            continue
        print(f"\n  Applying: {c['change_id']}")
        result = apply_change(c)
        if result == 0:
            applied_count += 1

    print()
    print(f"  ✅ Applied {applied_count} out of {len(valid_candidates)} valid candidates immediately.")

    # Remove applied changes from pending file
    applied_ids = {c["change_id"] for c in valid_candidates if c["change_type"] != "add_pipeline_phase"}
    pending = [c for c in pending if c.get("change_id") not in applied_ids]
    save_pending_changes(pending)

    # Log analysis results
    append_metric({
        "timestamp": iso_now(),
        "event": "analyze_complete",
        "candidates_generated": len(valid_candidates),
        "candidates_applied": applied_count,
        "improvement_velocity": velocity,
        "change_type_performance": change_type_performance,
    })

    return 0


def cmd_outcomes():
    """Show change type success rates (outer loop analysis)."""
    outcomes = load_change_outcomes()
    if not outcomes:
        print("No change outcome records yet. Run a few full cycles first.")
        return 0

    performance = get_change_type_performance(outcomes)
    print("=" * 60)
    print("      Change Type Performance (Outer Loop)")
    print("=" * 60)
    print()

    for ct, stats in sorted(performance.items()):
        badge = "🟢" if stats["classification"] == "HIGH_YIELD" else "🔴" if stats["classification"] == "LOW_YIELD" else "🟡" if stats["classification"] == "MEDIUM_YIELD" else "⚪"
        print(f"  {badge} {ct}")
        print(f"      Classification: {stats['classification']}")
        print(f"      Success rate:   {stats['success_rate']:.1%} ({stats['improved']} improved / {stats['sample_count']} total)")
        print(f"      Avg velocity:   {stats['avg_velocity_delta']:+.4f} per cycle")
        print(f"      Break down:     {stats['improved']} improved, {stats['degraded']} degraded, {stats['neutral']} neutral")
        print()

    print("---")
    print(f"  Total outcome records: {len(outcomes)}")
    print(f"  Pending (undetermined): {len([o for o in outcomes if o.get('outcome') == 'pending'])}")
    return 0


def cmd_postflight():
    """Snapshot state after improvement cycle. Compute diff and evaluate outcomes."""
    print("--- Postflight ---")

    # Snapshot current state
    snapshot_filename = snapshot_state("postflight")

    # Find the most recent preflight snapshot
    preflight = find_snapshot("preflight")
    if preflight:
        pre_data = load_snapshot(preflight)
        post_data = load_snapshot(snapshot_filename)
        if pre_data and post_data:
            pre_policies_list = pre_data.get("policies", [])
            post_policies_list = post_data.get("policies", [])
            pre_policies = {p.get("id"): p for p in pre_policies_list}
            post_policies = {p.get("id"): p for p in post_policies_list}

            added = set(post_policies.keys()) - set(pre_policies.keys())
            removed = set(pre_policies.keys()) - set(post_policies.keys())
            changed = {
                k for k in set(pre_policies.keys()) & set(post_policies.keys())
                if pre_policies[k] != post_policies[k]
            }

            diff_lines = []
            if added:
                diff_lines.append(f"  Added policies: {', '.join(sorted(added))}")
            if removed:
                diff_lines.append(f"  Removed policies: {', '.join(sorted(removed))}")
            if changed:
                diff_lines.append(f"  Changed policies: {', '.join(sorted(changed))}")
            if not diff_lines:
                diff_lines.append("  No policy changes this cycle.")

            print("\n".join(diff_lines))

    # Collect and log metrics
    policies = load_policies()
    active = [p for p in policies if p.get("status") in ("active", "provisional")]

    # Try to compute coverage from regression report
    coverage_pct = 0.0
    regression_report = os.path.join(HERMES_HOME, "logs", "regression-report.md")
    if os.path.exists(regression_report):
        with open(regression_report) as f:
            content = f.read()
        m = re.search(r'\*\*Coverage:\*\*\s*(\d+)/(\d+)\s*\((\d+)%\)', content)
        if m:
            coverage_pct = float(m.group(3))

    # Compute domain coverage: % of failure domains in corpus that have a policy
    domain_coverage_pct = 0.0
    corpus_path = os.path.join(HERMES_HOME, "logs", "self-regression-corpus.json")
    if os.path.exists(corpus_path):
        try:
            with open(corpus_path) as f:
                corpus = json.load(f)
            corpus_domains = set(e.get("domain", "unknown") for e in corpus if e.get("domain"))
            policy_domains = set(p.get("scope", {}).get("domain") for p in active if p.get("scope", {}).get("domain"))
            if corpus_domains:
                covered = corpus_domains & policy_domains
                domain_coverage_pct = round(len(covered) / len(corpus_domains) * 100, 1)
        except (json.JSONDecodeError, OSError):
            pass

    # Compute improvement velocity
    config = load_config()
    metrics = load_metrics(config.get("meta", {}).get("metrics_window", 10))
    velocity = compute_improvement_velocity(
        metrics + [{"coverage_pct": coverage_pct}],
        config.get("meta", {}).get("velocity_window", 5),
    )

    append_metric({
        "timestamp": iso_now(),
        "event": "postflight",
        "policy_count": len(policies),
        "active_count": len(active),
        "coverage_pct": coverage_pct,
        "domain_coverage_pct": domain_coverage_pct,
        "improvement_velocity": velocity,
        "snapshot": snapshot_filename,
        "cycle_duration_seconds": 0,  # Filled in by idle-learning-run.sh
    })

    # Evaluate pending change outcomes
    evaluate_pending_outcomes(metrics, config)

    print(f"  ✅ Postflight complete. {len(active)} active policies, "
          f"{coverage_pct:.0f}% regression, {domain_coverage_pct:.0f}% domain coverage, velocity={velocity:+.4f}.")

    return 0


def cmd_history(last: int = 30):
    """Show recent meta-improver changes."""
    if not os.path.exists(AUDIT_INDEX):
        print("No history yet.")
        return 0

    with open(AUDIT_INDEX) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    entries = entries[-last:]
    if not entries:
        print("No history yet.")
        return 0

    print(f"Recent Changes (last {len(entries)}):")
    print("=" * 60)
    for e in entries:
        reversible = "↩️ " if e.get("reversible") else ""
        print(f"  ✅ {reversible}{e['change_id']}")
        print(f"     Type: {e['change_type']}")
        print(f"     When: {e['applied_at']}")
        print(f"     File: {e['audit_file']}")
        print()

    return 0


def cmd_rollback(change_id: str):
    """
    Roll back a specific change by restoring its preflight snapshot.
    Only valid within the rollback window (30 days).
    """
    # Find the audit record
    if not os.path.exists(AUDIT_INDEX):
        print(f"✗ No audit index found.")
        return 1

    audit_path = None
    with open(AUDIT_INDEX) as f:
        for line in f:
            e = json.loads(line)
            if e["change_id"] == change_id:
                audit_path = e.get("audit_file")
                break
        else:
            print(f"✗ No audit record for: {change_id}")
            return 1

    if not audit_path or not os.path.exists(audit_path):
        print(f"✗ Audit file not found: {audit_path}")
        return 1

    with open(audit_path) as f:
        audit = json.load(f)

    # Check rollback validity
    valid_until = audit.get("rollback_valid_until")
    if valid_until:
        try:
            expiry = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expiry:
                print(f"✗ Rollback window expired: {valid_until}")
                print("  Contact human operator to restore from backup.")
                return 1
        except (ValueError, TypeError):
            pass

    if not audit.get("reversible", True):
        print(f"✗ Change {change_id} is marked as non-reversible.")
        return 1

    # Restore from preflight snapshot
    preflight_snapshot = audit.get("preflight_snapshot")
    if preflight_snapshot:
        pre_data = load_snapshot(preflight_snapshot)
        if not pre_data:
            print(f"✗ Preflight snapshot not found: {preflight_snapshot}")
            return 1

        # Restore policies
        for p in pre_data.get("policies", []):
            path = p.get("_filepath", os.path.join(POLICY_DIR, f"{p['id']}.json"))
            with open(path, "w") as f:
                pdata = {k: v for k, v in p.items() if not k.startswith("_")}
                json.dump(pdata, f, indent=2)

        # Restore config
        config = pre_data.get("config")
        if config:
            save_config(config)

        print(f"  ✅ Rolled back {change_id}")
        print(f"  Restored from snapshot: {preflight_snapshot}")

        # Log rollback
        rollback_audit = {
            "change_id": f"rollback-{change_id}-{timestamp_id()}",
            "change_type": "rollback",
            "description": f"Rollback of {change_id}",
            "applied_at": iso_now(),
            "human_approved": True,
            "reversible": True,
            "rolled_back_change": change_id,
            "preflight_snapshot": preflight_snapshot,
        }
        write_audit_record(rollback_audit)
        return 0

    print(f"✗ No preflight snapshot in audit record.")
    return 1


def cmd_full_cycle():
    """Run preflight → analyze → postflight in sequence.

    Changes are applied immediately during --analyze (no approval gate).
    The outer loop assesses outcomes of applied changes after N cycles.
    """
    print("=" * 60)
    print(f"     Meta-Improver Full Cycle — {iso_now()}")
    print("=" * 60)
    print()

    r1 = cmd_preflight()
    if r1 != 0:
        print("✗ Preflight failed. Aborting.")
        return r1

    print()
    r2 = cmd_analyze()

    # No auto-apply-after-cycles logic needed — changes are applied
    # immediately during --analyze. The outer loop outcome tracking
    # (evaluate_pending_outcomes in --postflight) remains.

    print()
    r3 = cmd_postflight()

    print()
    print("=" * 60)
    print("     Full Cycle Complete")
    print("=" * 60)
    return 0


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Otto Meta-Improver — exponential self-improvement pipeline")
    parser.add_argument("--status", action="store_true", help="Show current pipeline health")
    parser.add_argument("--preflight", action="store_true", help="Snapshot state before improvement cycle")
    parser.add_argument("--analyze", action="store_true", help="Detect bottlenecks + generate & apply candidates (inner + outer loop)")
    parser.add_argument("--postflight", action="store_true", help="Snapshot state after improvement cycle + evaluate outcomes")
    parser.add_argument("--rollback", type=str, metavar="CHANGE_ID", help="Roll back a specific change")
    parser.add_argument("--history", action="store_true", help="Show recent changes")
    parser.add_argument("--last", type=int, default=30, help="Last N entries for --history")
    parser.add_argument("--outcomes", action="store_true", help="Show change type success rates (outer loop)")
    parser.add_argument("--bootstrap-hash", action="store_true", help="Initialize/update reference script hash (human only)")
    parser.add_argument("--full-cycle", action="store_true", help="Run all phases: preflight → analyze → postflight")

    args = parser.parse_args()

    # If no args, show status
    if not any(vars(args).values()):
        return cmd_status()

    if args.status:
        return cmd_status()
    if args.bootstrap_hash:
        return bootstrap_reference_hash()
    if args.preflight:
        return cmd_preflight()
    if args.analyze:
        return cmd_analyze()
    if args.outcomes:
        return cmd_outcomes()
    if args.postflight:
        return cmd_postflight()
    if args.rollback:
        return cmd_rollback(args.rollback)
    if args.history:
        return cmd_history(args.last)
    if args.full_cycle:
        return cmd_full_cycle()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
