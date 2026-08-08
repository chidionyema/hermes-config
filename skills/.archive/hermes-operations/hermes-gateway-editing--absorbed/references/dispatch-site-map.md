# Dispatch Site Map — `/model` and `/panel` End-to-End

The exact wiring for the two delivery surfaces that landed in commit `7830f25647` (2026-08-05). When you're adding a new slash command or panel action, this is the reference for which file to touch and in what order.

## Two delivery surfaces, two wiring graphs

### Surface 1 — `/model` (Telegram inline-keyboard picker)

Already wired before this session — the *fix* was the header text. But the full wiring is the precedent for "user sends a slash command → Telegram calls a function → handler returns text + keyboard → user taps → callback handler resolves the choice → agent state mutates."

```
User: /model
  ↓
gateway/run.py  (slash command dispatch)
  ↓ canonical == "model"
gateway/slash_commands.py:1291  (model_command handler)
  ↓ context-aware: if picker available, adapter.send_model_picker()  ← THIS IS WHERE THE HEADER TEXT LIVES
  ↓ ELSE fallback text list (lines ~1336-1365)

gateway/platforms/telegram.py:send_model_picker (line 3509)
  ↓ builds framed header text via gateway.text_mode_cards.render_model_picker_card
  ↓ builds InlineKeyboardMarkup via _build_provider_keyboard
  ↓ sends to Telegram via _send_message_with_thread_fallback
  ↓ stores state in self._model_picker_state[chat_id] for callback routing

User taps a provider button (callback_data="mp:anthropic")
  ↓
Telegram → telegram-adapter callback handler
  ↓
gateway/platforms/telegram.py:_handle_model_picker_callback (line 3673)
  ↓ mp: → swap to model list view, edit message in place
  ↓ mm: → resolve model, dispatch on_model_selected, edit to confirmation
  ↓ mg: → pagination
  ↓ mb: → back to provider list
  ↓ mx: → cancel, close picker

on_model_selected  (closure captured by slash_commands.py)
  ↓
gateway/slash_commands.py:_on_model_selected (closure, ~line 1270)
  ↓ updates _session_model_overrides
  ↓ calls _evict_cached_agent
  ↓ applies via cached_entry[0].switch_model OR via fresh agent
```

### Surface 2 — `/panel` → 🤖 Agent & Model door (the new one)

Added in commit `7830f25647`. Wiring path for any new `estate:<action>` panel — model on this one.

```
User: /panel
  ↓
gateway/run.py  (slash command dispatch)
  ↓ canonical == "panel"
gateway/slash_commands.py:_handle_panel_command (line 3931)
  ↓ render_panel_view() → mission card

OR user taps an inline button on the mission card with callback "estate:agent_model"
OR user types /agent_model

Telegram callback → _handle_agent_model_command  (the new handler at line 3949)
  ↓
gateway/operator_shell/estate.py:handle_estate_action("agent_model")
  ↓ calls _dispatch("agent_model", request_id="...")

_dispatch (line 269):
  if action == "agent_model":
      from gateway.text_mode_cards import render_agent_model_panel
      from gateway.operator_shell.brain import current
      model, provider = current()
      try:
          from hermes_cli.providers import get_label
          provider_label = get_label(provider)
      except Exception:
          provider_label = provider or "?"
      switches = [{"slug": "agent_model", ...}, ...]
      text, buttons = render_agent_model_panel(...)
      return _finish(PanelView(text=text, buttons=buttons, toast="Agent & Model",
                               proof_receipt=_proof("agent_model", "done", "Agent & Model door", request_id=rid)))
```

That's it. **No changes needed to `run.py` or `commands.py`.** This is the PanelSurface Pattern from the parent SKILL.md — using `estate:<action>` avoids the three-site registration burden for panel doors.

## The three-site registration (for direct slash commands, not panels)

If you need a direct slash command that bypasses `/panel` (e.g. `/<name>` typed without context), you must register at three sites. **Missing one of the three makes the command dead.**

| # | Site | Path | What to add |
|---|---|---|---|
| 1 | **Handler** | `gateway/slash_commands.py` | `async def _handle_<name>_command(self, event: MessageEvent) -> Optional[str]:` mirroring `_handle_panel_command` or `_handle_missions_command` |
| 2 | **Dispatch chain** | `gateway/run.py` | Search for `if canonical == "<existing>":` matching the closest cousin. Add `if canonical == "<name>":` next to it. |
| 3 | **CommandDef** | `hermes_cli/commands.py` | `CommandDef("<name>", "<label>", ...)` in the registry. Add to `ACTIVE_SESSION_BYPASS_COMMANDS` if it should run while an agent is mid-turn. |

## Inline-keyboard callback namespace

Telegram inline-keyboard buttons carry `callback_data` strings. The established prefixes (so existing handlers don't crash on yours):

| Prefix | Handler | Purpose |
|---|---|---|
| `mp:<slug>` | `_handle_model_picker_callback` | Provider selected → show models |
| `mm:<idx>` | same | Model selected → switch |
| `mg:<page>` | same | Model list pagination |
| `mb` | same | Back to provider list |
| `mc:<idx>` | same | Confirm expensive model |
| `mx`, `mx:noop` | same | Cancel, or no-op placeholder |
| `estate:<action>` | `gateway/run.py:_handle_callback_query` | Estate panel action (brain, tune, sdlc, etc.) |
| `agent:<slug>` | (new — see opener) | Surfaces reachable from /panel agent_model door |

When introducing a new prefix, **search the dispatch table** for any existing prefix that overlaps with your prefix before adding. Conflicting prefixes are why bot handlers branch on `data.startswith("...")`.

## Pitfalls learned this session (added to the parent SKILL.md)

1. **The parallel-patch trap**: when using the `patch` tool with multiple parallel calls in the same function_calls block against the **same file** in the same lane-guarded path, the second patch can land before the first is verified, producing cascading indentation errors. Sequential patches only — never parallel patch a single file in the `gateway/` lane.
2. **GIT_EDITOR=true**: pass `GIT_EDITOR=true` to every `HERMES_LANE=claude git commit` that supplies `-m`. Without it, `git` opens `$EDITOR` (typically `vim`), the test-gate hangs for ~80s while waiting for the editor, and the user sees a "stuck" commit.
3. **`pytest-asyncio` venv**: the system `python3` may report `Unknown pytest.mark.asyncio` and fail every async test. Use `~/.hermes/hermes-agent/venv/bin/python -m pytest` — the venv has `pytest-asyncio==1.3.0` from the `[tool.pytest.ini_options]` config in `pyproject.toml`.
