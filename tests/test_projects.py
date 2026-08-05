"""Tests for project registry and new Home panel."""

import json
import tempfile
from pathlib import Path


def test_registry_loads_all_active():
    """Registry should contain all active + incubating projects."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import get_active_projects, get_archived_projects, get_project

    active = get_active_projects()
    assert len(active) >= 6  # At minimum the 6 active products

    archived = get_archived_projects()
    assert len(archived) >= 3  # haworks-legacy, modeltrainer, vaults

    # Get specific project
    p = get_project("prospector")
    assert p is not None
    assert p["name"] == "Prospector"
    assert p["type"] == "product"
    assert p["status"] == "active"


def test_project_types_present():
    """All project types should be represented."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import load_registry

    reg = load_registry()
    types = {p.get("type") for p in reg["projects"]}
    assert "product" in types
    assert "client" in types
    assert "incubating" in types
    assert "archived" in types


def test_onboarding_template_exists():
    """Onboarding section should have required fields."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import load_registry

    reg = load_registry()
    onboarding = reg.get("onboarding", {})
    assert "template" in onboarding
    assert "steps" in onboarding["template"]
    assert len(onboarding["template"]["steps"]) >= 5
    assert "risk_levels" in onboarding


def test_render_home_buttons_under_limit():
    """Home panel should respect Telegram 8-button-row limit."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import render_home

    text, buttons = render_home()
    assert len(buttons) <= 8, f"Home has {len(buttons)} button rows (max 8)"
    # Nav spine rows can have 3 buttons per Telegram's layout
    for row in buttons:
        assert len(row) <= 3, f"Button row has {len(row)} buttons (max 3 per Telegram row)"


def test_render_project_dashboard():
    """Project dashboard should render for known projects."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import render_project_dashboard

    for key in ("prospector", "tie", "haworks-platform"):
        text, buttons = render_project_dashboard(key)
        assert len(text) > 50, f"Dashboard for {key} too short: {len(text)} chars"
        assert len(buttons) >= 2, f"Dashboard for {key} has only {len(buttons)} button rows"


def test_render_onboarding():
    """Onboarding wizard should render."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import render_onboarding

    text, buttons = render_onboarding()
    assert "Onboard" in text
    assert len(buttons) >= 2
