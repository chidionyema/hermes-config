"""A capability that CANNOT run must not be graded as one that merely did not run.

The gap this pins: before 2026-08-19 every verdict in capability_audit.py answered "did it
produce?". When Hermes moved into a Linux container on 2026-08-17 it lost `claude`, `zsh`,
`node`, `launchctl` and every checkout under ~/Documents/code in one step, so fourteen
launchd capabilities and every tool-capable executor became unrunnable — and the audit
reported DARK, which points the diagnosis at the job instead of at the platform.

IMPOSSIBLE outranks DARK because it is the CAUSE of it.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))

import capability_audit as CA  # noqa: E402


def _cap(**over):
    cap = {"id": "t", "what": "w", "owner": "o", "period_s": 60,
           "observable": {"kind": "none"}}
    cap.update(over)
    return cap


def test_missing_binary_is_impossible_not_dark():
    reg = {"capabilities": [_cap(requires={"bins": ["a-binary-that-cannot-exist"]})]}
    rows = CA.audit_capabilities(reg, time.time())
    assert rows[0]["verdict"] == "IMPOSSIBLE", rows[0]
    assert "bin:a-binary-that-cannot-exist" in rows[0]["detail"]


def test_missing_path_and_env_are_named_individually():
    reg = {"capabilities": [_cap(requires={
        "paths": ["/nonexistent/checkout"],
        "env": ["A_VAR_NOBODY_SETS_HERE"],
    })]}
    rows = CA.audit_capabilities(reg, time.time())
    assert rows[0]["verdict"] == "IMPOSSIBLE"
    assert rows[0]["missing"] == ["path:/nonexistent/checkout", "env:A_VAR_NOBODY_SETS_HERE"]


def test_impossible_fails_the_audit():
    assert "IMPOSSIBLE" in CA.FAIL_VERDICTS


def test_a_capability_without_requires_is_graded_exactly_as_before():
    """The new check must be inert for every capability that does not opt in."""
    reg = {"capabilities": [_cap()]}
    rows = CA.audit_capabilities(reg, time.time())
    assert rows[0]["verdict"] == "UNPROVEN"   # observable kind "none", as before


def test_satisfied_requirements_do_not_shadow_the_real_verdict():
    """A requirement that IS met must fall through to the production grading."""
    reg = {"capabilities": [_cap(requires={"bins": ["sh"], "paths": [str(Path.home())]})]}
    rows = CA.audit_capabilities(reg, time.time())
    assert rows[0]["verdict"] == "UNPROVEN", rows[0]


def test_the_live_registry_declares_requirements_for_the_platform_bound_jobs():
    """Every launchd-owned capability is macOS-only and must say so.

    Without this, moving the estate to another platform silently turns them all DARK again.
    """
    import json
    reg = json.loads((Path.home() / ".hermes" / "capabilities.json").read_text())
    for cap in reg["capabilities"]:
        if str(cap.get("owner", "")).startswith("launchd:"):
            bins = (cap.get("requires") or {}).get("bins") or []
            assert "launchctl" in bins, f"{cap['id']} is launchd-owned but declares no launchctl"
