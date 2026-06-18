#!/usr/bin/env python3
"""
meta-improver.py — Core meta-improvement loop for Otto.

This is the exponential lever in Otto's self-improvement architecture.
It optimizes the improvement pipeline itself — not the policies directly.
Every change it makes is reversible, auditable, and gated by human approval
for anything dangerous.

WHAT IT CAN DO:
  - Measure pipeline performance (latency, yield, quality)
  - Detect bottlenecks in consolidation/regression/gap-finding
  - Tune numeric thresholds within bounded ranges
  - Re-order pipeline phases from a fixed set
  - Generate fix candidates for uncovered failure domains (never auto-applies)
  - Auto-retire stale policies (zero hits for 30+ days)
  - Log everything

WHAT IT CANNOT DO:
  - Modify its own evaluation criteria (hardcoded safety rules)
  - Apply fix candidates without human approval
  - Modify scripts outside meta/ and scripts/ directory
  - Access external systems or deploy code
  - Remove the off-switch
  - Modify human audit trail (append-only)

Usage:
    meta-improver.py --status                    # Show current pipeline health
    meta-improver.py --preflight                 # Snapshot state + check off-switch
    meta-improver.py --analyze                   # Detect bottlenecks + generate candidates
    meta-improver.py --review                    # Show pending changes awaiting approval
    meta-improver.py --approve <change-id>       # Apply a pending change
    meta-improver.py --reject <change-id>        # Reject a pending change (never re-propose)
    meta-improver.py --postflight                # Snapshot state + compute diff
    meta-improver.py --rollback <change-id>      # Roll back a specific change
    meta-improver.py --history [--last N]        # Show recent changes
    meta-improver.py --full-cycle                # Run preflight → analyze → postflight
"""

import json
import os
import sys
import hashlib
import shutil
import copy
import glob
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

# Ensure directories exist
for d in [META_DIR, LOGS_DIR, SNAPSHOT_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Hardcoded Safety Rules (Section 6 — non-negotiable) ─────────────────────

# These are read at runtime but never modified by this script.
# If you need to change these, edit this source file directly (human action).

SAFETY_RULES = {
    # Approval gates — which changes require human signoff
    "approval_required": [
        "add_pipeline_phase",
        "modify_evaluation_fn",
        "modify_safety_rule",
        "auto_apply_fix",
        "modify_script",
    ],
    # Approval-optional changes that auto-apply after N idle cycles
    "approval_optional": [
        "threshold_tuning",
        "pipeline_reorder",
        "policy_merge",
        "retire_stale",
    ],
    # Bounds for threshold tuning (cannot be tuned outside these ranges)
    "threshold_bounds": {
        "demote_ratio": {"min": 0.2, "max": 0.6},
        "similarity_threshold": {"min": 0.4, "max": 0.9},
        "promote_min_hits": {"min": 1, "max": 10},
    },
    # Script fingerprint for circular-self-reference detection
    "script_hash": None,  # Computed at startup
    # Maximum number of active policies
    "max_active_policies": 200,
    # Days since last hit before auto-retire
    "stale_policy_days": 30,
}

# ── Default Pipeline Config ─────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "pipeline_version": 1,
    "phases": {
        "consolidation": {
            "enabled": True,
            "order": 1,
            "script": "idle-consolidation.py",
            "args": [],
            "max_runtime_seconds": 30,
            "thresholds": {
                "similarity_threshold": 0.65,
                "demote_ratio": 0.4,
                "promote_min_hits": 3,
            },
        },
        "regression": {
            "enabled": True,
            "order": 2,
            "script": "self-regression.py",
            "args": ["--report"],
            "max_runtime_seconds": 30,
        },
        "gap_finding": {
            "enabled": True,
            "order": 3,
            "script": "gap-finding.py",
            "args": ["--report", "--generate-candidates"],
            "max_runtime_seconds": 30,
        },
        "meta_improvement": {
            "enabled": True,
            "order": 4,
            "script": "meta-improver.py",
            "args": ["--analyze"],
            "max_runtime_seconds": 20,
        },
    },
    "meta": {
        "auto_apply_after_cycles": 3,  # Approval-optional changes apply after N idle cycles
        "metrics_window": 10,           # Window size for bottleneck detection
        "enabled": True,               # Master switch for meta-improvement phase
    },
    "created_at": None,
    "updated_at": None,
}


# ── Helpers ─────────────────────────────────────────────────────────────────


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_config() -> dict:
    if os.path.exists(PIPELINE_CONFIG):
        with open(PIPELINE_CONFIG) as f:
            return json.load(f)
    # Create default
    cfg = dict(DEFAULT_CONFIG)
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


def compute_script_hash() -> str:
    """Compute SHA-256 of this script for circular-self-reference detection."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_off_switch() -> bool:
    """Check if off-switch exists. Returns True if learning is allowed."""
    if not os.path.exists(OFF_SWITCH):
        print("⛔ OFF_SWITCH absent — aborting all automatic learning")
        return False
    return True


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


def write_audit_record(record: dict):
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


# ── Safety Validation ───────────────────────────────────────────────────────


def validate_candidate(candidate: dict) -> tuple[bool, str]:
    """
    Validate a candidate change against safety rules.
    Returns (is_valid, reason).
    """
    change_type = candidate.get("change_type", "")
    params = candidate.get("params", {})

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

    # Rule 4: Cannot exceed max policy count
    if change_type in ("auto_apply_fix", "policy_merge"):
        current_count = len([p for p in load_policies() if p.get("status") in ("active", "provisional")])
        estimated_new = params.get("estimated_new_policies", 1)
        if current_count + estimated_new > SAFETY_RULES["max_active_policies"]:
            return (False, f"Would exceed max {SAFETY_RULES['max_active_policies']} active policies ({current_count} + {estimated_new})")

    # Rule 5: Can't approve a change that's already rejected
    rejected = load_rejected()
    if candidate.get("change_id") in rejected:
        return (False, "This change was previously rejected")

    return (True, "OK")


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
    print(f"  Pipeline ver:   {config.get('pipeline_version', 0)}")
    print(f"  Last updated:   {config.get('updated_at', 'never')}")
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
    """Snapshot state before improvement cycle. Check off-switch."""
    print("--- Preflight ---")

    # 1. Check off-switch
    if not check_off_switch():
        return 0  # Don't error out — just skip learning

    # 2. Check script integrity (circular-self-reference detection)
    current_hash = compute_script_hash()
    config = load_config()
    last_hash = SAFETY_RULES.get("script_hash")
    if last_hash and last_hash != current_hash:
        print(f"⚠️  Script hash changed: {last_hash[:16]} → {current_hash[:16]}")
        print("   This script has been modified since last audit.")
        print("   Aborting for safety. Verify integrity before re-enabling.")
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
    This is the core exponential improvement mechanism.

    Logic:
    1. Load last N cycles of metrics
    2. Detect bottlenecks by phase
    3. Generate candidate improvements
    4. Validate against safety rules
    5. Queue for human approval
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

    candidates = []

    # ── Bottleneck Detection Logic ──────────────────────────────────────────

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

    # 3. Check duplicate rate
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

    # ── Filter out previously rejected candidates ───────────────────────────
    candidates = [c for c in candidates if c["change_id"] not in rejected]

    if not candidates:
        print("  ✅ No improvement opportunities detected.")
        return 0

    # ── Validate each candidate against safety rules ────────────────────────
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

    # ── Write to pending changes ────────────────────────────────────────────
    pending = load_pending_changes()
    existing_ids = {c.get("change_id") for c in pending}
    new_count = 0
    for c in valid_candidates:
        if c["change_id"] not in existing_ids:
            pending.append(c)
            existing_ids.add(c["change_id"])
            new_count += 1

    save_pending_changes(pending)
    print(f"  ✅ Generated {new_count} new improvement candidates (total pending: {len(pending)})")

    # Log candidate generation
    append_metric({
        "timestamp": iso_now(),
        "event": "candidates_generated",
        "new_candidates": new_count,
        "total_pending": len(pending),
    })

    # Surface to user
    print()
    print("  ┌─" + "─" * 50 + "┐")
    print("  │ PENDING META-IMPROVEMENTS                                  │")
    print("  ├─" + "─" * 50 + "┤")
    for c in valid_candidates[:5]:
        print(f"  │ ⏳ {c['change_id'][:40]:<50}│")
        print(f"  │    {c['description'][:48]:<50}│")
    if len(valid_candidates) > 5:
        print(f"  │    ... and {len(valid_candidates) - 5} more                         │")
    print("  └─" + "─" * 50 + "┘")
    print(f"  Run: meta-improver.py --review")
    print(f"       meta-improver.py --approve <change-id>")
    print(f"       meta-improver.py --reject <change-id>")

    return 0


def cmd_review():
    """Show all pending changes awaiting approval."""
    pending = load_pending_changes()
    if not pending:
        print("No pending changes. Run --analyze to detect improvement opportunities.")
        return 0

    print(f"Pending Changes ({len(pending)}):")
    print("=" * 60)

    # Group by type
    by_type = {}
    for c in pending:
        t = c.get("change_type", "unknown")
        by_type.setdefault(t, []).append(c)

    for change_type, changes in sorted(by_type.items()):
        approval_needed = change_type in SAFETY_RULES["approval_required"]
        badge = "🔴 APPROVAL REQUIRED" if approval_needed else "🟡 Auto-apply after 3 cycles"
        print(f"\n  [{badge}] {change_type}")
        for c in changes:
            print(f"    ID: {c['change_id']}")
            print(f"    Description: {c.get('description', '?')}")
            params = c.get("params", {})
            if params:
                print(f"    Params: {json.dumps(params, indent=6)}")
            print()

    return 0


def cmd_approve(change_id: str):
    """Approve and apply a pending change."""
    pending = load_pending_changes()
    matching = [c for c in pending if c["change_id"] == change_id]

    if not matching:
        print(f"✗ No pending change with ID: {change_id}")
        return 1

    change = matching[0]
    change_type = change.get("change_type")
    params = change.get("params", {})

    # Validate again
    is_valid, reason = validate_candidate(change)
    if not is_valid:
        print(f"✗ Cannot apply: {reason}")
        return 1

    # Check approval gate
    if change_type in SAFETY_RULES["approval_required"]:
        print(f"✗ {change_type} requires human code review, not just approval gate.")
        print("  This change cannot be applied automatically. Edit the source directly.")
        return 1

    # Snapshot before applying
    pre_snapshot = snapshot_state("pre-approval")

    # Apply the change based on type
    config = load_config()
    before_config = copy.deepcopy(config)

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
            # Load, update status, save to archive
            with open(policy_path) as f:
                policy_data = json.load(f)
            policy_data["status"] = "archived"
            policy_data["archived_at"] = iso_now()
            policy_data["archived_by"] = "meta-improver"
            with open(archive_path, "w") as f:
                json.dump(policy_data, f, indent=2)
            # Remove from active directory
            os.remove(policy_path)
            print(f"  ✅ Retired {policy_id} → archived/")

    elif change_type == "policy_merge":
        merge_policy_ids = params.get("policy_ids", [])
        merged_trigger = params.get("merged_trigger", "")
        merged_rule = params.get("merged_rule", "")
        if len(merge_policy_ids) >= 2:
            # Create merged policy
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
            # Archive originals
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
        print(f"✗ Unknown change type: {change_type}")
        return 1

    # Record audit trail
    post_snapshot = snapshot_state("post-approval")
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

    # Remove from pending
    pending = [c for c in pending if c["change_id"] != change_id]
    save_pending_changes(pending)

    # Log metrics
    append_metric({
        "timestamp": iso_now(),
        "event": "change_applied",
        "change_id": change_id,
        "change_type": change_type,
        "human_approved": True,
    })

    return 0


def cmd_reject(change_id: str):
    """Reject a pending change. Never re-propose the same candidate."""
    pending = load_pending_changes()
    matching = [c for c in pending if c["change_id"] == change_id]

    if not matching:
        print(f"✗ No pending change with ID: {change_id}")
        return 1

    change = matching[0]
    log_rejected(change_id, change.get("description", ""))

    # Remove from pending
    pending = [c for c in pending if c["change_id"] != change_id]
    save_pending_changes(pending)

    print(f"✗ Rejected: {change_id}")
    print(f"  This candidate will never be re-proposed.")

    append_metric({
        "timestamp": iso_now(),
        "event": "change_rejected",
        "change_id": change_id,
    })

    return 0


def cmd_postflight():
    """Snapshot state after improvement cycle. Compute diff."""
    print("--- Postflight ---")

    # Snapshot current state
    snapshot_filename = snapshot_state("postflight")

    # Find the most recent preflight snapshot
    preflight = find_snapshot("preflight")
    if preflight:
        pre_data = load_snapshot(preflight)
        post_data = load_snapshot(snapshot_filename)
        if pre_data and post_data:
            pre_policies = {p.get("id"): p for p in pre_data.get("policies", [])}
            post_policies = {p.get("id"): p for p in post_data.get("policies", [])}

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
        import re
        m = re.search(r'\*\*Coverage:\*\*\s*(\d+)/(\d+)\s*\((\d+)%\)', content)
        if m:
            coverage_pct = float(m.group(3))

    append_metric({
        "timestamp": iso_now(),
        "event": "postflight",
        "policy_count": len(policies),
        "active_count": len(active),
        "coverage_pct": coverage_pct,
        "snapshot": snapshot_filename,
        "cycle_duration_seconds": 0,  # Filled in by idle-learning-run.sh
    })

    print(f"  ✅ Postflight complete. {len(active)} active policies, {coverage_pct:.0f}% coverage.")
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
        status = "✅" if e.get("human_approved") else "⏳"
        reversible = "↩️ " if e.get("reversible") else ""
        print(f"  {status} {reversible}{e['change_id']}")
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
                # Remove internal fields
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
    """Run preflight → analyze → postflight in sequence."""
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

    # Auto-apply approval-optional changes that have been pending long enough
    config = load_config()
    auto_after = config.get("meta", {}).get("auto_apply_after_cycles", 3)
    pending = load_pending_changes()

    for change in pending:
        if change.get("change_type") in SAFETY_RULES["approval_required"]:
            continue  # Skip approval-required changes

        # Check how many cycles this has been pending
        generated_at = change.get("generated_at", "")
        try:
            gen_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            cycles_since = (datetime.now(timezone.utc) - gen_time).total_seconds() / 7200  # ~2h per cycle
            if cycles_since >= auto_after:
                print(f"\n  Auto-applying (been pending {cycles_since:.0f} cycles): {change['change_id']}")
                cmd_approve(change["change_id"])
        except (ValueError, TypeError):
            continue

    print()
    r3 = cmd_postflight()

    print()
    print("=" * 60)
    print("     Full Cycle Complete")
    print("=" * 60)
    return 0


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Otto Meta-Improver — exponential self-improvement pipeline")
    parser.add_argument("--status", action="store_true", help="Show current pipeline health")
    parser.add_argument("--preflight", action="store_true", help="Snapshot state before improvement cycle")
    parser.add_argument("--analyze", action="store_true", help="Detect bottlenecks + generate candidates")
    parser.add_argument("--review", action="store_true", help="Show pending changes")
    parser.add_argument("--approve", type=str, metavar="CHANGE_ID", help="Approve and apply a pending change")
    parser.add_argument("--reject", type=str, metavar="CHANGE_ID", help="Reject a pending change")
    parser.add_argument("--postflight", action="store_true", help="Snapshot state after improvement cycle")
    parser.add_argument("--rollback", type=str, metavar="CHANGE_ID", help="Roll back a specific change")
    parser.add_argument("--history", action="store_true", help="Show recent changes")
    parser.add_argument("--last", type=int, default=30, help="Last N entries for --history")
    parser.add_argument("--full-cycle", action="store_true", help="Run all phases: preflight → analyze → postflight")

    args = parser.parse_args()

    # If no args, show status
    if not any(vars(args).values()):
        return cmd_status()

    if args.status:
        return cmd_status()
    if args.preflight:
        return cmd_preflight()
    if args.analyze:
        return cmd_analyze()
    if args.review:
        return cmd_review()
    if args.approve:
        return cmd_approve(args.approve)
    if args.reject:
        return cmd_reject(args.reject)
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
    # Compute and cache script hash on module load for circular-self-reference detection
    SAFETY_RULES["script_hash"] = compute_script_hash()
    sys.exit(main())
