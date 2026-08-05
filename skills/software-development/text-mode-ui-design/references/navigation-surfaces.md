# Navigation Surfaces — Detailed Reference

Companion to the **Navigation Surfaces: The "Door" Pattern** section in
SKILL.md. This file captures the session-specific lessons from real
audit-and-fix work on the Hermes command directory.

## The Original Symptom (2026-08-02)

Founder complaint: *"I still don't know how the menu works and this is
concerning despite all the work that has been done in the repo today."*

Root cause: `gateway_help_lines()` returned **61 lines** of `` `cmd -- desc` ``
in registry order. `/panel` landed at position 22 looking no different from
`/rollback`. A code comment in `locales/en.yaml` (2026-07-31) had already
recorded the complaint verbatim:

> "how do i access the menu? is there one menu are there multiple menus?"

Someone had added `cockpit_hint` as a one-line door above the wall, but
the wall was 60 lines tall. The hint was visible; the door was named;
the user still couldn't see them.

## Why Developer Categories Don't Work

The `CommandDef.category` field had only 4 values actually used:

- `Session`: 23 commands (including `/status`, `/fleet`, `/panel`, `/approve` — none of which are session management)
- `Info`: 14 (including `/restart`, `/debug` — not info)
- `Configuration`: 11
- Stragglers: `search`, `pending`, `bp`, `connect`

These reflect code organization. Users think in verbs ("check status",
"approve", "switch model") not code modules.

## The Six User-Shaped Categories (Hermes-Specific)

Re-mapped for the 60+ command registry:

| Display | What goes here | Why |
|---|---|---|
| 🎛 Cockpit & Overview | `/panel`, `/brief`, `/status`, `/fleet`, `/inbox`, `/missions`, `/help`, `/commands`, `/summary`, `/usage`, `/insights` | Things users check first — the "home" group |
| ⚙️ Control & Approvals | `/stop`, `/approve`, `/deny`, `/yolo`, `/notify`, `/busy`, `/revert`, `/platform`, `/rollback` | Pause/resume, gating, dangerous actions |
| 🤖 Agent & Model | `/model`, `/personality`, `/fast`, `/reasoning`, `/verbose`, `/agents`, `/codex-runtime`, `/gquota`, `/credits` | Switch behavior, set parameters |
| 💬 Sessions & History | `/start`, `/new`, `/topic`, `/retry`, `/undo`, `/title`, `/branch`, `/compress`, `/background`, `/queue`, `/steer`, `/goal`, `/subgoal`, `/resume`, `/sessions` | Conversation-level operations |
| 📅 Schedule & Skills | `/cron`, `/blueprint`, `/suggestions`, `/memory`, `/skills`, `/bundles`, `/kanban`, `/curator` | Automation and capability discovery |
| 🛠 System & Setup | `/whoami`, `/profile`, `/sethome`, `/footer`, `/voice`, `/restart`, `/version`, `/debug`, `/update`, `/reload-mcp`, `/reload-skills`, `/config`, `/tools`, `/toolsets`, `/skin`, `/indicator`, `/statusbar` | System-level / admin |

Implementation lives at `hermes_cli/command_directory.py`:
- `_DISPLAY_GROUPS` — display order (matters — first is the "door" group)
- `_DISPLAY_GROUP_BY_NAME` — name-to-group map (defaults to "system")

## The Door Hint

```
🎛 Hermes Command Directory

👉 Start here: /panel — opens the cockpit (one card, every operation a tap)
   Aliases: /menu, /cockpit, /control, /mission
   Inside /panel, the 🔎 button searches every command by name — you rarely need the list below.
```

Three lines because users need ALL of:
1. What to type (`/panel`)
2. Other ways to type it (aliases)
3. Why they don't need to scroll (the 🔎 search inside)

## Tests That Caught Real Bugs

The 14 invariant tests in `tests/hermes_cli/test_command_directory.py`
caught three real problems during development:

1. **`test_every_user_facing_command_is_in_some_group`** — initial
   implementation missed `reload-skills` because I forgot to add it to
   `_DISPLAY_GROUP_BY_NAME`. Test caught it before commit.

2. **`test_total_commands_in_directory_matches_registry`** — caught
   a 51-vs-50 count mismatch when I forgot to mark `codex-runtime`
   as user-facing vs `cli_only`. The test asserted parity.

3. **`test_help_directory_puts_panel_first`** — caught an
   implementation where the door hint was the SECOND block (after the
   header), so users saw the title before the door. Fixed by
   prepending the door before any group headers.

## Slack-Specific Caveat: The 50-Slash Cap

Slack apps can register at most **50 slash commands**. Hermes has 60+
gateway-available commands. Slack's clamp silently drops whichever
command sorts last, breaking Telegram parity.

Solution: `_SLACK_VIA_HERMES_ONLY` — a frozenset of commands explicitly
routed through `/hermes <command>` on Slack only. They stay native on
Telegram, Discord, CLI, TUI.

**Critical rule:** `/help` MUST stay native on Slack. It's the user-facing
entry point. If Slack's clamp tries to drop it, exclude a *different*
low-priority command instead (`reload-skills`, `reload-mcp`,
`codex-runtime`, etc.).

The script `scripts/slack_via_hermes.py` automates this calculation.

## The "10x" Connection

This work was triggered by the same feedback pattern as the Summary
Card 10x visual upgrade: a correct but flat surface, no visual
hierarchy, no discoverability. Same fix shape: reframe the data, surface
the door, make the user-shaped hierarchy explicit. Same test shape:
invariants, not snapshots.

The skill captures both:
- `SKILL.md` → "The 5-Element Visual Grammar" (data cards)
- `SKILL.md` → "Navigation Surfaces: The Door Pattern" (menus/lists)

Both share: framed boundaries, emoji+bold section markers, banned
snapshot tests, invariant assertions.

## When to Re-Run This Audit

Re-audit when:
- More than 5 commands are added to the registry in a week
- A user reports "I didn't know X existed" (X is in the registry)
- The `_SLACK_VIA_HERMES_ONLY` set needs to grow (50-cap pressure)
- A new platform is added that needs command parity (Discord is already
  parity-safe, Slack needs the cap work, others TBD)