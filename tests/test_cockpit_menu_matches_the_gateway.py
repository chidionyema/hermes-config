"""The one-shot menu installer must not carry its own copy of the menu.

`scripts/set-cockpit-menu.py` writes a CHAT-SCOPED Telegram menu, and Telegram's
scope precedence (Chat > AllPrivateChats > Default) means it BEATS whatever the
gateway registers at boot. It carried its own list of twelve names, last edited
2026-08-06. Running it on 2026-08-19 would have silently removed the five
commands added since — `summary` among them, which the founder had asked for by
name that morning.

The class: a second copy of a list, in a script nobody runs often enough to
notice it has gone stale.
"""

import sys
from pathlib import Path

HERMES = Path.home() / ".hermes"
sys.path.insert(0, str(HERMES / "scripts"))
sys.path.insert(0, str(HERMES / "hermes-agent"))

import importlib.util  # noqa: E402

from gateway.operator_shell.menu import OPERATOR_TELEGRAM_MENU  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "set_cockpit_menu", HERMES / "scripts" / "set-cockpit-menu.py")
set_cockpit_menu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_cockpit_menu)


def test_the_installer_installs_exactly_the_gateway_menu():
    names = [name for name, _ in set_cockpit_menu.cockpit()]
    assert names == list(OPERATOR_TELEGRAM_MENU)


def test_summary_is_on_the_menu():
    """The founder asked for it by name on 2026-08-19."""
    assert "summary" in OPERATOR_TELEGRAM_MENU


def test_a_menu_name_with_no_description_is_a_hard_failure():
    """Silently dropping the row would remove the command from his chat."""
    import pytest
    saved = set_cockpit_menu.DESCRIPTIONS.pop("summary")
    try:
        with pytest.raises(SystemExit):
            set_cockpit_menu.cockpit()
    finally:
        set_cockpit_menu.DESCRIPTIONS["summary"] = saved


def test_no_description_is_left_over_for_a_command_that_is_gone():
    """A stale description is how the next stale list starts."""
    extra = set(set_cockpit_menu.DESCRIPTIONS) - set(OPERATOR_TELEGRAM_MENU)
    assert not extra, f"DESCRIPTIONS still names {sorted(extra)}, not on the menu"


def test_every_description_fits_telegram():
    for name, desc in set_cockpit_menu.cockpit():
        assert 1 <= len(desc) <= 256, f"{name}: Telegram rejects this description"
