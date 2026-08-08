# Multi-Platform Renderer (worked example)

This is a worked example of the **Adapter Pattern applied to text rendering**,
captured while building the world-class Summary Card (`summary_card.py` in
`~/.hermes/hermes-agent/gateway/operator_shell/`).

Use it when:
- You have one engine that produces a structured string for human eyes
- You need to ship that string to N platforms with different dialect quirks
- You want invariant tests that prove every platform renders correctly
  without freezing snapshots

## The shape

```
                       ┌──────────────────────┐
                       │   render_engine()    │   ← single source of truth
                       │  (returns standard   │     for human-readable text
                       │   Markdown / format) │
                       └──────────┬───────────┘
                                  │
            ┌─────────────┬───────┼───────┬─────────────┐
            ▼             ▼       ▼       ▼             ▼
        telegram       slack    sms     email       glasses (30-char)
        MarkdownV2     mrkdwn   plain   HTML         monospace
        escape         adapt    text    escape       table
```

Each renderer takes the same `card: str` and `target: str` and emits the
platform-correct format. The engine has **zero** knowledge of platforms.

## Defects discovered while building this (Aug 2026)

These are real bugs caught by the test-driven path. Future renderers will hit
the same shape of bug:

1. **Map must be bidirectional.** An Atbash-style mirror pair table built
   only on A→Z missed every pair where the right-hand letter was in the
   input. Whenever you define a `Map[X]` index, also define `Map[X.mirror]`
   if you ever look up by either half.

2. **Substitution order matters with nested formatters.** When converting
   Markdown to HTML, run inline formatters (`**` → `<strong>`) **before**
   block formatters (tables → `<table>`). If the table substitution runs
   first, its contents are quarantined in a placeholder and the inline
   regex never sees them.

3. **Placeholder restoration can be recursive.** A table-substituted
   placeholder may contain inner placeholders from inline formatters. A
   single `for key, tag in placeholders.items(): out.replace(key, tag)`
   loop only restores the **outer** placeholder. The inner ones appear in
   the output as `\x00PH<n>\x00` literal garbage. Use an iterative loop:

   ```python
   while True:
       changed = False
       for key, tag in placeholders.items():
           if key in out:
               out = out.replace(key, tag)
               changed = True
       if not changed:
           break
   ```

4. **"[🧮✡️🌙] in line" is a char-class string, not a character class.**
   When checking if any of several emojis appears in a string, write
   `any(e in line for e in "🧮✡️🌙")`, not `"[🧮✡️🌙]" in line`. Same trap
   applies to any "string contains any of these multi-byte chars" check.

5. **Slip the renderer selector into a registry, not a match statement.**

   ```python
   _RENDERERS = {
       "telegram": _render_telegram,
       "slack":    _render_slack,
       "sms":      _render_sms,
       "email":    _render_email,
       "glasses":  _render_glasses,
   }

   def render_for_platform(text: str, platform: str) -> str:
       renderer = _RENDERERS.get(platform, _render_default)
       return renderer(render_summary_card(text), text)
   ```

   Unknown platform falls through to default. No surprises, easy to extend.

## The invariant-test pattern

The right test suite for a multi-platform renderer asserts **invariants**,
not snapshots. From AGENTS.md: "Behavior contracts over snapshots. Tests
should assert how two pieces of data must relate (invariants), not freeze a
current value."

Concretely, for a summary card:

```python
class TestTelegramRenderer:
    def test_preserves_raw_numerological_values(self):
        out = render_for_platform("chidi onyema", "telegram")
        # Numbers survive MarkdownV2 escape because they're not in the escape set.
        assert "61" in out and "192" in out and "37" in out

class TestSlackRenderer:
    def test_bold_syntax_is_single_asterisk(self):
        out = render_for_platform("chidi onyema", "slack")
        # **bold** (Markdown) must become *bold* (mrkdwn) — no `**` leaks.
        assert "**" not in out

class TestEmailRenderer:
    def test_bold_renders_as_strong(self):
        out = render_for_platform("chidi onyema", "email")
        # The bolded numbers must be wrapped in <strong> tags.
        assert "<strong>61</strong>" in out

class TestGlassesRenderer:
    def test_every_line_under_30_chars(self):
        out = render_for_platform("chidi onyema", "glasses")
        for line in out.splitlines():
            assert len(line) <= 30, line
```

The cross-cutting invariants:

```python
class TestCrossPlatform:
    def test_each_platform_produces_distinct_output(self):
        outs = {p: render_for_platform(target, p)
                for p in ("telegram", "slack", "email", "glasses")}
        # Pairwise distinctness: if two are identical, the renderer is
        # not really platform-aware.
        plats = list(outs)
        for i in range(len(plats)):
            for j in range(i + 1, len(plats)):
                assert outs[plats[i]] != outs[plats[j]]

    def test_unknown_platform_falls_through_to_default(self):
        a = render_for_platform(target, "smartwatch-foo-9")
        b = render_for_platform(target, "default")
        assert a == b
```

## When NOT to extend this skill

- When your engine and adapter share a single representation (no per-platform
  quirks), don't build a dispatcher — just emit the canonical form.
- When you only support two platforms, two `if platform == ...` branches
  are cheaper. Reach for the registry when N ≥ 3 or unknown platforms are
  a real possibility.
