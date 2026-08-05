#!/usr/bin/env python3
"""
integration.py — Wires all Tier 0-7 modules into the operational system.

Run this as a cron job or post-task hook. It:
1. Records task outcomes (if called with --task-outcome)
2. Runs constitutional validation (if called with --validate)
3. Updates health score snapshot
4. Triggers holdout evaluation (weekly)
5. Checks for distributional drift on active policies
6. Compresses policies (daily)
7. Auto-closes low-risk gaps

Usage:
  # Post-task hook
  python3 scripts/integration.py --task-outcome --task-id T1 --domain python --exit-code 0

  # Pre-modification safety gate
  python3 scripts/integration.py --validate --exit-code

  # Daily cron
  python3 scripts/integration.py --daily

  # Weekly cron  
  python3 scripts/integration.py --weekly
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SCRIPTS = HERMES_HOME / "scripts"


def record_task_outcome(task_id: str, domain: str, exit_code: int = 0,
                        stderr: str = "", duration: float = 0.0,
                        task_type: str = ""):
    """Record a task outcome after completion. Call after every task."""
    sys.path.insert(0, str(SCRIPTS))
    from outcome_tracker import OutcomeTracker

    tracker = OutcomeTracker(HERMES_HOME)
    outcome = tracker.auto_detect_outcome(
        task_id=task_id,
        domain=domain,
        exit_code=exit_code,
        stderr=stderr,
        duration=duration,
        task_type=task_type,
    )
    tracker.record(outcome)
    return outcome


def run_constitutional_check(exit_on_violation: bool = False) -> bool:
    """Run the constitutional validator. Returns True if all invariants pass."""
    sys.path.insert(0, str(SCRIPTS))
    from constitutional_validator import validate

    report = validate(HERMES_HOME)
    if not report.passed:
        for v in report.violations:
            print(f"⚠️  [{v.invariant_id}] {v.detail}", file=sys.stderr)
        if exit_on_violation:
            sys.exit(1)
    return report.passed


def daily_tasks():
    """Run daily self-improvement maintenance tasks."""
    print(f"=== Daily maintenance: {datetime.now(timezone.utc).isoformat()} ===")

    # 1. Constitutional check
    print("[1/6] Constitutional validation...")
    passed = run_constitutional_check(exit_on_violation=False)
    print(f"  {'✅' if passed else '❌'} Invariants {'OK' if passed else 'VIOLATED'}")

    # 2. Policy compression analysis
    print("[2/6] Policy compression...")
    sys.path.insert(0, str(SCRIPTS))
    from cost_policy_mgmt import PolicyCompressor
    pc = PolicyCompressor(HERMES_HOME)
    analysis = pc.analyze()
    print(f"  {analysis['active']} active policies (ceiling: {analysis['ceiling']})")
    if analysis["recommendations"]:
        for r in analysis["recommendations"]:
            print(f"  {'🔴' if r['severity']=='critical' else '🟡'} {r['message']}")

    # Only auto-compress if we're approaching ceiling
    if analysis["at_risk"]:
        result = pc.compress(dry_run=False)
        print(f"  Compressed: {result['compressed']} policies")

    # 3. Cost tracking
    print("[3/6] Cost tracking...")
    from cost_policy_mgmt import CostTracker
    ct = CostTracker(HERMES_HOME)
    stats = ct.stats(window_hours=24)
    print(f"  {stats['total_activities']} self-improvement activities in 24h")
    should_throttle, reason = ct.should_throttle(credit_limit=10.0)
    if should_throttle:
        print(f"  ⚠️  THROTTLE: {reason}")

    # 4. Health score snapshot
    print("[4/6] Health snapshot...")
    try:
        sys.path.insert(0, str(HERMES_HOME / "hermes-agent"))
        from gateway.operator_shell.otto_health import _save_daily_snapshot
        snap = _save_daily_snapshot()
        print(f"  Score: {snap['score']}")
    except Exception as e:
        print(f"  ⚠️  Health snapshot failed: {e}")

    # 5. Self-improvement loop closer (gap-finding + meta-improver + regression)
    print("[5/6] Self-improvement loop...")
    try:
        import subprocess as _sp
        r = _sp.run(
            [sys.executable, str(SCRIPTS / "self_improve_runner.py"), "--daily"],
            capture_output=True, text=True, timeout=120,
        )
        for line in (r.stdout + r.stderr).splitlines():
            if any(kw in line for kw in ("promoted", "shadow", "escalated", "Health:", "Complete", "Failed")):
                print(f"  {line.strip()[:120]}")
    except Exception as e:
        print(f"  ⚠️  Loop closer failed: {e}")

    # 6. Save agent snapshot (pre-modification baseline)
    print("[6/6] Agent snapshot...")
    from auto_close_identity import AgentIdentity
    ai = AgentIdentity(HERMES_HOME)
    snap_id = ai.snapshot(f"daily-{datetime.now(timezone.utc).strftime('%Y%m%d')}")
    print(f"  Snapshot: {snap_id}")

    # 6. Bump daily version
    ai.bump_version("patch", f"Daily maintenance snapshot")

    print("=== Daily maintenance complete ===\n")


def weekly_tasks():
    """Run weekly self-improvement maintenance tasks."""
    print(f"=== Weekly maintenance: {datetime.now(timezone.utc).isoformat()} ===")

    # 1. Holdout evaluation
    print("[1/4] Holdout evaluation...")
    sys.path.insert(0, str(SCRIPTS))
    from holdout_eval import HoldoutManager
    hm = HoldoutManager(HERMES_HOME)
    split_result = hm.split_corpus()
    print(f"  Corpus: {split_result['train']} train / {split_result['holdout']} holdout")
    validation = hm.validate_policies()
    if "holdout_pass_rate" in validation:
        print(f"  Holdout pass rate: {validation['holdout_pass_rate']:.1%}")

    # 2. Check for distributional drift on active policies
    print("[2/4] Drift check...")
    from quality_defense import DistributionalMonitor
    dm = DistributionalMonitor(HERMES_HOME)
    # Check policies that were deployed in the last 7 days
    policies_dir = HERMES_HOME / "policies"
    if policies_dir.is_dir():
        from datetime import timedelta
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        active_recent = []
        for f in policies_dir.glob("*.json"):
            try:
                p = json.loads(f.read_text())
                created = p.get("created_at") or p.get("created") or ""
                if created:
                    ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ct.tzinfo is None:
                        ct = ct.replace(tzinfo=timezone.utc)
                    if ct >= week_ago and p.get("status") == "active":
                        active_recent.append((p["id"], p.get("domain", ["unknown"])[0] if isinstance(p.get("domain"), list) else p.get("domain", "unknown")))
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                continue

        for pid, domain in active_recent[:5]:
            result = dm.auto_pause_if_drifting(pid, domain)
            if result["action"] != "ok":
                print(f"  ⚠️  {pid}: {result['action']} — {result['reason']}")

    # 3. Auto-close low-risk gaps that have enough shadow data
    print("[3/4] Gap evaluation...")
    from auto_close_identity import GapCloser, GapStatus
    gc = GapCloser(HERMES_HOME)
    gaps = gc._load_gaps()
    for gap_id, gap_data in gaps.items():
        if gap_data.get("status") == GapStatus.SHADOW.value:
            gap = gc.identify_gap.__self__  # Can't reconstruct easily from dict
            # Try to evaluate shadow
            try:
                from auto_close_identity import Gap, GapRisk, GapStatus as GS
                gap = Gap(
                    gap_id=gap_data["gap_id"],
                    domain=gap_data["domain"],
                    description=gap_data["description"],
                    severity=gap_data.get("severity", "warning"),
                    failure_count=gap_data.get("failure_count", 0),
                    risk_level=GapRisk(gap_data["risk_level"]),
                    status=GS(gap_data["status"]),
                )
                result = gc.evaluate_shadow(gap)
                if result["action"] in ("promoted", "escalated"):
                    print(f"  {gap_id}: {result['action']} — {result.get('reason', '')}")
            except Exception:
                pass

    # 4. Generate compliance report
    print("[4/4] Compliance report...")
    from auto_close_identity import AgentIdentity
    ai = AgentIdentity(HERMES_HOME)
    report = ai.compliance_report()
    report_path = HERMES_HOME / "reports" / "compliance.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Report: {report_path}")

    print("=== Weekly maintenance complete ===\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Hermes self-improvement integration runner"
    )
    parser.add_argument("--task-outcome", action="store_true",
                       help="Record a task outcome (post-task hook)")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--stderr", default="")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--task-type", default="")

    parser.add_argument("--validate", action="store_true",
                       help="Run constitutional validation")
    parser.add_argument("--exit-on-violation", action="store_true",
                       help="Exit non-zero on invariant violation")

    parser.add_argument("--daily", action="store_true",
                       help="Run daily maintenance tasks")
    parser.add_argument("--weekly", action="store_true",
                       help="Run weekly maintenance tasks")
    parser.add_argument("--all", action="store_true",
                       help="Run all maintenance (daily + weekly checks)")

    args = parser.parse_args()

    if args.task_outcome:
        outcome = record_task_outcome(
            task_id=args.task_id or f"task-{datetime.now(timezone.utc).timestamp():.0f}",
            domain=args.domain or "unknown",
            exit_code=args.exit_code,
            stderr=args.stderr,
            duration=args.duration,
            task_type=args.task_type,
        )
        print(f"Recorded: {outcome.task_id} → {outcome.outcome} "
              f"({outcome.domain}, confidence={outcome.confidence:.0%})")

    if args.validate:
        passed = run_constitutional_check(exit_on_violation=args.exit_on_violation)
        if not args.task_outcome and not args.daily and not args.weekly:
            print("✅ All invariants pass" if passed else "❌ Invariants violated")

    if args.daily or args.all:
        daily_tasks()

    if args.weekly or args.all:
        weekly_tasks()


if __name__ == "__main__":
    main()
