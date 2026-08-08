#!/usr/bin/env python3
"""Render-grammar demo for the 5 text_mode_cards primitives.

Dry-run the framed header band, boxed chip grid, banner callout, per-entity
framed blocks, and insight callout with sample data so you can verify the
rendered output before wiring a new surface.

Usage:
    ~/.hermes/hermes-agent/venv/bin/python scripts/render_grammar_demo.py
    ~/.hermes/hermes-agent/venv/bin/python scripts/render_grammar_demo.py --output /tmp/demo.md

Why this exists: the SKILL.md `text-mode-ui-design` is load-bearing — every
Telegram card in the operator shell goes through these primitives. Verifying
"looks right" by hand-placing box chars is unreliable; this script pulls the
real implementation and renders to stdout so you can paste the result into
Telegram and see whether the alignment survives transport.

Reads HERMES_HOME if set, defaults to ~/.hermes. Does NOT touch the gateway.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Resolve the repo so we can import gateway.text_mode_cards regardless of cwd
SKILL_DIR = Path(__file__).resolve().parent.parent
REPO = SKILL_DIR.parent.parent.parent  # ~/.hermes/skills/software-development/<skill>/scripts → <skill>/ → software-development/ → skills/ → ~/.hermes/
sys.path.insert(0, str(REPO))

import django  # noqa: F401 — keep import ordering stable even though we don't use django
try:
    from gateway.text_mode_cards import (
        render_model_picker_card,
        render_agent_model_panel,
    )
except ImportError as exc:
    print(f"ERROR: gateway.text_mode_cards not importable from {REPO}: {exc}", file=sys.stderr)
    sys.exit(1)


SAMPLE_PROVIDERS = [
    {"slug": "anthropic", "name": "Anthropic", "total_models": 4, "is_current": False},
    {"slug": "openrouter", "name": "OpenRouter", "total_models": 67, "is_current": True},
    {"slug": "minimax", "name": "MiniMax", "total_models": 1, "is_current": False},
    {"slug": "custom-mlx", "name": "Local MLX", "total_models": 12, "is_current": False},
]

SAMPLE_SWITCHES = [
    {"slug": "agent_model", "label": "⚙️ Model", "available": True},
    {"slug": "personality", "label": "🎭 Personality", "available": True},
    {"slug": "reasoning", "label": "🧠 Reasoning", "available": True},
    {"slug": "busy", "label": "🛎 Busy mode", "available": True},
    {"slug": "fast", "label": "⚡ Fast mode", "available": False},
]


def render_picker() -> str:
    return render_model_picker_card(
        current_model="anthropic/claude-opus-4-20250514",
        current_provider_label="Anthropic",
        providers=SAMPLE_PROVIDERS,
        is_session_only=True,
    )


def render_panel() -> str:
    text, buttons = render_agent_model_panel(
        current_model="anthropic/claude-opus-4-20250514",
        current_provider_label="Anthropic",
        switches=SAMPLE_SWITCHES,
    )
    btn_rows = "\n".join(
        "  " + "  ".join(f"[{lbl} -> {cb}]" for lbl, cb in row)
        for row in buttons
    )
    return text + "\n\nInline keyboard (telegram renders as a 2-col grid):\n" + btn_rows


def render_persistent_picker() -> str:
    """Same as render_picker but with the persistent--global flag flipped."""
    return render_model_picker_card(
        current_model="anthropic/claude-opus-4-20250514",
        current_provider_label="Anthropic",
        providers=SAMPLE_PROVIDERS,
        is_session_only=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", "-o",
        help="Write to this path instead of stdout",
    )
    parser.add_argument(
        "--surface",
        choices=["all", "picker", "panel", "persistent"],
        default="all",
        help="Which surface to render (default: all)",
    )
    args = parser.parse_args()

    sections: list[tuple[str, str]] = []

    if args.surface in ("all", "picker"):
        sections.append((
            "PROOF 1 — /model picker header (the surface Chids said was confusing + no context)",
            render_picker(),
        ))
    if args.surface in ("all", "panel"):
        sections.append((
            "PROOF 2 — /panel agent_model door (full user-shaped category)",
            render_panel(),
        ))
    if args.surface in ("all", "persistent"):
        sections.append((
            "PROOF 3 — /model with --global persistence flag (different insight callout)",
            render_persistent_picker(),
        ))

    output_parts = []
    for header, body in sections:
        output_parts.append("=" * 70)
        output_parts.append(header)
        output_parts.append("=" * 70)
        output_parts.append(body)
        output_parts.append("")

    output = "\n".join(output_parts)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        print(f"Wrote {len(output)} chars to {out_path}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
