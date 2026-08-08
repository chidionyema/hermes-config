# Handoff — Operator UX programme (P0 + P1 next session)

## Active task
Ship P0 + P1 of the spec at `~/.hermes/OPERATOR_UX_SPEC.md` in a **fresh-context session**.
This session did not start the work (resident ~141K, ~5x session floor per turn). Handoff is
the safe point.

## Spec state (committed, do not re-derive)
- `986c0f5` — programme opened (baseline measured)
- `b793a88` — R3 closed false, `/model` row corrected, R1 partially answered
- `a6069bc` — autosync 2026-08-08 02:01:07 (swept in a small edit; verified landed in HEAD)

§5 ledger now has three rows + an "across the board" section (no-silent-config, CLI/help fed
by the same intent tree, alerts-as-interface on the transition-not-state pattern). Cockpit
behaviour stays out of scope.

## Verified facts (blockers re-checked, all from this session's read of HEAD)

- **R3 (menu push unverified): FALSE** — production call is in
  `gateway/platforms/telegram.py:2366` (startup, all three scopes) and `:6515` (forum lazy).
  Hard cap is `MAX_COMMANDS_PER_SCOPE = 30`. The 12-slot scarcity is the operator profile,
  not Telegram. Caveat: push is startup-only — menu changes need a gateway restart.
- **R1 (config re-read): YES, with caveat** — `load_config()` uses mtime+size cache
  (`hermes_cli/config.py:5295`). A `config.yaml` write re-pops the cache on the next call.
  Long-lived in-memory model instances keep their old provider until next instantiation; the
  panel must say "takes effect on next dispatch".
- **13 roles are real and have no UI** — `~/.hermes/config.yaml:119-212` under `auxiliary:`,
  all `provider: auto / model: ''`. List: vision, web_extract, compression, skills_hub,
  approval, mcp, title_generation, tts_audio_tags, triage_specifier, kanban_decomposer,
  profile_describer, curator, monitor.
- **Both `/agent_model` and `/model` are unadvertised.** The spec's "12 slots" is
  `OPERATOR_TELEGRAM_MENU` in `gateway/operator_shell/menu.py:14-28`:
  `panel, projects, dashboard, status, inbox, brief, cron, busy, notify, revert, missions, help`.
  Neither `agent_model` nor `model` is in that list. `agent_model` is registered at
  `hermes_cli/commands.py:152`; `model` at `hermes_cli/commands.py:184`.

## P0 (no-restart window doesn't apply — restart is approved)

Q1 answer: take the restart. A no-restart P0 fixes only the handler and leaves both commands
invisible — the 31 Jul shape.

Surface TWO commands, not one:
1. Add `agent_model` and `model` to `OPERATOR_TELEGRAM_MENU` in
   `gateway/operator_shell/menu.py:14-28`. The list is currently 12 of 12, so adding two
   pushes it to 14; `MAX_COMMANDS_PER_SCOPE = 30` is fine.
2. Make `/agent_model` and `/model` print current state BEFORE offering a change
   (state-before-verb, principle 3). Today they jump straight to a picker.

## P1 (the persistent door)

Reply keyboard with five buttons (the spec's five):
- `🎛 Now` — home view
- `🤖 Brains` — landing for P2 (the Brains panel)
- `⚙️ Control` — pause/resume/approve/restart
- `📥 Inbox` — alias `/inbox`
- `❓ All` — `/help` directory, fallback not door

Implementation lives in the Telegram adapter; the existing `/` menu stays as fallback.
Re-tapping a button re-renders rather than nesting.

## P2 (next-next; not for this batch)

Brains panel — all three scopes (session, agent, 13 roles) in two taps from `🤖 Brains`.
Start with the R1 runtime test (change one role, dispatch, observe the actual model used)
BEFORE the writer ships, because the panel must state true semantics or it is a lie with
a tick next to it. P3 reachability gate lands with P2.

## Verified landmines

- **Hourly autosync bare-commits working-tree edits.** `config.yaml` is one of the targets.
  The most recent sweep (`a6069bc`) swept an in-flight edit into a real commit; the author
  then verified in HEAD that the content actually landed before moving on. **The rule for
  this work: never trust your own commit's exit code. Verify the file content in HEAD before
  moving to the next change.** This is the same defect class the spec is about.
- **`cron/jobs.json` is also autosync-managed.** Stash or expect concurrent sweeps there
  too.
- **`hermes-agent` is a submodule** (the `m` in `git status` = modified pointer). Touching
  inside it means committing inside the submodule first, then bumping the parent pointer.

## Files I expect the next session to touch

- `gateway/operator_shell/menu.py` (P0: add `agent_model`, `model` to OPERATOR_TELEGRAM_MENU)
- `hermes_cli/commands.py` (P0: state-before-verb in `/agent_model` and `/model` handlers)
- `gateway/platforms/telegram.py` (P1: ReplyKeyboardMarkup install + handler routing)
- A test that pins "every non-hidden CommandDef is reachable from the door in ≤2 taps"
  (P3 lands with P2; P1 is the right moment to lay the wiring)

## Files I will NOT touch

- `checkpoints/LATEST.md` — the prior epoch's checkpoint; out of scope, may be rotated by
  another session
- `hermes-agent` submodule contents — touch inside the submodule first
- Anything under `cron/` — autosync-managed, treat as read-mostly unless coordinating

## Safe point

This session is the safe point. The next session picks up P0 with the spec, the verified
facts, the open scope, and the landmines — and does not have to re-derive any of them.