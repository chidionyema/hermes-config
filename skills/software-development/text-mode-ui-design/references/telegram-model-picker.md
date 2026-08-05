# Telegram `/model` + `/panel` Agent & Model — Implementation Reference

Companion to the **5-Element Visual Grammar** in SKILL.md. Captures the
session-specific work of redesigning the existing `/model` Telegram picker
header and adding a `/panel` "🤖 Agent & Model" user-shaped category.

Use this when the user complains about the `/model` Telegram surface
("confusing and no context", "can be improved by 10x") or asks to add a
behavior-switch door to `/panel`.

## Original Symptom (2026-08-05)

Founder reaction to the existing `/model` header:

> "This is not great experience, confusing and no context"

The header that produced this reaction, rendered raw exactly as the bot
sends it:

```
⚙ *Model Configuration*

Current model: `anthropic/claude-opus-4-20250514`
Provider: Anthropic

Select a provider:
```

Five lines of dead prose. No framing, no chip grid, no per-entity blocks,
no context (session-scoped vs `--global`, provider count, what switching
*does*). The textbook spreadsheet-correct-with-no-hierarchy failure mode
the SKILL.md 5-Element Grammar outlaws.

## The Diagnosis That Saved The Build

Before redesigning, run this check to learn what to keep:

1. **Does the capability already exist?** Search for the slash command
   in `gateway/slash_commands.py` and the picker in
   `gateway/platforms/telegram.py` (search for `send_model_picker`).
   For `/model`: confirmed at `slash_commands.py:1291` with the inline
   comment in `gateway/operator_shell/brain.py` — *"`/model opus`
   already worked from Telegram"*. **The machinery is fine; the
   presentation is the bug.** This is almost always the case for
   established commands — don't re-build, re-frame.

2. **What callbacks are sacred?** The keyboard `mp:` / `mm:` / `mg:` /
   `mb:` / `mx:` prefixes are the routing contract with
   `_handle_model_picker_callback` (around `telegram.py:3673`). Any
   redesign must keep those callbacks untouched — only the visible
   text changes.

3. **What test assertions constrain the redesign?** Existing test in
   `tests/gateway/test_telegram_model_picker.py` asserts that
   `provider\_one` (escaped) and `` `model_1` `` (backtick-wrapped) must
   appear in `sent["text"]`. The redesign must preserve both: the
   escaped provider label and the backtick-wrapped current model. Put
   them inside the `text` fenced block so they survive Telegram's
   monospace rendering.

## File:Line Map For This Class Of Fix

| File | What lives there | Lines to study before editing |
|---|---|---|
| `gateway/platforms/telegram.py` | `send_model_picker`, `_build_provider_keyboard`, `_build_model_keyboard`, `_handle_model_picker_callback` | 3509–3800 |
| `gateway/slash_commands.py` | `/model` slash handler + model-switching completion | 1291, 1336–1429, 3928–4010 |
| `gateway/operator_shell/estate.py` | `_dispatch`, `PanelView`, `handle_estate_action` | 38–80, 150–249, 269–340 |
| `gateway/operator_shell/cockpit.py` | Established operator-shell module pattern | 1–80 (for conventions) |
| `gateway/operator_shell/panel_chrome.py` | Helpers: `nav`, `compose`, `Group`, `panel_stamp` | the whole file |
| `hermes_cli/commands.py` | `CommandDef` registry | 127, 146, 154 (panel/model/personality) |
| `hermes_cli/command_directory.py` | Six user-shaped categories including 🤖 Agent & Model | the whole file (see `references/navigation-surfaces.md`) |
| `gateway/run.py` | Dispatch chain — `if canonical == "panel":` is the template | ~7737 |

## The Redesigned `/model` Header Layout

Drop-in replacement for the flat 5-line header. Width budget: **42 chars
inner** (Telegram monospace render window, conservative for narrow
phones).

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚙️  M O D E L   P I C K E R
   Tap a provider to drill in → models
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

╔═══════ NOW RUNNING ══════════════════════╗
║  🧠 `claude-opus-4-20250514`
║  via Anthropic · 200K context · $15/$75
╚═══════════════════════════════════════════╝

┌── 📡 4 PROVIDERS · 47 MODELS ────────────┐
│  Tap one below to switch
└──────────────────────────────────────────┘

╭─ ✓ Anthropic  ·  12 models  ·  CURRENT ──╮
│  claude-opus-4-20250514  ✓ active
╰──────────────────────────────────────────╯

╭─ OpenAI  ·  8 models  ──────────────────╮
│  tap to drill in →
╰──────────────────────────────────────────╯

╭─ MiniMax  ·  5 models  ────────────────╮
│  via custom provider · M3 family
╰──────────────────────────────────────────╯

╭─ Gemini  ·  22 models  ───────────────╮
│  free tier · 1M context
╰──────────────────────────────────────────╯

> ⚠️ Switches are **session-scoped**. For a
> persistent change use `/model <name> --global`
> (writes to `~/.hermes/config.yaml`).
```

Five primitives in order: **framed header band** → **boxed chip grid**
(current) → **banner callout** (provider count) → **per-entity framed
blocks** (one per provider) → **blockquote insight** (persistence hint).

The keyboard layout (`_build_provider_keyboard`) is preserved verbatim —
same `mp:` / `mpg:` / `mm:` / `mb:` / `mx:` callbacks, same pagination,
same group folding for Kimi/Moonshot/MiniMax/xAI Grok families.

## The New `/panel` "🤖 Agent & Model" Group

When extending `/panel`, the new dispatch lives in
`gateway/operator_shell/estate.py` `_dispatch` (around line 269). The
template is the existing `brain` / `tune` / `missions` branches — pure
read until a button is tapped, so no idempotency sensitivity. Returns a
`PanelView` with the same 5-element grammar.

The panel text uses the established `panel_chrome` helpers (`nav`,
`compose`, `Group`, `panel_stamp`) for navigation rows, but the body
sections use the box-drawing chars directly — the helpers don't render
the 5-element grammar.

Wire it across four files:

1. **`estate.py`** — add `_dispatch` branch for `action == "agent_model"`
2. **`slash_commands.py`** — add `_handle_agent_model_command` next to
   `_handle_panel_command` (line 3931) and wire into the dispatch table
3. **`hermes_cli/commands.py`** — add `CommandDef("agent_model", ...)`
   and to `ACTIVE_SESSION_BYPASS_COMMANDS` (line 376)
4. **`gateway/run.py`** — add `if canonical == "agent_model":` chain
   next to the existing `panel` chain (~line 7737)

## Test Invariants (NOT Format Strings)

The skill's `SKILL.md` "Behavior contracts over snapshots" rule applies
twice as hard here. Format-string tests break every redesign. Use these
invariants in `tests/gateway/platforms/test_telegram_model_picker.py`
(new file) and the operator_shell suite:

```python
# Redesigned /model header invariants
assert "━━━━━━━━━━━━" in rendered       # framed band present
assert "╔" in rendered and "╚" in rendered  # boxed chip grid
assert current_model in rendered        # never hide the active model
assert provider_label in rendered       # never hide the active provider
assert rendered.count("╭─") >= len(providers)  # one block per provider
assert "session-scoped" in rendered.lower()   # persistence hint always visible

# Agent & Model panel invariants
assert "/model" in rendered
assert "🤖" in rendered
assert any("◀" in label or "back" in label.lower() for label, _ in buttons)
```

## The Lane Guard Reality

`gateway/` is in Claude's single-writer lane — pre-commit hook at
`.git/hooks/pre-commit:45` enforces `HERMES_LANE=claude` for any commit
touching `gateway/`, `scripts/coordinator.py`, `config.yaml`, or
`plugins/otto-inbound/`. The guard exists because concurrent edits
crash-looped the gateway twice.

For Otto (this agent) the practical implication:

- You **cannot** edit + commit `gateway/` directly. The commit will be
  rejected even with a perfect, syntax-clean change.
- You **can** edit it locally for design verification (read with
  `read_file`, do dry-run renders, do anything that doesn't `git add`).
- The actual edit + commit must go through Claude with
  `HERMES_LANE=claude git commit`. Plan the delegation budget: budget
  ~25 tool-call iterations for the actual write phase, not 50.
  Investigation is Otto's job; Claude's job is the write.

## Subagent Drop-Loop Pattern (2026-08-05 Lesson)

Claude ran 50/50 iterations reading without writing. The user profile
hard rule: *after 3rd narrative on same failure, stop. Never 4th
admission.* When dispatching Claude for gateway edits:

1. **Otto pre-investigates.** Read the files yourself, produce the
   punch list, hand it to Claude as `context`.
2. **Tell Claude the budget is the write phase, not investigation.**
   "Do not re-read files I've already described. Begin writing
   immediately."
3. **Require a verifiable receipt.** `git log -1 --oneline`,
   `git diff --stat HEAD~1`, `pytest` output, and a dry-run render of
   the new text. Not a narrative summary.
4. **If Claude drops, do not re-dispatch with the same context.** Ship
   a tighter context with the punch list more fully spelled out, or
   ask the user for a one-time lane override (`HERMES_LANE=claude`
   passed explicitly).

## When To Re-Run This Work

- User reports the `/model` header is "flat" / "confusing" / "no context"
- A new behavior-switch command (`/reasoning`, `/fast`, `/verbose`) is
  added and needs a `/panel` entry
- The provider list grows >10 entries and the chip grid needs re-pagination
- The existing test in `tests/gateway/test_telegram_model_picker.py`
  becomes a format-string snapshot — replace it with the invariants
  above