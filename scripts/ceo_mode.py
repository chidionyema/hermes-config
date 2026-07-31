#!/usr/bin/env python3
"""ceo_mode — phone defaults to cards for ops; free chat still reaches the agent.

CEO mode (default): short noise / panel verbs → mission card; structured ops
(natural_ops, inbox, fleet, RSI, Otto tasks) stay deterministic. Substantive
freeform DMs reach the chat agent (silent mission-card-only was a dead UX).
Engineer mode: same, plus explicit `Otto engineer:` still forces agent.
"""
from __future__ import annotations

import os
from pathlib import Path

HERMES = Path(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")))


def mode() -> str:
    """Return 'ceo' | 'engineer'."""
    env = (os.getenv("OTTO_MODE") or os.getenv("HERMES_OTTO_MODE") or "").strip().lower()
    if env in ("ceo", "engineer"):
        return env
    try:
        import yaml
        cfg = yaml.safe_load((HERMES / "config.yaml").read_text()) or {}
        block = cfg.get("operator_shell") or {}
        m = str(block.get("mode") or "ceo").strip().lower()
        if m in ("ceo", "engineer"):
            return m
    except Exception:
        pass
    return "ceo"


def is_ceo() -> bool:
    return mode() == "ceo"


def engineer_trigger(text: str) -> bool:
    """True if message explicitly requests engineer/agent mode for this turn."""
    import re
    t = (text or "").strip()
    return bool(re.match(r"^\s*(otto[,:]?\s+)?(engineer|agent|debug)[,:]?\s+\S", t, re.I))


def is_ceo_pull(text: str) -> bool:
    """True for short status/ops pulls that must never burn an agent turn."""
    try:
        import sys
        agent = str(HERMES / "hermes-agent")
        if agent not in sys.path:
            sys.path.insert(0, agent)
        from gateway.operator_shell.natural_ops import match_natural_op
        return match_natural_op(text) is not None
    except Exception:
        return False
