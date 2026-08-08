# Operator UX Programme — the Hermes control surfaces

> Status ledger + spec. **Append results here, never in a chat transcript.** A spec that lived only
> in a transcript is the reason `docs/SITE_SPEC_PROGRAM.md` exists in Prospector; this file is the
> same insurance for the operator surfaces (Telegram, cockpit, CLI).
>
> Scope: how the operator SEES and CHANGES the estate. Not what the estate does.

---

## 0. The founding measurement (2026-08-08)

The founder asked: *"there is a telegram ui feature to see and change the underlying model of the
hermes agent/coordinator etc roles, i cant see it — does it exist? does it work properly? how to
access easily"*.

Answer, with receipts:

| Thing | Where | Reachable? |
|---|---|---|
| `/agent_model` — *"Agent & model: which brain is answering, and switch it"*, aliases `agentmodel`, `brain`, `gateway_only=True` | `hermes_cli/commands.py:152-153` | **NO.** Absent from `_TELEGRAM_MENU_PRIORITY` (`:628-656`); `config.yaml:568 menu_profile: operator` registers only the first 12. Typable, never advertised. |
| `/model` — *"Switch model for this session"* | `hermes_cli/commands.py:184` | **NO — corrected 2026-08-08.** It is in `_TELEGRAM_MENU_PRIORITY` (`:637`), but that tuple is not the operator filter. `menu_profile: operator` filters to `OPERATOR_TELEGRAM_MENU` (`gateway/operator_shell/menu.py:14-28`) = `panel, projects, dashboard, status, inbox, brief, cron, busy, notify, revert, missions, help` — **`model` is not in it.** So *both* model commands are unadvertised, and P0 must surface both. Its picker is also reasoned entirely around the terminal TUI (`_PICKER_COMMANDS`, `:1396`: *"prompt_toolkit suppresses the menu"*). |
| **Per-role models** — 13 roles: `vision, web_extract, compression, skills_hub, approval, mcp, title_generation, tts_audio_tags, triage_specifier, kanban_decomposer, profile_describer, curator, monitor` | `config.yaml:119-212`, all `provider: auto` / `model: ''` | **NO UI ON ANY SURFACE.** A 13-entry control panel with no renderer. |

**The recurrence is the real defect.** `command_directory.py:9-14` records the founder complaint of
2026-07-31 — *"how do i access the menu? is there one menu are there multiple menus?"* — and the fix
shipped was a re-grouped `/help` directory. Eight days later the same question returned in a new
costume. **Re-sorting a list cannot fix an interface that requires recall.** Every future fix in this
programme is judged against that: did it change the interaction model, or just the sort order?

HYPOTHESIS (must verify before any menu work): `set_my_commands` appears in this repo only in a
docstring (`commands.py:595`) and in tests (`tests/gateway/test_telegram_forum_commands.py:21-118`,
which assert `await_count == 1`). A production call site should exist in the Telegram adapter and did
not turn up. Check: `grep -rn --no-ignore 'set_my_commands' ~/.hermes/hermes-agent` (recursive grep
here is `ugrep` and skips gitignored files), then confirm at runtime with
`curl -s "https://api.telegram.org/bot$TG/getMyCommands"`. **If the menu is never pushed, every
ranking change in `_TELEGRAM_MENU_PRIORITY` is inert and the 2026-07-31 fix could not have worked.**

---

## 1. Principles (the bar every change is held to)

1. **Zero-recall.** The operator never needs to remember a name. Capabilities are reached by
   *recognition* (tap a labelled thing) not *recall* (type the right word). A command that must be
   remembered is unshipped inventory.
2. **One door, always in the same place.** Exactly one persistent entry point per surface that does
   not scroll away, is not behind a tap-and-read, and is never ambiguous. "Is there one menu or
   several?" must be unaskable.
3. **State on the surface, before the verb.** A control that changes something *shows what it is now*
   in its own label: `🤖 Brain: sonnet ›` not `/model`. The founder asked to "see and change" — see
   comes first, and it is the cheaper half.
4. **No silent config.** Any config table with N entries and no renderer is a hidden control panel.
   If it is worth a key in `config.yaml`, it is worth a row in a panel with its current value.
5. **Honest effect.** A control states when its change takes effect (now / next dispatch / needs
   restart) and proves it, or it is a lie with a tick next to it. See §4 risk R1.
6. **No dead ends.** Every reply ends with the next available action as tappable buttons, so the
   operator is never returned to a blank prompt holding the burden of knowing what is possible.
7. **Discoverability is a testable claim, not taste.** See §3 — the reachability gate. This is the
   only principle that makes the others compound instead of decay.

---

## 2. The plan (phased, each phase independently shippable)

### P0 — Stop hiding what already works (hours, no new UI)
- Verify the `getMyCommands` hypothesis above **first**; a menu that is never pushed makes P0 inert.
- Add `agent_model` and `inbox` to the visible slots (they are Tier-0 operator intent, currently
  outranked by `restart` and `commands`), or raise the operator cap from 12.
- `/model` and `/agent_model` must **print current state before offering a change** (Principle 3),
  and must render as an inline keyboard on Telegram rather than a TUI picker.
- Deliverable: the founder's original question answerable in one tap, on the existing architecture.

### P1 — The Persistent Door (the interaction-model change)
The `/` menu is the wrong primitive: capped, hidden behind a tap, alphabet-shaped, and it evaporates
from view. Replace it as the primary door with a **persistent reply keyboard**
(`ReplyKeyboardMarkup(is_persistent=True, resize_keyboard=True)`) — always visible, survives
scrolling, no recall, no cap negotiation. Five buttons, chosen by operator intent, not code layout:

```
[ 🎛 Now ]  [ 🤖 Brains ]
[ ⚙️ Control ] [ 📥 Inbox ] [ ❓ All ]
```

- `🎛 Now` — the home view: what is running, what broke, what changed since you last looked.
- `🤖 Brains` — §3 panel: every role and its current model.
- `⚙️ Control` — pause / resume / approve / restart, with confirmation on anything destructive.
- `📥 Inbox` — decisions waiting on you (`/inbox` already exists, `commands.py:154-155`).
- `❓ All` — the full directory, which is where `command_directory.py`'s six groups belong: a
  *fallback*, not the door.

Rule: the door is pinned and idempotent. Re-tapping any button re-renders rather than nesting.

### P2 — The Brains panel (the capability the founder actually asked for)
One screen answering "which brain is answering, for what?", covering all three scopes that exist:
session, agent, and the 13 roles. Spec in §3.

### P3 — Make it impossible to regress (the exponential part)
Two automated gates, because a UX principle with no test is a preference:
- **Inventory gate:** every `CommandDef` not explicitly marked `hidden=True` must be reachable from
  the door in ≤2 taps. New command with no home ⇒ red build. This is what stops the 58-commands-12-
  slots drift from silently returning.
- **Reachability budget:** an asserted tap-count per top intent (see §3 metrics). A change that
  makes "change the coordinator's model" cost 4 taps instead of 2 fails.
- Caution: a redesign can make a guard test **vacuous** rather than failing (memory:
  `progressive-disclosure-makes-a-guard-test-vacuous`). Each gate must assert on the rendered
  surface, and must be re-audited after any IA change — a still-green test proves nothing about a
  surface it no longer describes.

### P4 — One IA, three renderers
The same intent tree renders to Telegram (buttons), cockpit (panels) and CLI (`/help`). Today the
taxonomy in `command_directory.py:26-40` exists but is projected onto only one surface, so the three
doors disagree. One source, three renderers, no per-surface menu logic.

---

## 3. Spec — the Brains panel

**Entry:** `🤖 Brains` on the persistent keyboard; aliases `/brain`, `/agent_model`, `/models` all
land here. Never a bare prompt.

**Render (state before verb, Principle 3):**
```
🤖 BRAINS — who is answering

Session ......... sonnet          (this chat only)      ›
Agent ........... sonnet          (default for all)     ›

ROLES  (13 · 0 overridden, 13 inheriting)
  approval ........ auto → sonnet                       ›
  vision .......... auto → sonnet                       ›
  … [ Show all 13 ]
[ Change agent brain ]  [ Reset all overrides ]
```
- Show the *resolved* model, not the empty string. `model: ''` renders `auto → <resolved>`, because
  `''` is not information the operator can act on.
- Count overridden vs inheriting on the header line, so drift is visible without reading 13 rows.
- Long lists collapse behind one explicit expander — never silent truncation.

**Change flow:** tap role → inline keyboard of allowed models (from the same registry the CLI picker
uses, so the two surfaces cannot disagree) → tap → confirm line stating **when it takes effect** →
re-render the panel with the new value. Two taps from the door to a changed role model.

**Writer requirements:** atomic (`tempfile.mkstemp` + `os.replace`), YAML round-trip that preserves
comments and key order, timestamped backup before write, and an append-only audit row (who, what,
old→new, when). A control-panel write with no backup and no audit row is not shippable.

**Metrics (asserted in P3, not asserted by prose):**
| Intent | Today | Target |
|---|---|---|
| See which brain is answering | not reachable without knowing `/brain` | 1 tap |
| Change the agent's brain | unknown-name recall | 2 taps |
| Change one role's model | **impossible on every surface** | 2 taps |
| Commands reachable from the door | 12 of ~58 | 100% of non-hidden |
| Capabilities requiring recall of a name | most | 0 |

---

## 4. Risks and open questions (do not ship past these)

- **R1 — Does the running gateway re-read `config.yaml`? PARTIALLY ANSWERED 2026-08-08: yes, per
  process.** `load_config()` caches on the config file's `(mtime_ns, size)` and `save_config()` /
  `migrate_config()` write via `atomic_yaml_write`, producing a fresh inode, so the next
  `load_config()` repopulates with no explicit invalidation hook (`hermes_cli/config.py:5295`
  docblock). **Remaining qualifier — this is still what gates P2:** the re-read is per *load call*,
  so an already-constructed model instance keeps its old provider until the next instantiation. A
  role change is therefore reflected on the **next dispatch for that role**, never on an in-flight
  one. The panel must say exactly that. Still unproven by runtime observation: change one role,
  dispatch, and observe the model actually used — an in-process assertion, not a config diff. Until
  that runs, "takes effect on next dispatch" is a code reading, not a measurement.
- **R2 — Fence.** Some roles must not be switchable to a weak model from a phone. `approval` and
  anything money/identity-adjacent needs an explicit allowlist of models, enforced in the writer,
  not in the keyboard layout. A keyboard that omits an option is not a fence.
- ~~**R3 — Menu push unverified.**~~ **CLOSED 2026-08-08 — false alarm, not a blocker.** See §0. What
  survives is a smaller constraint: the push is startup-only, so P0 needs one gateway restart.
- **R4 — The cockpit is used daily and operationally.** Nothing in this programme retires it or
  changes its behaviour without an explicit ask; P4 adds a renderer, it does not replace the surface.
- **R5 — `provider: auto` semantics.** 13 roles inherit; the resolution rule must be read from code
  before it is rendered, or the panel will confidently display a model the estate does not use.

---

## 5. "Across the board" — the same seven principles on the other surfaces

The founder's ask is estate-wide, so the programme is not Telegram-only. P4 unifies the IA; these are
the surface-specific items that must be audited against §1 rather than redesigned by taste. **Nothing
here retires or alters the cockpit's behaviour** (see R4) — it is used daily and operationally.

- **Cockpit.** Audit every panel against Principle 4 (no silent config) and the known defect class
  "built and unreachable" — a rendered button whose handler is unwired reads as shipped. Each panel
  must show current state in its own header, and a control with no writer must be visibly read-only
  rather than look actionable.
- **CLI / TUI.** `/help` is already grouped (`command_directory.py:26-40`); what it lacks is
  state-before-verb — the directory lists names, not current values. The same intent tree that feeds
  the Telegram door should feed it (P4), so the two doors cannot disagree about what exists.
- **Alerts as an interface.** Push beats pull: the cheapest discoverability win is not needing to
  look. The pattern is already proven in this estate — `rsi-autorun.sh` alerts on outcome
  *transition*, never on standing state, because nightly alerts train the operator to ignore the
  channel. Extend that, and routine operation stops depending on remembering where anything lives.
- **Undo.** A time-boxed inline `Undo` on every state change is what makes tap-to-change safe on a
  phone; without it, a fat-finger on a role model is unrecoverable from the surface that caused it.

## 6. Ledger

| Date | Change | Evidence |
|---|---|---|
| 2026-08-08 | Programme opened. Baseline measured: `/agent_model` exists and is unadvertised; per-role models have no UI; the 2026-07-31 menu complaint recurred after a sort-order fix. | §0 table, all `file:line` verified on disk this session |
| 2026-08-08 | **R3 re-verified FALSE and closed.** The menu push is wired (`gateway/platforms/telegram.py:2366`, `:6515`); the real cap is `MAX_COMMANDS_PER_SCOPE = 30`, and the 12 is `OPERATOR_TELEGRAM_MENU` (`gateway/operator_shell/menu.py:14-28`). Push is startup-only ⇒ P0 needs a restart. | §0, §4 R3 |
| 2026-08-08 | **§0 row 2 CORRECTED: `/model` is also unadvertised.** `_TELEGRAM_MENU_PRIORITY` is not the operator filter; `OPERATOR_TELEGRAM_MENU` omits `model`. P0 must surface **both** model commands, not one. | `gateway/operator_shell/menu.py:14-28` |
| 2026-08-08 | **R1 partially answered:** `load_config()` mtime+size cache + atomic write ⇒ per-process re-read with no invalidation hook (`hermes_cli/config.py:5295`); a role change lands on the next dispatch, not in-flight. Runtime observation still owed before P2. | §4 R1 |
