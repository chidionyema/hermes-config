#!/usr/bin/env python3
"""
improver-switcher.py — Improver versioning and swap tracking.

Records the current meta-improver state before any swap, provides
versioning for the improvement pipeline, and maintains the
improver-versions.jsonl log.

Usage:
    python3 improver-switcher.py --record     # Record current state snapshot
    python3 improver-switcher.py --history    # Show version history
    python3 improver-switcher.py --status     # Show current improver state
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
VERSIONS_LOG = HERMES_HOME / "meta" / "improver-versions.jsonl"
METRICS_FILE = HERMES_HOME / "meta" / "metrics.jsonl"
REFERENCE_HASH = HERMES_HOME / "meta" / "reference-script-hash.json"
PIPELINE_CONFIG = HERMES_HOME / "meta" / "pipeline-config.json"
CHANGE_OUTCOMES = HERMES_HOME / "meta" / "change-outcomes.jsonl"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_hash(path: str) -> str:
    """Compute SHA-256 of a file."""
    p = Path(path).expanduser()
    if not p.exists():
        return "FILE_NOT_FOUND"
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_latest_metrics(n: int = 10) -> dict | None:
    """Get the most recent metrics entry."""
    entries = load_jsonl(METRICS_FILE)
    if not entries:
        return None
    return entries[-1]


def compute_improvement_velocity(entries: list[dict], window: int = 5) -> float:
    """Compute improvement velocity from recent metrics."""
    if len(entries) < 2:
        return 0.0
    relevant = entries[-window:] if len(entries) >= window else entries
    coverages = [m.get("coverage_pct", 0) or 0 for m in relevant]
    if len(coverages) < 2:
        return 0.0
    delta = coverages[-1] - coverages[0]
    cycles = len(coverages) - 1
    return round(delta / cycles, 4) if cycles > 0 else 0.0


def eval_prompt_hash() -> str:
    """Hash the eval prompt and reflection logic to track version changes."""
    paths = [
        HERMES_HOME / "scripts" / "reflect-on-correction.py",
        HERMES_HOME / "scripts" / "self-regression.py",
        HERMES_HOME / "scripts" / "gap-finding.py",
    ]
    combined = ""
    for p in paths:
        if p.exists():
            combined += p.read_text()
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def record_state(version: str = "current"):
    """Record the current improver state to improver-versions.jsonl."""
    metrics = load_jsonl(METRICS_FILE)
    velocity_before = compute_improvement_velocity(metrics)

    # Read reference hash
    ref_hash = ""
    if REFERENCE_HASH.exists():
        try:
            with open(REFERENCE_HASH) as f:
                ref_data = json.load(f)
                ref_hash = ref_data.get("sha256", "")
        except (json.JSONDecodeError, OSError):
            pass

    # Read pipeline config version
    config_ver = 0
    if PIPELINE_CONFIG.exists():
        try:
            with open(PIPELINE_CONFIG) as f:
                cfg = json.load(f)
                config_ver = cfg.get("pipeline_version", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # Read change outcomes
    outcomes = load_jsonl(CHANGE_OUTCOMES)
    successful_changes = sum(1 for o in outcomes if o.get("outcome") == "improved")

    entry = {
        "timestamp": iso_now(),
        "version": version,
        "meta_improver_hash": file_hash(str(HERMES_HOME / "scripts" / "meta-improver.py"))[:16],
        "eval_prompt_hash": eval_prompt_hash(),
        "pipeline_config_version": config_ver,
        "improvement_velocity_before": velocity_before,
        "total_changes_applied": len(outcomes),
        "successful_changes": successful_changes,
        "policy_count": len(list(HERMES_HOME.joinpath("policies").glob("pol-*.json"))),
        "script_paths": {
            "meta_improver": str(HERMES_HOME / "scripts" / "meta-improver.py"),
            "self_regression": str(HERMES_HOME / "scripts" / "self-regression.py"),
            "gap_finding": str(HERMES_HOME / "scripts" / "gap-finding.py"),
            "consolidation": str(HERMES_HOME / "scripts" / "idle-consolidation.py"),
            "policy_composer": str(HERMES_HOME / "scripts" / "policy-composer.py"),
            "outcome_evaluator": str(HERMES_HOME / "scripts" / "outcome-evaluator.py"),
        },
        "reference_hash_ref": ref_hash[:16],
    }

    os.makedirs(VERSIONS_LOG.parent, exist_ok=True)
    with open(VERSIONS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"✅ Version recorded: {version} at {iso_now()}")
    print(f"   Script hash: {entry['meta_improver_hash']}...")
    print(f"   Eval prompt hash: {entry['eval_prompt_hash']}...")
    print(f"   Velocity: {velocity_before}")
    return entry


def cmd_record():
    """Record current state snapshot."""
    print("=== Improver Version Recording ===")
    print()
    record_state(version="v1")
    return 0


def cmd_history():
    """Show version history from improver-versions.jsonl."""
    print("=== Improver Version History ===")
    print()

    versions = load_jsonl(VERSIONS_LOG)
    if not versions:
        print("  No version history yet.")
        return 0

    print(f"  {'Timestamp':<22} {'Version':<10} {'Hash':<18} {'Velocity':<10} {'Changes':<8}")
    print("  " + "-" * 70)
    for v in versions:
        ts = v.get("timestamp", "?")[:19]
        ver = v.get("version", "?")
        hsh = v.get("meta_improver_hash", "?")
        vel = v.get("improvement_velocity_before", 0)
        chg = v.get("total_changes_applied", 0)
        print(f"  {ts:<22} {ver:<10} {hsh:<18} {vel:<10.4f} {chg:<8}")

    print()
    print(f"  Total records: {len(versions)}")
    return 0


def cmd_status():
    """Show current improver state and status."""
    print("=== Improver Status ===")
    print()

    metrics = load_jsonl(METRICS_FILE)
    velocity = compute_improvement_velocity(metrics)
    last_metric = load_latest_metrics()

    print(f"  Improvement velocity: {velocity:+.4f} coverage_pct/cycle")
    if last_metric:
        print(f"  Last cycle: {last_metric.get('timestamp', '?')[:19]}")
        print(f"  Coverage: {last_metric.get('coverage_pct', '?')}%")
        print(f"  Policy count: {last_metric.get('policy_count', '?')}")

    outcomes = load_jsonl(CHANGE_OUTCOMES)
    print(f"  Total changes: {len(outcomes)}")
    improved = sum(1 for o in outcomes if o.get("outcome") == "improved")
    degraded = sum(1 for o in outcomes if o.get("outcome") == "degraded")
    print(f"  Improved: {improved}, Degraded: {degraded}")

    print()
    print(f"  Meta-improver hash: {file_hash(str(HERMES_HOME / 'scripts' / 'meta-improver.py'))[:16]}...")
    print(f"  Reference hash: ", end="")
    if REFERENCE_HASH.exists():
        try:
            with open(REFERENCE_HASH) as f:
                rd = json.load(f)
            print(f"{rd.get('sha256', '?')[:16]}...")
            print(f"  Recorded at: {rd.get('recorded_at', '?')}")
        except (json.JSONDecodeError, OSError):
            print("CORRUPT")
    else:
        print("NOT FOUND")

    versions = load_jsonl(VERSIONS_LOG)
    print(f"  Version history: {len(versions)} records")
    if versions:
        latest = versions[-1]
        print(f"  Latest version: {latest.get('version', '?')} at {latest.get('timestamp', '?')[:19]}")

    # Check off-switch
    off_switch = HERMES_HOME / "meta" / "OFF_SWITCH"
    print(f"  Off-switch: {'✅ PRESENT' if off_switch.exists() else '⛔ MISSING'}")

    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Improver Versioning System")
    parser.add_argument("--record", action="store_true", help="Record current state")
    parser.add_argument("--history", action="store_true", help="Show version history")
    parser.add_argument("--status", action="store_true", help="Show current improver state")

    args = parser.parse_args()

    if args.record:
        sys.exit(cmd_record())
    elif args.history:
        sys.exit(cmd_history())
    elif args.status:
        sys.exit(cmd_status())
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    main()
