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


# test_onboarding_template_exists was DELETED on 2026-08-19, not repaired.
#
# It asserted registry["onboarding"]["template"]["steps"] and ["risk_levels"]. Nothing has
# ever read those keys: the "From Template" button and its two siblings were removed on
# 2026-08-10 because there was no renderer, no handler and no template store behind any of
# them (see the comment in projects.render_onboarding). Adding the block to projects.json
# would have turned the test green while testing nothing at all.
#
# The rule that removal established — a button on the onboard panel must dispatch — is
# already enforced repo-wide, against real dispatch state rather than a copy of it, by
# hermes-agent/tests/gateway/operator_shell/test_every_button_dispatches.py. A second copy
# here would pin the same thing twice and let a future edit satisfy one while breaking the
# other.


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


def test_home_stays_bounded_when_the_registry_grows():
    """The live-registry test above only proves TODAY'S estate fits.

    Its verdict depends on how many projects happen to be registered on the machine running
    it, which is how this panel broke in the first place: it was written when 2 projects per
    row fitted, and it silently went to 9 rows the day the estate reached 10 active projects.
    This case pins the bound against a registry far larger than the real one, so the guard
    fails when the PACKING is wrong rather than when the founder registers one more project.
    """
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell import projects as P

    fake = [
        {"key": f"p{i}", "name": f"Project {i}", "type": "product",
         "status": "active", "risk": "low", "primary_repo": f"p{i}"}
        for i in range(40)
    ]
    real = P.get_active_projects
    real_reg = P.load_registry
    try:
        P.get_active_projects = lambda: [dict(p) for p in fake]
        P.load_registry = lambda: {"projects": [dict(p) for p in fake]}
        text, buttons = P.render_home()
    finally:
        P.get_active_projects = real
        P.load_registry = real_reg

    assert len(buttons) <= P.HOME_MAX_ROWS, f"{len(buttons)} rows with 40 projects"
    for row in buttons:
        assert len(row) <= P.HOME_ROW_WIDTH, f"row of {len(row)}"

    # Nothing may be dropped silently. 40 projects cannot all fit, so the overflow door has
    # to be on the panel — a bounded screen that just truncates is the defect, not the fix.
    callbacks = [cb for row in buttons for _, cb in row]
    assert "estate:projects_all" in callbacks, callbacks


def test_all_projects_panel_reaches_every_registered_project():
    """The overflow door must actually list everything Home could not show."""
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import render_all_projects, load_registry

    text, buttons = render_all_projects()
    callbacks = {cb for row in buttons for _, cb in row}
    for p in load_registry().get("projects", []):
        assert f"estate:project:{p['key']}" in callbacks, f"{p['key']} unreachable"


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
