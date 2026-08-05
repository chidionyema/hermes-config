---
name: text-mode-ui-design
description: Design visually rich text-mode interfaces — Telegram/Slack/Discord cards, terminal reports, Markdown reports, console dashboards, and any other surface where the medium is monospace + Unicode box-drawing characters + Markdown syntax, not HTML/CSS. Load when designing any text-output surface where presentation is shipping class, not polish.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, ui, text-mode, markdown, telegram, terminal, presentation, monospace, unicode]
    related_skills: [claude-design, ascii-art, requesting-code-review]
---

# Text-Mode UI Design

Design visually rich interfaces where **the medium is text**. No CSS, no JS, no flexbox — just monospace characters, Unicode box-drawing primitives, and Markdown syntax.

This is the class of work for: Telegram bot replies, Slack messages, terminal reports, Markdown documentation, console dashboards, CLI output, log-formatted structured data, ASCII art cards, and any surface where text *is* the pixel.

## Why This Skill Exists

User feedback pattern: when a text-mode output ships as "correct data, flat presentation," the response is "presentation can be improved by 10x." This isn't a style preference — it's a delivery requirement. A spreadsheet-correct card with no visual hierarchy is a failed deliverable in this class.

A 10x text-mode surface has:

- **A framed header band**, not a paragraph
- **Boxed chip grids**, not inline bullets
- **Banner callouts**, not italicized asides
- **Per-entity framed blocks**, not tables
- **Insight callouts surfaced as discoveries**, not buried in data
- **Distinct sections separated by visual transitions**, not blank lines

The medium is constrained. The *design* ceiling is not.

## When to Use

Load this skill when the deliverable is any of:

- A bot reply that needs to scan in <2 seconds
- A terminal/CLI report (health snapshot, audit result, status update)
- A Markdown report or README
- A Telegram/Slack/Discord structured card
- A log-formatted data dump (JSONL view, table dump, summary line)
- Any text-mode surface where the user is going to spend 30+ seconds reading

Do NOT load this for:

- One-line status messages (design doesn't apply)
- Plain natural-language replies (already well-designed by nature)
- HTML/web artifacts (use `claude-design` instead)

## The 5-Element Visual Grammar

Every text-mode surface is built from these primitives. Use them like a designer's color and type system.

### 1. Framed Header Band

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔮  I S O P S E P H Y   C A R D
   Chidiebere onyema
   📊 17 chars · 16 letters
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Rules:
- Top and bottom borders `━━━━` (40-50 chars wide)
- Spaced caps or letter-spacing in the title
- Subtitle line indented to align with character count metadata
- Title emoji + UPPERCASED subject + spacing between words

### 2. Boxed Chip Grid

```text
╔═══════ AT-A-GLANCE ═══════════════════════╗
║  🧮 **6**   ·   ✡️ **2**   ·   🌙 ⚡ **11** (master)
║  8V/8C  ·  12 unique
╚════════════════════════════════════════════╝
```

Rules:
- Heavy corners `╔ ╗ ╚ ╝`
- Vertical bars `║`
- Section label left-aligned, uppercase or spaced caps
- Two info lines: chips on top, meta on bottom
- Width matches header band

### 3. Banner Callout

```text
┌── 🌈 ALL-DIFFERENT ──────────────────────┐
│  3 distinct root numbers — no resonance
└──────────────────────────────────────────┘
```

Use for: status banners, alerts, resonance indicators, state announcements.

Different frame style from chip grid (`┌ ┐ └ ┘`) signals "this is a callout, not data."

### 4. Per-Entity Framed Blocks

```text
╭─ Chidiebere  ·  10 letters ───────────────╮
│ 🧮 59→**5**  ·  ✡️ 140→**5**  ·  🌙 33→⚡ **33** (master)
╰──────────────────────────────────────────╯
```

Use for: each item in a multi-item collection (one per name, one per task, one per file).

Rounded corners `╭ ╮ ╰ ╯` signal "this is a discrete entity, not a section."

The closing entity (sum, combined, summary) should be visually emphasized — heavier box, UPPERCASE label (`Σ COMBINED`), or distinguished spacing.

### 5. Insight Callouts (Blockquote Discoveries)

```markdown
> ⚡ **Chaldean** yields **Master Number 11** — preserved, not reduced
> 🪞 **3 Atbash mirror pairs** — `B`↔`Y` · `I`↔`R` · `M`↔`N` (high mirror density)
```

Use for: discoveries, recommendations, things the user would say "oh, I didn't know that" about.

Each insight is a *conclusion*, not raw data. Strip the math out — that's what the data tables are for.

## Banned Patterns

These appear in "functional but flat" text-mode output. Reject them in code review.

| Banned pattern | Why it's wrong | Replace with |
|---|---|---|
| `───` as a divider | Telegram eats blank lines; `───` is invisible | Box-drawn section transitions or visual frame changes |
| `▸ **Footnote**` as a callout | Italic footnotes don't demand attention | `┌──┐` banner callout |
| Inline chips `**6** · **2** · ⚡ **11**` | Single-line density hides structure | Boxed chip grid `╔══╗` |
| Markdown table for 2-3 entities | Tables are data, not entities | Per-entity framed blocks `╭──╮` |
| Discovery buried in prose | User reads past it | Blockquote insight callout `>` |
| `**Try:** /cmd a · /cmd b · /cmd c` | Plain suggestions get scrolled past | Framed footer or status line |
| 80-char-wide tables | Telegram renders wide tables as a mess | Cap table width at 60-72 chars; use compact columns |
| Multiple blank lines between sections | Telegram collapses blank lines | Visual frame change (different border chars) |

## The Design-First Workflow

When building a text-mode surface:

1. **Audit the data first.** What are the 3-5 most important things the user needs to see in <2 seconds? Those go in the at-a-glance grid.

2. **Audit the discoveries.** What is non-obvious about this data — patterns, anomalies, master numbers, repeating elements? Those become insight callouts. Discoveries are why the user is reading this; data alone isn't a reason.

3. **Pick the 5 elements.** For each section of your output, decide which of the 5 primitives applies:
   - HEADER → framed band
   - Summary metrics → boxed chip grid
   - State / status / resonance → banner callout
   - Per-item collection → framed blocks (one per item + emphasized closing)
   - Discoveries → blockquote insights
   - Detailed data → Markdown tables (kept as-is; tables are good for dense reference data)
   - Deep math → collapsibles (`<details>`)

4. **Assign distinctive frames.** Don't reuse the same border style for two different sections. The eye should know which section it's in without reading the label.

5. **Test on Telegram.** Paste the output to Telegram and check:
   - Does the framed header band survive transport?
   - Do collapsibles render as `<details>` tags or get unwrapped?
   - Does width fit Telegram's message bubble?

## Platform-Specific Rules

### Telegram

- ✅ Preserves box-drawing characters
- ✅ Preserves `>` blockquotes
- ✅ Preserves Markdown tables (max ~60-72 char width)
- ✅ Preserves `<details>` collapse tags
- ⚠️ Eats blank lines (use border chars as visual dividers instead)
- ⚠️ Limited inline formatting inside code blocks (must use the Markdown surrounding the `````)

### Slack

- ✅ Preserves box-drawing
- ✅ `*bold*` not `**bold**` (mrkdwn, not GFM)
- ✅ `>` blockquote preserved
- ⚠️ Tables rendered inconsistently
- ⚠️ `<details>` tags render as literal text (avoid for Slack)

### SMS / plain text

- Width must be <160 chars total
- ⚠️ Box-drawing chars may render as `?` on legacy networks — verify before relying on them
- ⚠️ No Markdown support — render summary directly as plain text

### Email (HTML)

- ✅ Use `<h3>` / `<h4>` for sections (renders as proper headings)
- ✅ `<blockquote>` for callouts
- ✅ Box-drawing chars preserved in `<pre>` monospace blocks
- Test: render summary, send email, verify in Gmail/Spark/Apple Mail

### Terminal / CLI

- ✅ Full Unicode box-drawing available
- ✅ ANSI color codes available for emphasis
- ⚠️ Watch column width on 80-col terminals
- ⚠️ Trim trailing whitespace — it shows as red in some terminals

## Insight Generation Heuristics

A text-mode surface without insight callouts is a database dump. Surface discoveries programmatically.

For data-rich outputs, scan for:

1. **Min/Max extremes** — "highest value is X, lowest is Y"
2. **Pattern collapses** — "3 elements share root 5" / "all 4 entities share power number 9"
3. **Threshold breaches** — "7 rows >100 chars trigger the warning" / "mirror density >3 is unusual"
4. **Anomalies** — "this entity alone breaks the pattern" / "all except one match"
5. **Combinations** — "combined produces master number; individually, only component pieces do"
6. **Predictions** — "next token probability P > 0.8" / "release date likely Q3"

Each candidate is a one-line blockquote. The user gets 0-5 per card; trim if the card already has too many.

## Pitfalls (Real Session Lessons)

### Use ````` as plate

Don't hand-align box-drawing borders char-by-char. Use code fences to render them as a fixed-width block:

```text
```text
╭─ Label ───────────────╮
│ content here
╰──────────────────────╯
```
```

Telegram will render the inner content monospaced, side-by-side borders aligned.

### Test platform-renderer invariants, not format strings

When tests assert `"| Cipher | Raw | Root | Ladder |" in out`, every redesign breaks the test. Tests must assert:

- Presence: `assert "Master Number 11" in out`
- Invariants: `assert Σ raw in entity block`
- Behavior: `assert 3+ insights fire for high-data inputs`

(Reinforced in TDD skill's "diagnostic loop got blocked" section — invariant tests survive regex changes.)

### Don't overstack frames

A card with frame inside frame inside frame is noise. Allow whitespace between sections and let each frame breathe. Visual hierarchy comes from the *alternation* between framed and unframed content.

### Closing entity always gets emphasis

If the card lists items + a Σ sum, the Σ must be visually heavier than the items. Options:

- UPPERCASE label (`Σ COMBINED`)
- Heavier box (double-line border chars: `╔═══╗`)
- One extra line of whitespace above
- All-caps label in the box title

Pick one. Don't combine all four or it becomes visual noise.

### Width budget

Pick one width for the entire card (e.g., 40-44 chars for chip grids, 36-40 chars for entity blocks). Mixing widths mid-card looks broken.

Test: search-and-replace `────` line length — all borders should match.

### Redesign before you rebuild

When the user complains about an existing Telegram command's UI ("confusing", "no context", "10x improvement"), **first prove the capability already works** before designing from scratch. Search `gateway/slash_commands.py` for the slash handler and `gateway/platforms/telegram.py` for `send_<cmd>`. Common finding: the keyboard callbacks and dispatch chain are correct; only the *visible header text* is the spreadsheet-correct-with-no-hierarchy failure mode. The fix is a 5-element redesign of the header text only — keyboard callbacks are sacred, the dispatch is sacred, the routing is sacred. Keep all of those untouched.

For the `/model` Telegram case specifically, see `references/telegram-model-picker.md` for the exact file:line map and pre-investigation punch list.

### Lane guard: `gateway/` is Claude's single-writer lane

The Hermes estate pre-commit hook (`.git/hooks/pre-commit:45`) blocks any commit touching `gateway/`, `scripts/coordinator.py`, `config.yaml`, or `plugins/otto-inbound/` unless `HERMES_LANE=claude` is set. The guard exists because concurrent edits to these paths have crashed the gateway in production. When Otto (this agent) needs to edit `gateway/`, the actual `git commit` must be delegated to Claude — Otto can read, dry-run render, and design locally, but cannot commit. Plan the Claude delegation with a tight iteration budget for the write phase only; Otto pre-investigates and hands the punch list as `context`. See `references/telegram-model-picker.md` for the budget pattern that prevents the 50/50-tool-call drop loop.

### Test the gateway surfaces, not the format

The skill bans snapshot tests (`assert "| Cmd | Desc |" in out`). For gateway surfaces this matters even more because Telegram's Markdown rendering is the contract: `parse_mode=ParseMode.MARKDOWN_V2` will eat unescaped `.` `_` `(` `)` and other reserved chars. Test invariants instead: framed band present (`"━━━━━━" in rendered`), boxed chip grid present (`"╔" in rendered and "╚" in rendered`), one per-entity block per provider (`rendered.count("╭─") >= len(providers)`), active model always visible, persistence hint always visible. Format-string tests break on every redesign; invariant tests survive MarkdownV2 escaping changes.

## Navigation Surfaces: The "Door" Pattern

When a system exposes >20 commands, menu items, or skill names, the user is
overwhelmed. The fix is **user-shaped categories** with **one primary entry
point pinned at the top** — the "door."

### When to apply

- Command lists (`/help`, `/commands`, CLI help)
- Skill catalogs (`/skills`, `/bundles`)
- Menu systems (settings, options, modes)
- Tool palettes (`/tools`, `/toolsets`)
- Any list where users say "I don't know what's available"

### The Door

If there is ONE thing the user should reach for first, it MUST be the
first line of the output — not buried in the list. The skill (or
function, or homepage) is the door. Everything else is rooms.

```markdown
🎛 Hermes Command Directory

👉 Start here: /panel — opens the cockpit (one card, every operation a tap)
   Aliases: /menu, /cockpit, /control, /mission
   Inside /panel, the 🔎 button searches every command by name — you rarely need the list below.
```

Rules:
- Door line uses **👉 emoji + bold** to stand out from the list below
- Aliases appear on the next line (so users learn the shortcuts)
- One sentence explains what happens inside the door
- The door is positioned **before** any section headers, not within them

### User-Shaped Categories

Developer-shaped categories (e.g., `Session`, `Configuration`, `Info` —
reflecting code organization) confuse users. Re-group by **what users DO**:

| User-shaped | What goes here |
|---|---|
| 🎛 **Cockpit & Overview** | Things users check first: status, summary, inbox |
| ⚙️ **Control & Approvals** | Pause/resume, approvals, gating |
| 🤖 **Agent & Model** | Switch behavior, set parameters |
| 💬 **Sessions & History** | Start, resume, undo, branch |
| 📅 **Schedule & Skills** | Cron, automation, capabilities |
| 🛠 **System & Setup** | Config, profile, restart |

Rules:
- **5-7 groups max** — more is overwhelming, fewer means groups get too big
- **Emoji + bold heading per group** — same visual grammar as data cards
- **Group size visible** (`(11)` after the heading) — signals how much reading
- **No group >15 entries** — if you have more, split them
- **Aliases shown inline** (`↪ /sitrep`) — next to the canonical name
- **Args hints preserved** (`[name]`, `<prompt>`) — so users know how to invoke

### Banned patterns for navigation surfaces

| Banned | Why it's wrong | Replace with |
|---|---|---|
| Flat alphabetical list of 50+ items | No signal of importance | Categorized directory with door at top |
| Door buried mid-list at position 22 | Looks like every other entry | Door line BEFORE any list, with `👉` and bold |
| One-letter group labels (A/B/C) | Adds memorization burden | Emoji + semantic name (`🎛 Cockpit & Overview`) |
| Developer categories (`Session`, `Configuration`) | Reflects code, not user mental model | User-shaped categories (what they DO) |
| Aliases hidden until `/help <cmd>` | Users never discover them | Aliases shown inline with `↪` |

### Tests for navigation surfaces (invariants, not format)

```python
def test_panel_lives_in_cockpit_group():
    lines = render_category_section("home")
    assert any("/panel" in line for line in lines)

def test_no_command_appears_in_two_groups():
    # Walk all groups, assert each name maps to exactly one group
    seen = {}
    for key in category_keys():
        for name in names_in(key):
            assert seen.setdefault(name, key) == key

def test_every_user_facing_command_appears_somewhere():
    # Walk all groups, assert registry names are subset
    assert registry_names <= rendered_names

def test_door_is_first():
    lines = render_help()
    first_actionable = next(l for l in lines if "👉" in l or "Start here" in l)
    assert "/panel" in first_actionable
```

Never test for `assert "| Cmd | Desc |" in out` — that's a snapshot test that
breaks on every redesign. Test the **invariants**: door prominence, group
membership, count parity, alias visibility, args hint preservation.

### When NOT to apply

- The list has <15 entries (just show them)
- All entries are equally obscure (no door exists)
- The user is searching, not browsing (use a search bar, not a directory)

## See Also

- `references/visual-upgrade-checklist.md` — pre-shipping verification checklist (frames, density, platform, tests, anti-patterns, the "10x test")
- `references/navigation-surfaces.md` — categorized directory pattern, door placement, Slack-vs-other-platform parity for command surfaces
- `references/telegram-model-picker.md` — exact file:line map for redesigning the existing `/model` Telegram picker header + adding the `/panel` "🤖 Agent & Model" door; pre-investigation punch list + Claude subagent budget; **read before any gateway/ picker edit**
- `scripts/surgical_replace.py` — `replace_function(path, fn_name, new_source)` helper that bypasses the `patch` tool's over-indent bug. Use when a long multi-line patch mangles your file's indentation.
- `scripts/slack_via_hermes.py` — helper to compute which commands belong in `_SLACK_VIA_HERMES_ONLY` given Slack's 50-slash cap and which canonical MUST stay native (e.g., `/help`)

## Final Rule

```
Text-mode output without visual hierarchy is a spreadsheet.
A spreadsheet does not deserve a Telegram bubble.
```

Treat text-mode surfaces with the same design discipline you'd apply to a landing page. The medium is constrained. The audience is the same.</content>