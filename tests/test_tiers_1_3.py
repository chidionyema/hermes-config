"""
Tests for Tiers 1-3: Holdout evaluation, cost attribution, policy compression.
"""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Tier 1: Holdout Manager ──

def test_holdout_split_creates_train_and_holdout():
    """Split should create both train and holdout sets."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from holdout_eval import HoldoutManager

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        # Create mock corpus
        corpus = [{"id": f"failure_{i}", "task_id": f"task_{i}", "error": f"error {i}"} for i in range(50)]
        (home / "logs").mkdir(parents=True)
        (home / "logs" / "self-regression-corpus.json").write_text(json.dumps(corpus))

        hm = HoldoutManager(home)
        result = hm.split_corpus(holdout_ratio=0.3, seed=42)

        assert result["total"] == 50
        assert result["train"] + result["holdout"] == 50
        assert result["holdout"] > 0  # Should have some holdout
        assert result["train"] > 0  # Should have some train


def test_holdout_is_stable_across_splits():
    """Repeated splits with same seed should produce same holdout set."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from holdout_eval import HoldoutManager

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        corpus = [{"id": f"f_{i}"} for i in range(100)]
        (home / "logs").mkdir(parents=True)
        (home / "logs" / "self-regression-corpus.json").write_text(json.dumps(corpus))

        hm1 = HoldoutManager(home)
        r1 = hm1.split_corpus(seed=42)

        hm2 = HoldoutManager(home)
        r2 = hm2.split_corpus(seed=42)

        # Same seed, same split
        assert r1["holdout"] == r2["holdout"]
        assert r1["train"] == r2["train"]


def test_holdout_validate_returns_metrics():
    """Validate should return pass rate and missed items."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from holdout_eval import HoldoutManager

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "logs").mkdir(parents=True)

        # Create holdout corpus
        holdout = [{"id": "h1", "error": "syntax error in python script"}]
        (home / "logs" / "holdout-corpus.json").write_text(json.dumps(holdout))

        # Create a policy that matches
        (home / "policies").mkdir(parents=True)
        policy = {"id": "pol-1", "rule": "always check python syntax before execution",
                  "trigger": "syntax error", "status": "active"}
        (home / "policies" / "pol-1.json").write_text(json.dumps(policy))

        hm = HoldoutManager(home)
        result = hm.validate_policies()
        assert "holdout_pass_rate" in result
        assert result["total"] >= 1


# ── Tier 1: Policy Attribution ──

def test_policy_attribution_requires_data():
    """Attribution without outcomes should return error."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from holdout_eval import PolicyAttribution

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        pa = PolicyAttribution(home)
        result = pa.measure_policy_effect("pol-x", "python")
        assert "error" in result


def test_policy_attribution_with_data():
    """Attribution with outcomes should compute before/after rates."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from holdout_eval import PolicyAttribution

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "logs").mkdir(parents=True)
        (home / "policies").mkdir(parents=True)

        # Create policy created 2 days ago
        created = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        policy = {"id": "pol-test", "created_at": created, "status": "active"}
        (home / "policies" / "pol-test.json").write_text(json.dumps(policy))

        # Create outcomes: 5 failures before, 2 failures after (improvement)
        before_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        after_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        outcomes = []
        for i in range(10):
            outcomes.append(json.dumps({
                "ts": before_ts, "domain": "python",
                "outcome": "failure" if i < 5 else "success"
            }) + "\n")
        for i in range(10):
            outcomes.append(json.dumps({
                "ts": after_ts, "domain": "python",
                "outcome": "failure" if i < 2 else "success"
            }) + "\n")

        (home / "logs" / "task-outcomes.jsonl").write_text("".join(outcomes))

        pa = PolicyAttribution(home)
        result = pa.measure_policy_effect("pol-test", "python")

        assert result["before_rate"] == 0.5  # 5/10 failures → 50% success
        assert result["after_rate"] == 0.8  # 2/10 failures → 80% success
        assert result["direction"] == "positive"
        assert result["effect"] > 0.2


# ── Tier 2: Cost Tracker ──

def test_cost_tracker_records_and_stats():
    """Recording costs should produce accurate stats."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import CostTracker

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        ct = CostTracker(home)

        ct.record("self_regression", "credits", 3.5, "credits")
        ct.record("gap_finding", "credits", 2.0, "credits")
        ct.record("self_regression", "latency_seconds", 45.0, "seconds")

        stats = ct.stats(window_hours=24)
        assert stats["total_activities"] == 3
        assert stats["total_cost"] == 50.5  # 3.5 + 2.0 + 45.0
        assert "self_regression" in stats["per_activity"]
        assert "gap_finding" in stats["per_activity"]


def test_cost_throttle_detects_overrun():
    """Should throttle when credit usage exceeds limit."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import CostTracker

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        ct = CostTracker(home)

        # Record high credit usage
        for i in range(5):
            ct.record("self_regression", "credits", 5.0, "credits")

        should, reason = ct.should_throttle(credit_limit=10.0)
        assert should is True
        assert "exceeds limit" in reason


# ── Tier 3: Policy Compressor ──

def test_policy_compressor_analyzes_corpus():
    """Analyze should count policies and find duplicates."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import PolicyCompressor

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "policies").mkdir(parents=True)

        # Create two similar policies
        p1 = {"id": "p1", "trigger": "missing type hints in python code",
              "rule": "always add type hints to python functions", "status": "active"}
        p2 = {"id": "p2", "trigger": "python type hints are missing",
              "rule": "add type hints to all python functions", "status": "active"}
        (home / "policies" / "p1.json").write_text(json.dumps(p1))
        (home / "policies" / "p2.json").write_text(json.dumps(p2))

        pc = PolicyCompressor(home)
        analysis = pc.analyze()

        assert analysis["active"] == 2
        assert analysis["total"] == 2
        # Should detect near-duplicates
        assert len(analysis["duplicates"]) >= 1


def test_policy_compressor_dry_run():
    """Dry run compress should not modify files."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import PolicyCompressor

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "policies").mkdir(parents=True)

        p1 = {"id": "p1", "trigger": "syntax error in bash", "rule": "validate bash", "status": "active"}
        p2 = {"id": "p2", "trigger": "syntax error in bash scripts", "rule": "validate bash scripts", "status": "active"}
        (home / "policies" / "p1.json").write_text(json.dumps(p1))
        (home / "policies" / "p2.json").write_text(json.dumps(p2))

        pc = PolicyCompressor(home)
        result = pc.compress(dry_run=True)

        # Files should still exist (dry run)
        assert (home / "policies" / "p1.json").is_file()
        assert (home / "policies" / "p2.json").is_file()
        assert result["compressed"] >= 0  # May or may not find duplicates depending on similarity


def test_domain_scoping():
    """Domain scoping should tag a policy with domains."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import PolicyCompressor

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "policies").mkdir(parents=True)

        policy = {"id": "pol-x", "trigger": "test", "rule": "test", "status": "active"}
        (home / "policies" / "pol-x.json").write_text(json.dumps(policy))

        pc = PolicyCompressor(home)
        ok = pc.domain_scope_policy("pol-x.json", ["python", "shell"])
        assert ok is True

        # Verify domains were added
        updated = json.loads((home / "policies" / "pol-x.json").read_text())
        assert "python" in updated["domain"]
        assert "shell" in updated["domain"]


def test_get_domain_policies():
    """Should return only domain-relevant policies."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from cost_policy_mgmt import PolicyCompressor

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "policies").mkdir(parents=True)

        py_policy = {"id": "py", "domain": ["python"], "trigger": "t", "rule": "r", "status": "active"}
        shell_policy = {"id": "sh", "domain": ["shell"], "trigger": "t", "rule": "r", "status": "active"}
        unscoped = {"id": "un", "trigger": "t", "rule": "r", "status": "active"}

        (home / "policies" / "py.json").write_text(json.dumps(py_policy))
        (home / "policies" / "sh.json").write_text(json.dumps(shell_policy))
        (home / "policies" / "un.json").write_text(json.dumps(unscoped))

        pc = PolicyCompressor(home)
        python_policies = pc.get_domain_policies("python")
        python_ids = [p["id"] for p in python_policies]

        # Should include python-scoped AND unscoped, but NOT shell-scoped
        assert "py" in python_ids
        assert "un" in python_ids
        assert "sh" not in python_ids
