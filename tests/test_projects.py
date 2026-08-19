"""Tests for project registry and new Home panel."""

import json
import tempfile
from pathlib import Path


def test_the_estate_is_prospector_and_hermes():
    """The registry pins WHICH projects are active, not HOW MANY.

    This test used to assert `len(active) >= 6`, which pinned the roster: it made shrinking
    the estate a test failure, and it passed happily while five of those six named repos did
    not exist on the machine the agent runs on. Founder, 2026-08-19: "hermes agent thinks the
    estate is every folder in code, should understand its just prospector and hermes agent".
    Assert that, and assert the property that actually matters — an active project must have
    something to work on.
    """
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import get_active_projects, get_project

    active = {p["key"] for p in get_active_projects()}
    assert active == {"prospector", "hermes-agent"}, sorted(active)

    for key in sorted(active):
        p = get_project(key)
        assert p is not None, key
        assert p["status"] == "active"
        assert p.get("objectives"), f"{key} is active with no objective"

    # An archived project must carry no live objective: every panel renders `objectives` as
    # "what we are doing about it", so a stale one reads as work in flight that nobody filed.
    from gateway.operator_shell.projects import get_archived_projects
    for p in get_archived_projects():
        assert not p.get("objectives"), f"archived {p['key']} still has an objective"

    p = get_project("prospector")
    assert p["name"] == "Prospector"
    assert p["type"] == "product"



def test_an_active_project_points_at_a_real_checkout():
    """An active row must name a repo that exists, and archived rows must not run.

    Measured 2026-08-19 over ~/.hermes/coordinator.db: of 121 coordinator tasks in 14
    days, 35 were filed against projects with no `repo` key and no directory on disk —
    portfolio-site (15), tie (6), ritualworks (5), haworks-platform (5), signalengine
    (4). They failed on arrival with titles like `repo-health: lux: not found` and
    `prospector repo missing at ...`, and every one of those failures then filed ANOTHER
    task, which is how a queue fills itself with work nobody can do.

    `scripts/coordinator.py::_project_repo` falls back to `~/Documents/code/<key>` for a
    row with no `repo`, so a missing path does not fail loudly — it invents a plausible
    one. This test is the thing that fails instead.
    """
    import os
    import sys
    sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
    from gateway.operator_shell.projects import get_active_projects

    for proj in get_active_projects():
        repo = os.path.expanduser(proj.get("repo") or "")
        assert repo, f"active project {proj['key']} names no repo"
        assert os.path.isdir(os.path.join(repo, ".git")), (
            f"active project {proj['key']} points at {repo!r}, which is not a git checkout"
        )


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

    from gateway.operator_shell.panel_chrome import nav

    text, buttons = render_home()
    assert len(buttons) <= 8, f"Home has {len(buttons)} button rows (max 8)"

    # The last row is the shared nav spine, and it is 6 or 7 buttons wide BY DESIGN
    # (panel_chrome.nav — "always last, always this order"). This loop used to run over it
    # with a max of 3 and a comment claiming Telegram allowed 3, which was wrong on both
    # counts; it never fired only because the row-count assert above failed first. Pin the
    # spine as itself, and hold the width rule where it means something: the panel's own rows.
    assert buttons[-1] == nav(), "last row is not the shared nav spine"
    for row in buttons[:-1]:
        assert len(row) <= 3, f"Button row has {len(row)} buttons (max 3 per row)"


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
    for row in buttons[:-1]:  # last row is the nav spine; see the note in the test above
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

    for key in ("prospector", "hermes-agent"):
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
