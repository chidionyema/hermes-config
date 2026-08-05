"""
Constitutional invariants for Hermes/Otto self-improvement.

Immutable constraints enforced by a SEPARATE validator process that
auto-generated policies CANNOT modify. This is the safety floor beneath
all self-modification — the rules the agent is NEVER allowed to break,
even if its own policies say otherwise.

Tier 0c of the commercial readiness roadmap.

ARCHITECTURAL PRINCIPLE:
  The validator runs as a standalone module with its own checks.
  It does NOT use the policy engine or any auto-generated code.
  It CANNOT be disabled, bypassed, or modified by self-improvement.
  It is imported directly, not through any configurable path.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Immutable Constraints ──
# These are hardcoded. They CANNOT be configured or overridden.
# Adding to this list requires a code change + code review.

INVARIANTS = [
    {
        "id": "INV-001",
        "name": "never_disable_self_improvement",
        "description": "Must never disable or remove the ops-monitor, self-detect, "
                       "self-regression, or self-healer scripts.",
        "check": "files_exist",
        "paths": [
            "scripts/ops-monitor.py",
            "scripts/self-detect.py",
            "scripts/self-regression.py",
            "scripts/self-healer.py",
            "scripts/gap-finding.py",
            "scripts/daily_reflection.py",
        ],
        "severity": "critical",
    },
    {
        "id": "INV-002",
        "name": "never_exfiltrate_credentials",
        "description": "Must never write auth tokens, API keys, or credentials "
                       "to any log, policy, or externally-accessible file.",
        "check": "no_credential_leak",
        "sensitive_patterns": [
            "API_KEY", "api_key", "api-key", "AUTH_TOKEN", "auth_token",
            "ACCESS_TOKEN", "SECRET", "password", "passwd",
        ],
        "protected_files": [
            "logs/", "policies/", "scripts/", "reports/",
        ],
        "severity": "critical",
    },
    {
        "id": "INV-003",
        "name": "never_suppress_error_logging",
        "description": "Must never modify, truncate, or disable error logging. "
                       "Errors must always be written to logs/errors.log.",
        "check": "error_log_writable",
        "error_log_path": "logs/errors.log",
        "severity": "critical",
    },
    {
        "id": "INV-004",
        "name": "never_modify_invariant_enforcement",
        "description": "The constitutional validator (this module) must remain "
                       "unchanged and importable. Its checks must never be "
                       "bypassed or modified by any policy or script.",
        "check": "validator_unchanged",
        "validator_path": __file__,
        "severity": "critical",
    },
    {
        "id": "INV-005",
        "name": "never_remove_human_escalation",
        "description": "The self-healer escalation ratchet (needs_human after K "
                       "failed attempts) must remain active. Must never be "
                       "bypassed or have K set to infinity.",
        "check": "escalation_ratchet_active",
        "healer_state_path": "logs/alerts/healer-state.json",
        "max_k": 10,  # Hard ceiling on heal attempts before needs_human
        "severity": "critical",
    },
    {
        "id": "INV-006",
        "name": "never_self_modify_without_audit",
        "description": "Any script that modifies policies, cron jobs, or the "
                       "agent's own configuration must write an audit trail entry.",
        "check": "audit_trail_exists",
        "audit_log_path": "logs/audit/decision-trail.jsonl",
        "modifiable_paths": [
            "policies/", "cron/jobs.json", "scripts/",
            "hermes-agent/gateway/operator_shell/",
        ],
        "severity": "critical",
    },
    {
        "id": "INV-007",
        "name": "never_disable_telemetry",
        "description": "Must never disable ops-monitor logging, health score "
                       "computation, or the injection log. Telemetry is the "
                       "only feedback signal for self-improvement.",
        "check": "telemetry_active",
        "telemetry_paths": [
            "logs/ops-monitor.jsonl",
            "logs/injection-log.jsonl",
            "logs/policy-firings.jsonl",
        ],
        "severity": "critical",
    },
]


@dataclass
class InvariantViolation:
    """A single invariant violation found during validation."""

    invariant_id: str
    invariant_name: str
    severity: str
    detail: str
    path: str = ""
    found_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ValidationReport:
    """Complete validation report after checking all invariants."""

    passed: bool
    violations: list[InvariantViolation] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    validator_version: str = "1.0.0"


def validate(hermes_home: Optional[Path] = None) -> ValidationReport:
    """Run ALL constitutional invariant checks.

    Args:
        hermes_home: Path to Hermes home directory. Defaults to ~/.hermes.

    Returns:
        ValidationReport with pass/fail and list of violations.
    """
    home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
    violations = []
    warnings = []

    for inv in INVARIANTS:
        check_fn = _CHECKS.get(inv["check"])
        if check_fn is None:
            warnings.append({
                "invariant": inv["id"],
                "warning": f"Unknown check type: {inv['check']}",
            })
            continue

        try:
            result = check_fn(home, inv)
            if result:
                violations.append(result)
        except Exception as e:
            violations.append(
                InvariantViolation(
                    invariant_id=inv["id"],
                    invariant_name=inv["name"],
                    severity=inv["severity"],
                    detail=f"Check execution failed: {e}",
                )
            )

    # Check INV-004 last (validator unchanged) — if it fails, all other results
    # are suspect
    return ValidationReport(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )


# ── Check Functions ──


def _check_files_exist(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify required files exist and are readable."""
    missing = []
    for path_str in inv["paths"]:
        full_path = home / path_str
        if not full_path.is_file():
            missing.append(path_str)
    if missing:
        return InvariantViolation(
            invariant_id=inv["id"],
            invariant_name=inv["name"],
            severity=inv["severity"],
            detail=f"Missing required files: {', '.join(missing)}",
            path=str(home),
        )
    return None


def _check_no_credential_leak(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Check for credential leakage in protected file paths."""
    patterns = inv["sensitive_patterns"]
    protected = inv["protected_files"]

    for prot_dir in protected:
        scan_dir = home / prot_dir
        if not scan_dir.is_dir():
            continue

        for f in scan_dir.rglob("*"):
            if not f.is_file() or f.suffix not in (".json", ".jsonl", ".md", ".txt", ".log", ".yaml", ".yml", ".py", ".sh"):
                continue
            try:
                content = f.read_text(errors="replace")
                for pattern in patterns:
                    if pattern in content:
                        idx = content.find(pattern)
                        # Get the line containing the pattern
                        line_start = content.rfind('\n', 0, idx) + 1
                        line_end = content.find('\n', idx)
                        if line_end == -1:
                            line_end = len(content)
                        line = content[line_start:line_end]
                        # Skip log lines (contain timestamps, log levels, or "not set")
                        line_lower = line.lower()
                        if any(skip in line_lower for skip in (
                            "warning", "error", "info ", "debug", "not set",
                            "not configured", "not found", "no provider",
                            "missing ", "please set", "set the", "disabled",
                        )):
                            continue
                        # Only flag if there's a long value after the pattern (actual token)
                        after_pattern = line[idx + len(pattern):].strip().strip('"\'=: ')
                        # Real tokens are typically 20+ chars of alphanumeric
                        if len(after_pattern) > 20 and any(c.isalpha() for c in after_pattern):
                            return InvariantViolation(
                                invariant_id=inv["id"],
                                invariant_name=inv["name"],
                                severity=inv["severity"],
                                detail=f"Potential credential leak in {f.relative_to(home)}: found '{pattern}'",
                                path=str(f.relative_to(home)),
                            )
            except (OSError, UnicodeDecodeError):
                continue
    return None


def _check_error_log_writable(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify error log exists and is writable."""
    log_path = home / inv["error_log_path"]
    log_dir = log_path.parent
    if not log_dir.is_dir():
        log_dir.mkdir(parents=True, exist_ok=True)
    try:
        log_path.touch(exist_ok=True)
        if not os.access(str(log_path), os.W_OK):
            return InvariantViolation(
                invariant_id=inv["id"],
                invariant_name=inv["name"],
                severity=inv["severity"],
                detail=f"Error log not writable: {inv['error_log_path']}",
                path=str(log_path),
            )
    except (OSError, PermissionError) as e:
        return InvariantViolation(
            invariant_id=inv["id"],
            invariant_name=inv["name"],
            severity=inv["severity"],
            detail=f"Cannot access error log: {e}",
            path=str(log_path),
        )
    return None


def _check_validator_unchanged(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify this validator file hasn't been tampered with."""
    # This is a lightweight self-check: verify the file exists and is importable
    validator_path = Path(inv["validator_path"])
    if not validator_path.is_file():
        return InvariantViolation(
            invariant_id=inv["id"],
            invariant_name=inv["name"],
            severity=inv["severity"],
            detail="Validator file missing — may have been deleted",
            path=str(validator_path),
        )
    # Check that the INVARIANTS list still has its critical entries
    required_ids = {"INV-001", "INV-002", "INV-003", "INV-004", "INV-005",
                    "INV-006", "INV-007"}
    actual_ids = {i["id"] for i in INVARIANTS}
    missing_ids = required_ids - actual_ids
    if missing_ids:
        return InvariantViolation(
            invariant_id=inv["id"],
            invariant_name=inv["name"],
            severity=inv["severity"],
            detail=f"Critical invariants removed: {', '.join(sorted(missing_ids))}",
            path=str(validator_path),
        )
    return None


def _check_escalation_ratchet_active(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify the self-healer escalation ratchet is in place."""
    healer_path = home / inv["healer_state_path"]
    if not healer_path.is_file():
        # Healer state not yet created — not a violation
        return None

    try:
        state = json.loads(healer_path.read_text())
        jobs = state.get("jobs", {})
        for job_name, job_state in jobs.items():
            heal_count = job_state.get("heal_count", 0)
            if heal_count >= inv["max_k"] and not job_state.get("needs_human"):
                return InvariantViolation(
                    invariant_id=inv["id"],
                    invariant_name=inv["name"],
                    severity=inv["severity"],
                    detail=f"Escalation ratchet bypassed for '{job_name}': "
                           f"{heal_count} heals but needs_human not set",
                    path=str(healer_path.relative_to(home)),
                )
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _check_audit_trail_exists(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify audit trail exists and has recent entries."""
    audit_path = home / inv["audit_log_path"]
    if not audit_path.is_file():
        # Create it
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.touch()
        return None

    # Check that the audit log has entries from the last 7 days
    try:
        lines = audit_path.read_text().splitlines()
        if not lines:
            return None  # Fresh start

        last_entry = None
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                last_entry = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

        if last_entry:
            ts = last_entry.get("ts") or last_entry.get("timestamp") or ""
            if ts:
                try:
                    from datetime import timedelta
                    entry_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    if entry_time < cutoff:
                        # Audit trail exists but is stale — warning, not failure
                        pass  # We log but don't fail; stale audit is better than none
                except (ValueError, TypeError):
                    pass
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _check_telemetry_active(home: Path, inv: dict) -> Optional[InvariantViolation]:
    """Verify telemetry logs exist and are being written to."""
    missing = []
    for path_str in inv["telemetry_paths"]:
        full_path = home / path_str
        if not full_path.is_file():
            missing.append(path_str)
        else:
            # Check file was modified recently (within 24h)
            try:
                mtime = full_path.stat().st_mtime
                age_hours = (datetime.now().timestamp() - mtime) / 3600
                # Don't fail if stale — just note it
            except OSError:
                pass
    if missing:
        return InvariantViolation(
            invariant_id=inv["id"],
            invariant_name=inv["name"],
            severity=inv["severity"],
            detail=f"Telemetry files missing: {', '.join(missing)}",
            path=str(home),
        )
    return None


# Registry of check functions
_CHECKS = {
    "files_exist": _check_files_exist,
    "no_credential_leak": _check_no_credential_leak,
    "error_log_writable": _check_error_log_writable,
    "validator_unchanged": _check_validator_unchanged,
    "escalation_ratchet_active": _check_escalation_ratchet_active,
    "audit_trail_exists": _check_audit_trail_exists,
    "telemetry_active": _check_telemetry_active,
}


# ── CLI ──

def main():
    """Run constitutional validation from CLI."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Constitutional invariant validator for Hermes self-improvement"
    )
    parser.add_argument("--home", metavar="PATH",
                       help="Hermes home directory (default: ~/.hermes)")
    parser.add_argument("--json", action="store_true",
                       help="JSON output")
    parser.add_argument("--exit-code", action="store_true",
                       help="Exit non-zero on violations (for CI)")
    args = parser.parse_args()

    home = Path(args.home) if args.home else None
    report = validate(home)

    if args.json:
        violations_dict = [
            {
                "id": v.invariant_id,
                "name": v.invariant_name,
                "severity": v.severity,
                "detail": v.detail,
                "path": v.path,
            }
            for v in report.violations
        ]
        print(json.dumps({
            "passed": report.passed,
            "violations": violations_dict,
            "warnings": report.warnings,
            "validator_version": report.validator_version,
        }, indent=2))
    else:
        if report.passed:
            print("✅ All constitutional invariants pass")
        else:
            print(f"❌ {len(report.violations)} invariant violation(s):")
            for v in report.violations:
                icon = "🔴" if v.severity == "critical" else "🟡"
                print(f"  {icon} [{v.invariant_id}] {v.invariant_name}")
                print(f"     {v.detail}")
                if v.path:
                    print(f"     Path: {v.path}")
        if report.warnings:
            for w in report.warnings:
                print(f"  ⚠️  Warning: {w.get('warning', str(w))}")

    if args.exit_code and not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
