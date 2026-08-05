---
name: hermes-gateway-editing
description: Edit files under `~/.hermes/hermes-agent/gateway/` correctly — the lane-guard procedure, the compile/test/untracked-import gates, the precedence of dispatch sites, and the conventions for adding new slash commands, dispatch actions, and panel surfaces. Load when about to modify any file matching `gateway/`, when registering a new `/command`, when wiring a new panel action, or when investigating why a Telegram/Discord/Slack handler isn't firing. Always pair with `text-mode-ui-design` when the change produces a user-facing card.
version: 1.0.0
---

# Hermes Gateway Editing

`gateway/` is the single-writer lane of the Hermes codebase — the Telegram/Discord/Slack adapter layer, the slash-command dispatch table, and the operator-shell panel renderers. Edits here reach the user's inbox, so they ship behind three pre-commit gates (compile, lane, test) and one structural gate (untracked-import). Knowing those gates is the difference between a 30-second patch and a launchd-restart surprise.

## When to Use

Load when:
- Adding or modifying a slash command under `gateway/slash_commands.py`
- Adding a new `estate:<action>` dispatch branch in `gateway/operator_shell/estate.py`
- Editing a Telegram / Discord / Slack adapter (`gateway/platforms/<platform>.py`)
- Adding a panel renderer under `gateway/operator_shell/<feature>.py`
- A commit is rejected by the lane guard (need to understand `HERMES_LANE`)
- Investigating why a `/command` isn't reaching the new handler
- Adding tests for any of the above (path conventions, mock harness, fixture pattern)

Pair with `text-mode-ui-design` whenever the change produces a user-facing card.

## The Four Pre-commit Gates

`~/.hermes/hermes-agent/.git/hooks/pre-commit` enforces four checks in order. Knowing them lets you fix-and-retry instead of guessing why the commit hung.

### Gate 1 — Compile
Runs `python -m compile` on every staged `.py`. Catches malformed files before they reach `launchd` (a non-importing `gateway/platforms/telegram.py` once crash-looped the gateway — see the comment at the top of the hook). **Fast, deterministic, always runs.**

### Gate 2 — Lane Guard
```bash
PROTECTED_RE='^(scripts/coordinator\.py|config\.yaml|plugins/otto-inbound/|gateway/)'
if [ "${HERMES_LANE:-}" != "claude" ]; then ... exit 1; fi
```
Any file under those paths requires `HERMES_LANE=claude` in the commit environment. **This is the gate that fired in the 2026-08-05 `/model` session.** The lane guard exists because concurrent edits to `gateway/` have broken production more than once. The correct bypass:

```bash
GIT_EDITOR=true HERMES_LANE=claude git commit -m "<message>" 2>&1
```

Pass `GIT_EDITOR=true` to avoid the commit hanging on an editor invocation when the commit message is supplied via `-m`. The lane guard is a **process risk** (per the Dropped-Ball Prevention hard rule, not an objective-superiority argument) — it can be overridden when the user has explicitly granted a lane override, but the override must be honored, not silently ignored.

### Gate 3 — Test Gate (operator_shell only)
Touching `gateway/operator_shell/*` or `tests/gateway/operator_shell/*` runs the full operator_shell suite. The suite is **~80s** at last measurement (479 tests). The commit will appear to hang — that is normal. **Do not interrupt; do not `--no-verify` without checking that the tests pass independently first.**

Run the gate manually before committing:
```bash
~/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/operator_shell/ -q
```

### Gate 4 — Untracked-import Gate
A staged `.py` that imports an untracked sibling from `gateway/operator_shell/` will be rejected. The incident that produced this gate: `estate.py` imported `gateway.operator_shell.daemons` while `daemons.py` was untracked — 8.8KB of unreviewed launchctl code that the gateway would have imported on its next restart. **Always stage dependent modules before staging the importer.**

## Dispatch Sites — Where to Wire Each Kind of Change

Hermes has a three-site registration path for any new slash command. Miss one and the command never fires.

| Site | Path | Purpose |
|---|---|---|
| **1. Handler** | `gateway/slash_commands.py:<class>.async def _handle_<name>_command(self, event)` | The actual function that builds the response. Pattern below. |
| **2. Dispatch table** | `gateway/run.py`: search for the existing command's `if canonical == "...":` branch | Routes `/<name>` to the handler. Adding a CommandDef without adding here leaves it silently ignored. |
| **3. CommandDef** | `hermes_cli/commands.py`: `CommandDef("name", ...)` registry + `ACTIVE_SESSION_BYPASS_COMMANDS` frozenset | The canonical name + aliases + help text + whether it runs while an agent is active. Without this, `/help` won't show the command. |

To add a new `/<name>`:
1. Implement `_handle_<name>_command` in `slash_commands.py`, mirroring an existing handler (e.g. `_handle_inbox_command`, `_handle_panel_command`).
2. Add a branch in `gateway/run.py` next to the equivalent existing command.
3. Add a `CommandDef` entry in `hermes_cli/commands.py`.
4. If the command should bypass the active-session guard (run while an agent is mid-turn), add it to `ACTIVE_SESSION_BYPASS_COMMANDS`. If it's a panel-style command (`/panel`, `/inbox`, `/agent_model`), bypass is the right call.

The 2026-08-05 `/model` session skipped command-table steps and instead used `estate:_dispatch("agent_model")` so the new command is reachable via the `estate:agent_model` callback from `/panel`. **For new panel surfaces, prefer this path** — no changes to `run.py` or `commands.py` needed, and the surface is consistent with `brain`, `tune`, `cron`, etc.

## Panel Surface Pattern (the `estate:<action>` way)

The correct way to add a new card to `/panel` is an `estate:<action>` branch in `gateway/operator_shell/estate.py:_dispatch`. Existing actions to model on: `brain`, `tune`, `sdlc`, `find`, `run`, `inbox`, `fleet`, `missions`.

Skeleton:
```python
if action == "<name>":
    # Compose (text, buttons) using the 5-element grammar
    from gateway.text_mode_cards import render_<name>_card
    text, buttons = render_<name>_card(<args>)
    return _finish(
        PanelView(
            text=text,
            buttons=buttons,
            toast="<name>",
            proof_receipt=_proof("<name>", "done", "<human label>", request_id=rid),
        )
    )
```

The PanelView dataclass, `with_nav` chrome helper, `_proof` receipt writer, and `_finish` idempotency wrapper are all already imported at the top of the file — no new imports needed beyond your renderer.

## Test Harness Conventions

`tests/gateway/test_telegram_model_picker.py` is the canonical reference. The harness:

- Mocks the `telegram` module via `_ensure_telegram_mock()` (the SDK is mocked because not all dev envs have it installed)
- Uses `_make_adapter()` to build a `TelegramAdapter` with `AsyncMock` bot
- Asserts **invariants, not format strings** (provider slug appears; current model appears; framed band present; per-entity block count)
- `pytest.mark.asyncio` requires `pytest-asyncio==1.3.0` — use the project's `venv/bin/python -m pytest`, not system `python3` (system may not have asyncio plugin installed)

The skill `text-mode-ui-design` warns against snapshot assertions like `assert "│ Cipher | Raw │" in out`; the same rule applies to gateway tests. Assert:
- **Presence**: provider name appears in rendered text
- **Invariant**: number of per-entity blocks matches `len(providers)`
- **Behavior**: edit_message_text is awaited; reply_markup is not None

Not:
- **Format**: `assert "provider\\_one" in sent["text"]` — the underscore escape is markdown_v2 implementation detail; testing it freezes every legitimate redesign

## Live Path Verification (the proof, before claiming shipped)

After the commit lands, prove the new surface wires end-to-end. **This is the receipt** — without it the work is unverified.

For `agent_model` panel:
```python
import os; os.environ.setdefault("HERMES_HOME", "~/.hermes")
from gateway.operator_shell.estate import handle_estate_action
view = handle_estate_action("agent_model")
assert view.ok
assert "<invariant>" in view.text
assert any("◀ Panel" in lbl for row in view.buttons for lbl, _ in row)
```

For `send_model_picker`:
```python
from gateway.text_mode_cards import render_model_picker_card
out = render_model_picker_card(current_model=..., current_provider_label=..., providers=[...])
assert "```text" in out
assert "━━━━" in out
assert out.count("╭─") >= len(providers)
```

For full pickers-from-message-to-Telegram, restart the gateway (`launchctl kickstart -k gui/$(id -u)/com.hermes.gateway`) and send the message from a separate session. **The receipts that matter**: `git log -1 --format=%H` + `git show HEAD --stat` + `pytest N/M passed` + `view.ok == True`.

## Pitfalls (learned from real sessions)

### The lane guard is a process risk, not an objective-superiority argument
The hard rule from `dropped-ball-prevention`: never reject another agent's work on "blast radius" or process-fence grounds alone. **But here**: the lane guard exists for a real reason (concurrent edits broke prod). Override with `HERMES_LANE=claude` only when the user has explicitly granted it; honor the guard otherwise.

### Compiling != importing
The compile gate only checks syntax (`compile(...)`, `"exec"` mode). A file can compile but fail at import time. Always re-import after editing: `python3 -c "import gateway.platforms.telegram"`. The Telegram mock harness in `test_telegram_model_picker.py` provides a higher-fidelity check.

### The parallel-patch trap on a single file (discovered 2026-08-05)

The `patch` tool supports parallel calls in a single function_calls block. **Never do this against the same file in the `gateway/` lane.** When you do, the second patch can land before the first is verified, producing cascading indentation errors and/or merged garbage where patches overlap.

What this looked like in practice — issuing 4 parallel patches to `gateway/operator_shell/estate.py`, all targeting the same `if action == "brain": ... if action == "brain_set":` block, with different selectors:

```python
# All four patches tried to insert *between* the two `if` blocks.
# The second patch landed with a half-applied first patch as context.
# Result: `IndentationError: unexpected indent (line 508, column 16)`
```

**Recovery:** `git checkout gateway/operator_shell/estate.py` to revert, then re-issue as a single `patch` call with a uniquely-identifying `old_string`. Verify with `python3 -c 'compile(open("...").read(), "...", "exec")'` after each.

**Rule:** one `patch` call per file per turn when the file is in the `gateway/` lane (or any other lane-guarded path). Multiple files in parallel is fine; multiple patches to the same file is not.

### `pytest-asyncio` is required, and your system Python may not have it
The test fixture uses `@pytest.mark.asyncio`. If you run `pytest` from the system interpreter, you get "Unknown pytest.mark.asyncio" warnings and the tests fail. **Always use the project's venv**: `~/.hermes/hermes-agent/venv/bin/python -m pytest`.

### pre-commit hooks hang, but only because they're doing real work
The test gate takes ~80s on operator_shell/. The hook will not respond for ~2 minutes — that's normal. Do **not** `--no-verify`. Do **not** kill the process. Verify by running the test manually first so you're confident the gate will pass; then commit; then `git log -1 --oneline` to confirm the commit landed.

### Don't delete the legacy fallback path on the same commit
When wrapping a flat prose surface with `text_mode_cards.render_*_card`, keep the legacy string as a `try/except Exception: _card = "..."` fallback. The fallback ensures the surface still works if a missing dep prevents the new module from importing. Stripping the fallback ships a silent regression as a "cleanup."

### Tests test the past, gates test the present
An old test for `send_model_picker` asserted `assert "provider\\_one" in sent["text"]`. That assertion encoded the byte-level markdown_v2 escape, NOT the visible behavior (provider name visible to user). When the legitimate redesign moved provider names inside a code fence (where escaping doesn't apply), the test broke even though behavior was correct. **Update invariant assertions to test visible behavior** (`assert "provider_one" in sent["text"]`), not byte-level escapes.

## See Also

- `text-mode-ui-design` — for the 5-element grammar used in panel cards
- `dropped-ball-prevention` — for the NO-FORWARDING RULE (do the work yourself before delegating)
- `operator-shell-audit` — for auditing an existing operator_shell/ for density / chrome consistency
- `requesting-code-review` — for pre-commit quality gates
- `test-driven-development` — for RED-GREEN-REFACTOR cadence on tests

## Support Files

- `references/dispatch-site-map.md` — exact end-to-end flow for `/model` and `/panel`, the three registration sites for new commands, and the inline-keyboard callback namespace table. Read this before adding a new slash command.
- `scripts/render_grammar_demo.py` — dry-run the 5 `text_mode_cards` primitives with sample data so you can verify the rendered output before wiring a new surface.
