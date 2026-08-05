# Visual Upgrade Checklist

Pre-shipping verification for text-mode UI surfaces. Run before merging any change to a card, report, or structured-output generator.

## Section 1 — Frames

- [ ] **Header band uses `━━━` top/bottom borders**, not `─` or `───`
- [ ] **Boxed chip grid uses heavy corners `╔ ╗ ╚ ╝`**, vertical bars `║`, and a single uppercase label
- [ ] **Banner callouts use `┌ ┐ └ ┘`**, distinguished from chip grid
- [ ] **Per-entity blocks use `╭ ╮ ╰ ╯`**, distinguished from banner callouts
- [ ] **No two adjacent sections use the same border style** — eye should know which section it's in

## Section 2 — Density & Information Hierarchy

- [ ] **At-a-glance summary is in the first ~5 lines** — what does the user need in <2s?
- [ ] **Discoveries are surfaced as blockquote callouts**, not buried in tables
- [ ] **Tables only appear where dense reference data belongs** (per-letter tallies, full strings)
- [ ] **Closing entity (Σ / combined / summary) is visually emphasized** (UPPERCASE, heavier border, or extra whitespace)

## Section 3 — Platform Compatibility

- [ ] **Tested in target platforms**: Telegram, Slack, SMS, email, terminal — whichever applies
- [ ] **All Markdown rendered correctly on Telegram**: tables, blockquotes, `` ``` `` fences
- [ ] **Box-drawing characters transmit intact** (no `?` for missing glyphs)
- [ ] **`<details>` collapsible tags used** for deep math on platforms that support it

## Section 4 — Tests

- [ ] **Tests assert behavior invariants** (`assert "Master Number 11" in out`), not frozen format strings
- [ ] **Tests assert count of insight callouts** when input is data-rich (e.g., `>= 2 insights for high-mirror-density inputs`)
- [ ] **Tests cover edge cases**: empty input, single char, multi-word with 2+3 letters
- [ ] **No `assert "| Header | Value |" in out`** — those are change-detector tests that break every redesign

## Section 5 — Common Anti-Patterns

- [ ] **No inline bullet chips** (`**a** · **b** · **c**`) where a boxed grid would scan better
- [ ] **No `▸ Footnote` callouts** where a banner would demand attention
- [ ] **No tables for 2-3 entities** — use framed blocks
- [ ] **No trailing blank-line sections** — Telegram collapses them
- [ ] **No `───` dividers** — they're invisible in rendering

## Section 6 — The "10x Test"

Before shipping, ask:

> Could this output be presented as a *poster*, *certificate*, or *product page*?

If not, the design hasn't earned the platform. The text-mode ceiling is high — constrained by character set, not by what design can express.

## Red Flags — STOP and Redesign

If you catch yourself doing any of these, stop and restart the design:

- Lining up data with spaces and tabs by hand (use code fences)
- Shipping a card with only horizontal dividers between sections (no frames)
- All sections using the same border character set
- Discoveries only visible by reading the data tables
- Tests that assert presence of `| Magic | String | Format |`
- Telegram paste-test reveals the framed header collapsed into a paragraph

## Verification Recipes

### Telegram paste-test

```bash
# Generate the card to a file
hermes_cardgen "Chidiebere onyema" > /tmp/card.md

# Open Telegram and paste the contents of /tmp/card.md
# Verify: framed header band intact, chip grid alignment preserved, insights render as blockquotes
```

### Width consistency check

```bash
# All horizontal borders should be exactly the same width
grep -E '^[╔╔─┌╭]' /tmp/card.md | awk '{print length}' | sort -u
# Should return ONE value. Multiple values = mixed widths (broken).
```

### Insight count check

```bash
# Should see >=N blockquote lines for data-rich inputs
grep -c '^>' /tmp/card.md
# For names with 1+ cipher master numbers + Atbash density: expect >= 2
```

### Closing-entity emphasis check

```bash
# Closing entity line should match one of these patterns
grep -E 'Σ.*COMBINED|═══|Total|Aggregate' /tmp/card.md
```

## Refactor Workflow (when an existing card needs upgrading)

1. **Snapshot current output** to `/tmp/card.before.md` for diff
2. **List all sections** currently separated by `───` or blank lines
3. **For each section, choose a frame primitive** from the 5-element grammar
4. **Move discoveries to a `💡 Insights` section** as blockquote callouts
5. **Emphasize closing entity** (Σ, Total, Summary)
6. **Test on Telegram and Slack** with `hermes cardgen <text> | <platform>`
7. **Update tests to assert invariants**, not frozen format strings
8. **Commit and ship**

## Migration Pattern (when extracting presentation from logic)

Don't rewrite the whole render function at once. Use surgical line-based replacement via `execute_code` + `pathlib`:

```python
from pathlib import Path

path = Path('render.py')
src = path.read_text()
lines = src.splitlines(keepends=True)

# Find function boundaries
start = next(i for i, l in enumerate(lines) if l.startswith('def render('))
end = next(i for i, l in enumerate(lines[start+1:], start+1) if l.startswith('def '))

# Splice
new_src = ''.join(lines[:start] + [NEW_FN] + lines[end:])
path.write_text(new_src)
```

This bypasses the `patch` tool's over-indent bug and keeps untouched helpers/renderers intact. Always `git checkout` the file first if the patch goes wrong — don't try to clean up an over-indented file with more patches.

## See Also

- `text-mode-ui-design` skill — the grammar and design rules
- `TDD skill "diagnostic loop got blocked"` — invariant testing pattern
- AGENTS.md "Behavior contracts over snapshots" — same principle