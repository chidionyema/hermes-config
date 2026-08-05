"""Compute the Slack `_SLACK_VIA_HERMES_ONLY` exclusion set.

Slack caps apps at 50 slash commands. When Hermes has more than ~50
gateway-available commands, Slack silently drops the lowest-priority
ones — which means the user-facing door (`/help`) might disappear.

This script:
1. Lists every gateway-available canonical command
2. Subtracts reserved Slack built-ins (e.g., /status, /me)
3. Subtracts the high-priority aliases (/hermes + /btw + /bg)
4. Prints the surplus: commands that need to be in `_SLACK_VIA_HERMES_ONLY`

The list it produces is what you paste into
``hermes_cli/commands.py:_SLACK_VIA_HERMES_ONLY``.

Always verify after editing:
    pytest tests/hermes_cli/test_commands.py::TestSlackNativeSlashes -v

Critical: `/help` MUST NOT appear in the output. If it does, the
Slack clamp is about to drop the user-facing entry point — exclude
a different low-priority command instead.
"""
from __future__ import annotations

import sys


# Reserved Slack built-ins (cannot be registered by apps)
# Source: https://slack.com/help/articles/201259356-Use-built-in-slash-commands
RESERVED: frozenset[str] = frozenset({
    "me", "status", "away", "dnd", "shrug", "remind", "msg", "feed",
    "who", "collapse", "expand", "leave", "join", "open", "search",
    "topic", "mute", "pro", "shortcuts",
})

# Hard cap on Slack native slash commands
MAX_SLASHES = 50


def compute_surplus(available: list[str]) -> list[str]:
    """Return commands that should be in ``_SLACK_VIA_HERMES_ONLY``.

    Args:
        available: Names of all gateway-available canonical commands.

    Returns:
        Sorted list of command names to exclude from Slack native
        (routed through ``/hermes <command>`` instead).
    """
    # Reserved commands are silently skipped — they count toward
    # the slack clamp but aren't user-reachable there. We still
    # subtract them so they don't trigger exclusion of others.
    candidates = [n for n in available if n not in RESERVED]

    # The /hermes catch-all reserves 1 slot.
    # Slack also recommends reserving 1-2 slots for high-priority
    # aliases that must survive the clamp.
    overhead = 1  # /hermes
    slots_remaining = MAX_SLASHES - overhead

    if len(candidates) <= slots_remaining:
        return []  # everything fits, no exclusions needed

    surplus_count = len(candidates) - slots_remaining
    # Sort candidates by priority (lowest first). The lowest-priority
    # ones get excluded. Caller adjusts the priority heuristic below.
    return sorted(candidates)[:surplus_count]


# Low-priority commands that should be excluded FIRST when Slack's
# cap is hit. Higher in this list = more important to KEEP native.
# Lower = more likely to be excluded.
LOW_PRIORITY: tuple[str, ...] = (
    "reload-skills",   # admin-only filesystem rescan
    "reload-mcp",      # admin-only MCP reload
    "codex-runtime",   # niche runtime toggle
    "statusbar",       # UI-only
    "indicator",       # UI-only
    "skin",            # UI-only
    "config",          # admin-only
    "tools",           # admin-only
    "toolsets",        # admin-only
    "platform",        # admin-only platform pause
    "restart",         # admin-only gateway restart
    "update",          # admin-only self-update
    "version",         # read-only version readout
    "insights",        # analytics, niche
    "usage",           # analytics, niche
    "credits",         # billing, niche
    "debug",           # log upload, niche
    "summary",         # text analysis, niche
    "commands",        # paginated browser (replaced by /help)
)


def compute_exclusion_list(available: list[str]) -> list[str]:
    """Compute the exact `_SLACK_VIA_HERMES_ONLY` set.

    Strategy: when the registry overflows Slack's 50-cap, exclude the
    lowest-priority commands first, until we fit. `/help` is NEVER
    excluded (asserted at the end).

    Args:
        available: Names of all gateway-available canonical commands.

    Returns:
        Sorted list of command names to add to `_SLACK_VIA_HERMES_ONLY`.

    Raises:
        RuntimeError: If `help` would need to be excluded to fit. The
            caller should remove a different command instead.
    """
    # Reserved commands count toward the Slack clamp (silently
    # skipped) but aren't reachable natively. Subtract from the
    # available pool.
    reachable = [n for n in available if n not in RESERVED]
    # /hermes reserves one slot. Slack also wants 1-2 slots for
    # priority aliases (/btw, /bg).
    overhead = 1
    slots_remaining = MAX_SLASHES - overhead

    if len(reachable) <= slots_remaining:
        return []

    surplus = len(reachable) - slots_remaining

    # Build exclusion list: lowest-priority first.
    available_set = set(reachable)
    exclusion: list[str] = []
    for cmd in LOW_PRIORITY:
        if surplus <= 0:
            break
        if cmd in available_set:
            exclusion.append(cmd)
            surplus -= 1

    # If we still have surplus, exclude any remaining commands
    # in alphabetical order (deterministic; reviewer can adjust).
    if surplus > 0:
        for cmd in sorted(available_set - set(exclusion)):
            if surplus <= 0:
                break
            if cmd in {"help"}:  # never exclude
                continue
            exclusion.append(cmd)
            surplus -= 1

    if "help" in exclusion:
        raise RuntimeError(
            "Slack cap pressure would exclude /help. "
            "Remove another command from LOW_PRIORITY."
        )

    return sorted(exclusion)


def main() -> int:
    """CLI entry point — reads available commands from stdin (one per line)."""
    if sys.stdin.isatty():
        print("Usage: compute-suggested-exclusion < available_commands.txt")
        print("Where available_commands.txt has one command name per line.")
        return 1
    available = [line.strip() for line in sys.stdin if line.strip()]
    exclusion = compute_exclusion_list(available)
    print("_SLACK_VIA_HERMES_ONLY = frozenset({")
    for cmd in exclusion:
        print(f'    "{cmd}",')
    print("})")
    return 0


if __name__ == "__main__":
    sys.exit(main())