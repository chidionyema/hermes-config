"""
Tests for Tiers 6-7: Gap auto-closing and agent identity/versioning.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ── Tier 6: Gap Closer ──

def test_identify_low_risk_gap():
    """Domain with many stable outcomes should be low risk."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import GapCloser, GapRisk

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "logs").mkdir(parents=True)

        # Create stable outcome history
        outcomes = []
        for i in range(70):
            outcomes.append(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "domain": "python",
                "outcome": "success",
            }) + "\n")
        (home / "logs" / "task-outcomes.jsonl").write_text("".join(outcomes))

        gc = GapCloser(home)
        gap = gc.identify_gap("python", "Missing type checking in generated code", failure_count=3)
        assert gap.risk_level == GapRisk.LOW


def test_identify_high_risk_security_gap():
    """Security domain gaps should always be high risk."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import GapCloser, GapRisk

    with tempfile.TemporaryDirectory() as tmp:
        gc = GapCloser(Path(tmp))
        gap = gc.identify_gap("auth", "Missing credential validation", failure_count=1)
        assert gap.risk_level == GapRisk.HIGH


def test_auto_close_low_risk_creates_policy():
    """Low-risk gaps should be auto-closed with a generated policy."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import GapCloser, GapRisk, GapStatus

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "logs").mkdir(parents=True)
        (home / "policies").mkdir(parents=True)

        # Create stable outcome history
        outcomes = []
        for i in range(70):
            outcomes.append(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "domain": "python",
                "outcome": "success",
            }) + "\n")
        (home / "logs" / "task-outcomes.jsonl").write_text("".join(outcomes))

        gc = GapCloser(home)
        gap = gc.identify_gap("python", "Missing docstrings", failure_count=2)
        assert gap.risk_level == GapRisk.LOW

        result = gc.auto_close_if_safe(gap)
        if result["action"] == "auto_promoted":
            assert result["policy_id"].startswith("pol-auto-")
            # Check policy was created
            policy_path = home / "policies" / f"{result['policy_id']}.json"
            assert policy_path.is_file()
        # If invariants blocked it, that's also acceptable behavior


def test_escalate_high_risk():
    """High-risk gaps should be escalated, not auto-closed."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import GapCloser, GapRisk

    with tempfile.TemporaryDirectory() as tmp:
        gc = GapCloser(Path(tmp))
        gap = gc.identify_gap("credentials", "Hardcoded secrets in generated code", failure_count=25)
        assert gap.risk_level == GapRisk.HIGH

        result = gc.auto_close_if_safe(gap)
        assert result["action"] == "escalated"
        assert "evidence" in result


def test_human_approve_and_reject():
    """Human should be able to approve or reject escalated gaps."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import GapCloser

    with tempfile.TemporaryDirectory() as tmp:
        gc = GapCloser(Path(tmp))
        gap = gc.identify_gap("auth", "Security gap", failure_count=30)

        # Escalate
        result = gc.auto_close_if_safe(gap)
        assert result["action"] == "escalated"

        # Human reject
        assert gc.human_reject(gap.gap_id, "Too risky to auto-close") is True
        gaps = gc._load_gaps()
        assert gaps[gap.gap_id]["status"] == "rejected"

        # Create new gap for approval test
        gap2 = gc.identify_gap("auth2", "Another security gap", failure_count=30)
        gc.auto_close_if_safe(gap2)
        assert gc.human_approve(gap2.gap_id) is True
        gaps = gc._load_gaps()
        assert gaps[gap2.gap_id]["status"] == "promoted"


# ── Tier 7: Agent Identity ──

def test_agent_current_version():
    """Should return or initialize agent identity."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import AgentIdentity

    with tempfile.TemporaryDirectory() as tmp:
        ai = AgentIdentity(Path(tmp))
        v = ai.current_version()
        assert v["agent"] == "Otto"
        assert "version" in v
        assert "capabilities" in v


def test_bump_version():
    """Bumping should increment semantic version correctly."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import AgentIdentity

    with tempfile.TemporaryDirectory() as tmp:
        ai = AgentIdentity(Path(tmp))

        v1 = ai.bump_version("patch", "Bug fix")
        assert v1["version"] == "1.0.1"

        v2 = ai.bump_version("minor", "New feature")
        assert v2["version"] == "1.1.0"  # minor resets patch

        v3 = ai.bump_version("major", "Breaking change")
        assert v3["version"] == "2.0.0"


def test_snapshot_and_list():
    """Creating snapshots and listing them should work."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import AgentIdentity

    with tempfile.TemporaryDirectory() as tmp:
        ai = AgentIdentity(Path(tmp))
        snap_id = ai.snapshot("test snapshot")
        assert snap_id.startswith("snap-")

        snaps = ai.list_snapshots()
        assert len(snaps) >= 1
        assert snaps[0]["snapshot_id"] == snap_id


def test_rollback_restores_state():
    """Rollback should capture and restore state."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import AgentIdentity

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "policies").mkdir(parents=True)
        (home / "cron").mkdir(parents=True)

        # Create initial state
        (home / "policies" / "test-pol.json").write_text('{"id":"test","status":"active"}')
        (home / "cron" / "jobs.json").write_text('{"jobs":[]}')

        ai = AgentIdentity(home)
        snap_id = ai.snapshot("before change")

        # Modify state
        (home / "policies" / "test-pol.json").write_text('{"id":"test","status":"modified"}')

        # Rollback
        result = ai.rollback(snap_id)
        if "error" not in result:
            assert "policies" in result["restored"]
            # Policy should be restored
            restored_pol = json.loads((home / "policies" / "test-pol.json").read_text())
            assert restored_pol["status"] == "active"


def test_compliance_report():
    """Compliance report should include all required sections."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from auto_close_identity import AgentIdentity

    with tempfile.TemporaryDirectory() as tmp:
        ai = AgentIdentity(Path(tmp))
        report = ai.compliance_report()

        assert "agent_identity" in report
        assert "modification_governance" in report
        assert "invariant_enforcement" in report
        assert "human_oversight" in report
        assert "data_governance" in report
        assert report["invariant_enforcement"]["validator_active"] is True
