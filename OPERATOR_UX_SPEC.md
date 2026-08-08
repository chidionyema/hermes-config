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

The hypothesis that produced the finding above (KILLED 2026-08-08, kept as a method note): I searched
`commands.py` and the tests, found `set_my_commands` only in a docstring (`commands.py:595`) and in
`tests/gateway/test_telegram_forum_commands.py:21-118`, and concluded the production push might not
exist. It does — in `gateway/platforms/telegram.py`, which my search never covered. **The lesson is
the scoping, not the grep flag:** I searched where the *data* was built and called that the whole
mechanism. When asking "is this wired?", search at the surface that talks to the outside world, not
at the module that assembles the payload. (Recursive grep here is `ugrep` and skips gitignored files,
so also pass `--no-ignore` before concluding anything is absent.)

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

### The two curves (added 2026-08-08, after the founder asked for an exponential improvement)

Operator effort is `recall × navigate × act`, per capability. **P0–P4 shrink `navigate`. They never
remove it**, and they leave effort scaling with the number of commands. Reachable-from-the-door goes
12 → 88 and then the paradigm is spent: a bounded ~7x, once. That is a real win and it is not the
thing the founder asked for.

The curve only bends by deleting a factor, not shrinking one. Three levers do that, and each is
already mostly built — the measurement below is what makes them cheap, not a proposal to build
infrastructure:

| Lever | Deletes | Already built | Missing |
|---|---|---|---|
| **L1** registry as tool schema | `navigate` | free text reaches the brain (`telegram.py:6933` → `run.py:8062` → `agent.run_conversation` `run.py:15525`); brain receives tools from `agent.tools` (`run.py:15246`); 88 `CommandDef`s already carry name + description + `args_hint` | the wire: `COMMAND_REGISTRY` is **never** converted into a tool list. It is projected onto menus and help text only. |
| **L2** alerts carry their action | the trip | `CallbackQueryHandler` registered (`telegram.py:2243`) with **8 working callback families**; 3 of 9 alert sites already attach `InlineKeyboardMarkup` | 6 of 9 alert sites send plain text (`notify_fanout.py:29`, `alert_router.py:30`, `health_monitor.py:57`, `estate_alert.py:63`, `coordinator.py:1555`, `:1576`) |
| **L3** act-and-undo | `act`, on the routine path | `push_undo`/`pop_undo` (`gateway/operator_shell/estate.py:1128-1156`) | wired to exactly 2 action families (pause/resume, cron). Not a dispatch-level decorator. |

**The levers are additive, not a reordering.** P1 is *more* necessary once L1 lands: when the operator
can ask for anything, the question becomes "what can I even ask?", which is still recall. The
persistent keyboard is the permanent answer to that — top intents always in view, brain handles the
long tail — and it is the only surface visible when nothing is pending. (Recorded because the first
draft of this section wrongly proposed demoting P1: the 12/N dilution argument applies to the `/`
command *directory*, which grows with N, not to a five-button keyboard, which does not. Founder
rejected the demotion 2026-08-08 and was right.)

Order: **P0 → P1 → P2+L3 → L1 → L2 → P3 → P4.**

### P0 — Stop hiding what already works (hours, no new UI)
- ~~Verify the `getMyCommands` hypothesis first.~~ **CLOSED** — the push is wired (§0, R3). P0 is not
  inert, but it needs one gateway restart because the push is startup-only.
- Add `model` and `agent_model` to `OPERATOR_TELEGRAM_MENU` (`gateway/operator_shell/menu.py:9-24`).
  **Both** are absent, not one (§6 ledger).
- **This requires editing a test.** `tests/gateway/operator_shell/test_operator_shell.py:23` asserts
  `len(OPERATOR_TELEGRAM_MENU) <= 12`, and `menu.py:1` documents "≤12 commands", while the actual
  platform ceiling is `MAX_COMMANDS_PER_SCOPE = 30` (`gateway/platforms/telegram.py:181`). The 12 is
  self-imposed and pinned by an assertion the platform does not require. Raise both, or displace two
  entries — but do it deliberately, because that test currently pins a constraint that does not exist.
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

### P2 — The Brains panel + generalised undo (the capability the founder actually asked for)
One screen answering "which brain is answering, for what?", covering all three scopes that exist:
session, agent, and the 13 roles. Spec in §3.

**P2 is cheaper than it looks — the machinery exists, on the wrong surface (measured 2026-08-08).**
`hermes_cli/web_server.py:3159-3171` defines `_AUX_TASK_SLOTS` and serves `/api/model/options` +
`/api/model/set`, backed by `build_models_payload` / `load_picker_context` (`hermes_cli/inventory.py`),
and the docstring states the response shape matches the TUI's `model.options` JSON-RPC 1:1 so surfaces
can share it. So a per-role model picker **is built and works** — on the web dashboard the founder does
not use from a phone. P2 is a third renderer over that payload, not a new subsystem. This is P4's
thesis arriving early, and it is the strongest evidence for doing P4 rather than three bespoke doors.

**Open discrepancy (blocks the panel's header count):** `_AUX_TASK_SLOTS` lists **11** slots;
§0 says **13**. `tts_audio_tags` and `monitor` appear in neither `_AUX_TASK_SLOTS` nor any renderer.
Resolve before P2 renders a count: either the web UI silently hides two roles (Principle 4 violation
on the surface that supposedly has coverage), or §0's 13 is wrong. Do not render "13" until it is
settled — a confident wrong count is worse than no panel.

**Ships with L3, not after it.** P2 is the first tap-to-change surface on a phone, so it is the phase
that earns the fence. Promote `push_undo`/`pop_undo` (`estate.py:1128-1156`, today hardwired to
pause/resume and cron) into a decorator at the dispatch layer, so any state-changing command returns
its result with a time-boxed inline `Undo`. Without it a fat-finger on a role model is unrecoverable
from the surface that caused it — and L1 is not shippable at all, because a brain that can invoke 88
commands can pause the estate (R7).

### L1 — The registry becomes a tool schema (deletes `navigate`)
Wire `COMMAND_REGISTRY` (`hermes_cli/commands.py:64`, **88 entries**) into the tool list the agent
already receives at `run.py:15246`. `name` + `description` + `args_hint` is already a function-calling
schema with the field names correct. Effect: reachable-without-recall goes 12 → 88 at zero taps, and
— the part that is not a constant factor — **the marginal UI cost of command 89 becomes zero**. It is
reachable the moment it is defined, with no slot negotiation, no menu design, no sort order.

This is the only item in the programme whose payoff applies to work not yet done.

Blocked on a decision, not on code: see **R6** (`natural_ops.py` intercepts first) and **R7**
(blast radius + schema token cost).

### L2 — Every alert carries its action (deletes the trip)
Convert the 6 plain-text alert sites listed in the two-curves table to `InlineKeyboardMarkup`, on the
callback infrastructure that already works (`telegram.py:2243`, 8 live families). Today an alert says
something changed and then makes the operator go find the control; after, the action is in the
message. Cost per event goes from `notice → open → navigate → act` to one tap, and the discovery cost
goes to zero because the operator never went looking.

Constraint from the estate's own experience: alert on outcome **transition**, never on standing state
(`rsi-autorun.sh`). Nightly alerts train the operator to ignore the channel, which converts this lever
into a negative one.

### P3 — Make it impossible to regress (the compounding part)
Two automated gates, because a UX principle with no test is a preference:
- **Inventory gate:** every `CommandDef` not explicitly marked `hidden=True` must be reachable from
  the door in ≤2 taps. New command with no home ⇒ red build. This is what stops the 88-commands-12-
  slots drift from silently returning. **Note: the field does not exist yet** — 0 of 88 registry
  entries carry `hidden`, so the gate has to introduce it, and every exemption becomes a deliberate,
  reviewable line rather than an omission.
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
| Commands reachable from the door | **12 of 88** (`len(COMMAND_REGISTRY)` = 88, measured 2026-08-08) | 100% of non-hidden |
| Marginal UI cost of adding command 89 | a slot negotiation against a 12-cap | zero (L1) |
| Taps per routine alert | notice → open → navigate → act | 1 (L2) |
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
- **R6 — `natural_ops.py` intercepts free text BEFORE the agent, so L1 is partly dead on arrival.**
  `run.py:8502` calls `match_natural_op(_raw_text)` (`gateway/operator_shell/natural_ops.py`), ~50
  hardcoded regexes mapping operator shorthand ("projects?", "what's on fire") to fixed actions;
  unmatched text falls through to the brain. It is a deterministic pattern match, not a classifier.
  **Decision owed before L1 ships:** retire it, or keep it as an explicit fast path with a documented
  precedence rule. Doing neither means L1 silently fails for exactly the phrases the operator uses
  most. Note this file is itself the defect class the programme is about — hardcoded shorthand that
  only a reader of the source can discover, and that decays as commands are added.
- **R7 — L1's blast radius and schema cost, both unmeasured.** A brain that can invoke 88 commands can
  pause the estate, restart the gateway and change role models. Two unresolved questions: (a) the
  fence — L3's dispatch-level undo plus confirmation on destructive verbs is the proposed answer, and
  it must land first, but "which verbs are destructive" is not yet enumerated anywhere; (b) an 88-tool
  schema on every turn is a standing token cost that has not been measured. Likely mitigations are
  tier-scoping the exposed set or a two-step search-then-call, but **do not choose one before
  measuring the naive version** — the cost may be irrelevant next to the conversation itself.

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
- **Alerts as an interface.** Now specced as **L2** in §2 with the send sites measured: 3 of 9 attach
  buttons, 6 send plain text. Push beats pull, and the constraint is unchanged — alert on outcome
  *transition*, never on standing state (`rsi-autorun.sh`), because nightly alerts train the operator
  to ignore the channel. This is the surface-agnostic lever: it applies to ntfy and email fanout
  (`notify_fanout.py:29`, `alert_router.py:30`) exactly as it does to Telegram.
- **Undo.** Now specced as **L3**, shipping with P2. The primitive exists (`estate.py:1128-1156`) and
  is wired to 2 action families; generalising it to the dispatch layer is what makes tap-to-change
  safe on a phone and is the precondition for L1.
- **The CLI gets L1 for free, the cockpit does not.** L1 lands in the gateway's agent, so any surface
  that routes free text to the brain inherits all 88 commands with no per-surface work. The cockpit is
  a panel renderer with no free-text door, so it needs P4's intent tree. Worth stating because it is
  the one place where "across the board" is not uniform.

## 6. Ledger

| Date | Change | Evidence |
|---|---|---|
| 2026-08-08 | Programme opened. Baseline measured: `/agent_model` exists and is unadvertised; per-role models have no UI; the 2026-07-31 menu complaint recurred after a sort-order fix. | §0 table, all `file:line` verified on disk this session |
| 2026-08-08 | **R3 re-verified FALSE and closed.** The menu push is wired (`gateway/platforms/telegram.py:2366`, `:6515`); the real cap is `MAX_COMMANDS_PER_SCOPE = 30`, and the 12 is `OPERATOR_TELEGRAM_MENU` (`gateway/operator_shell/menu.py:14-28`). Push is startup-only ⇒ P0 needs a restart. | §0, §4 R3 |
| 2026-08-08 | **§0 row 2 CORRECTED: `/model` is also unadvertised.** `_TELEGRAM_MENU_PRIORITY` is not the operator filter; `OPERATOR_TELEGRAM_MENU` omits `model`. P0 must surface **both** model commands, not one. | `gateway/operator_shell/menu.py:14-28` |
| 2026-08-08 | **R1 partially answered:** `load_config()` mtime+size cache + atomic write ⇒ per-process re-read with no invalidation hook (`hermes_cli/config.py:5295`); a role change lands on the next dispatch, not in-flight. Runtime observation still owed before P2. | §4 R1 |
| 2026-08-08 | **P0 widened again: it must edit a test.** `test_operator_shell.py:23` asserts `len(OPERATOR_TELEGRAM_MENU) <= 12` while the platform ceiling is 30 (`telegram.py:181`). The 12-cap is self-imposed and test-pinned. | §2 P0 |
| 2026-08-08 | **Registry size corrected: 88, not ~58.** `len(COMMAND_REGISTRY)` = 88, `len(COMMANDS)` = 85 incl. aliases, and **0 entries carry `hidden`** — so P3's inventory gate must introduce the field. Door shows 12 of 88 = 13.6%. | import of `hermes_cli.commands`, run 2026-08-08 |
| 2026-08-08 | **Founder: "we need exponentially better UI and UX."** Recorded that P0–P4 cannot deliver it: they shrink `navigate` and are bounded at ~7x (12→88 reachable). Added §2 "two curves" + three levers L1/L2/L3, each measured as mostly-built. | §2 two-curves table, all `file:line` verified this session |
| 2026-08-08 | **L1 is one wire, not a build.** Free text already reaches the brain (`telegram.py:6933` → `run.py:8062` → `run.py:15525`) and the brain already takes tools (`run.py:15246`), but `COMMAND_REGISTRY` is **never** converted to a tool schema — projected onto menus and help text only. | Explore subagent trace, verdicts + `file:line` |
| 2026-08-08 | **L2 is 6 edits on working infrastructure.** `CallbackQueryHandler` live at `telegram.py:2243` with 8 callback families; 3 of 9 alert sites attach buttons, 6 send plain text. | Explore subagent trace |
| 2026-08-08 | **Founder REJECTED demoting P1, correctly.** The 12/N dilution argument applies to the `/` directory (grows with N), not a 5-button persistent keyboard (fixed). L1 makes P1 *more* necessary: "what can I even ask?" is still recall. Levers are additive; order is P0 → P1 → P2+L3 → L1 → L2 → P3 → P4. | §2 two-curves closing para |
| 2026-08-08 | **P0 SHIPPED (by a concurrent session) and VERIFIED.** `OPERATOR_TELEGRAM_MENU` now has 14 entries incl. `agent_model` + `model`; the hardcoded `12` in `telegram_menu_commands` replaced by `min(max_commands, MAX_COMMANDS_PER_SCOPE)`. Tests rewritten to assert the new contract, not vacuously. **Not yet live** — the push is startup-only and the gateway is running as pid 96348. | `pytest tests/gateway/operator_shell/test_operator_shell.py` = 16 passed; `-k TelegramMenu` = 8 passed; `len(OPERATOR_TELEGRAM_MENU)` = 14 |
| 2026-08-08 | **A comment in `menu.py` asserted an unbuilt capability.** It claimed `render_agent_model_panel` prints a "role table"; it prints a current model + provider chip grid only (`text_mode_cards.py:198-205`), and `switches` is four hardcoded behaviour toggles (`estate.py:619-624`). Corrected in place rather than deleted — this is the programme's own defect class appearing inside the programme's own P0. | `estate.py:619-624`, `text_mode_cards.py:178-218` |
| 2026-08-08 | **P2 is much cheaper than specced: the role picker is BUILT, on the web surface.** `web_server.py:3159-3171` `_AUX_TASK_SLOTS` + `/api/model/options` + `/api/model/set` over `build_models_payload`/`load_picker_context`, shape-matched 1:1 to the TUI `model.options` JSON-RPC. P2 becomes a third renderer, and this is the strongest argument yet for P4 over three bespoke doors. | §2 P2 |
| 2026-08-08 | **New blocker: role count is 11 or 13, unresolved.** `_AUX_TASK_SLOTS` = 11; §0 = 13. `tts_audio_tags` and `monitor` are in no renderer at all. Blocks P2's header count. | `web_server.py:3159-3171` vs `config.yaml:119-212` |
| 2026-08-08 | **New blockers opened: R6, R7.** `natural_ops.py` (~50 regexes at `run.py:8502`) intercepts free text before the brain, so L1 silently fails on the operator's most-used phrases until that precedence is decided. L1's blast radius and 88-tool schema cost are both unmeasured. | §4 R6, R7 |
| 2026-08-08 | **P0 proven LIVE, not merely shipped — and the previous row's pid was wrong.** It said "not yet live, gateway is pid 96348". The running gateway was pid 24893, started 02:44, *after* the code changed, so no restart was ever needed. Verified against Telegram itself rather than the process table; the probe never prints the bot token. | live `getMyCommands` = **14** commands, incl. `agent_model` and `model` |
| 2026-08-08 | **#7 CLOSED — and the drift was worse than specced: THREE surfaces disagreed, not two.** `config.py DEFAULT_CONFIG["auxiliary"]` = 13, `main.py _AUX_TASKS` = 12, `web_server.py _AUX_TASK_SLOTS` = 11. Both omitted roles are live in code (`tools/tts_tool.py:194`, `cron/scripts/classify_items.py:167`), so the estate was dispatching to brains the operator could not see. Fixed by **derivation** from one `AUXILIARY_TASK_KEYS` (`hermes_cli/config.py:2573`), not by restating the list — a comment is not a sync mechanism. | `tests/hermes_cli/test_auxiliary_role_coverage.py` = **7 passed**; non-vacuity check printed `simulated drift missing set: ['monitor']` → GATE BITES |
| 2026-08-08 | **Gate design note: the role tests assert SET EQUALITY per surface, never the literal count 13.** A count pins a number; equality pins the invariant. `REGRESSION_ROLES = ("tts_audio_tags", "monitor")` is named explicitly so a future "fix" that deletes roles instead of adding renderers still goes red. | same suite |
| 2026-08-08 | **P2 + L3 SHIPPED.** New `gateway/operator_shell/brains.py` (panel, writer, R2 fence, timestamped backup, append-only audit) and `gateway/operator_shell/undo_ops.py` (a reverse-payload registry replacing the 2-verb if/elif chain). Five new dispatch branches in `estate.py`; `/agent_model` **gains** a row into the roles rather than losing its existing controls (no silent feature removal). | `test_brains_panel.py` **22 passed**; `test_brains_dispatch.py` **7 passed**; pre-existing `tests/gateway/operator_shell/` **628 passed, 5 skipped** ⇒ no regression |
| 2026-08-08 | **A spec requirement KILLED by measurement.** §3 demanded a comment-preserving YAML round-trip for the config writer. `~/.hermes/config.yaml` has **0 comment lines out of 578** — an earlier `save_config` already stripped them — so ruamel round-tripping (installed, 0.18.17) would have been work for nothing. Key order is already held by `sort_keys=False`. | line + comment count on the live config, run 2026-08-08 |
| 2026-08-08 | **Three writer requirements WERE genuinely absent and were built:** timestamped backup before every write, an append-only audit row per change, and a per-role model fence. The R2 fence is **enforced in the writer, not the keyboard**, proven by a test that calls the writer with an option the keyboard never offered. The writer touches only `provider` and `model`, leaving `timeout`/`extra_body` alone so a picker cannot silently revert hand-tuning. | `test_brains_panel.py` fence + writer-isolation cases |
| 2026-08-08 | **R2 ships UNPOPULATED, deliberately.** The `role_model_allowlist` mechanism is live but empty by default: which models are strong enough to arbitrate approvals is a founder policy call, and inventing a list here would be exactly the assert-without-proof this programme exists to stop. The live half is the confirm step, and the panel says so. | `brains.py` `_allowlist_for`, `fence_check` |
| 2026-08-08 | **Latent defect found and fixed in the PRE-EXISTING undo path.** An unrecognised reverse payload fell through silently and still rendered "Undone" over a refreshed panel — a failed undo was indistinguishable from a successful one. Now surfaces `⚠️ Cannot undo`, `ok=False`, and emits `reverse_keys=`/`known=` as evidence. | `estate.py` undo branch; `undo_ops.apply_reverse` returns `(ok, applied)` |
| 2026-08-08 | **A bug the tests caught before it shipped: `Choice.alias` is a short alias, not a resolved model id.** Writing it directly would have put `model: haiku` into `config.yaml` while the agent scope carried `claude-haiku-4-5-20251001` — two surfaces disagreeing about the same model, the exact defect this panel exists to remove. Now routed through the same `switch_model` resolver (`brain.py:137`), which doubles as a credential check so an unreachable model is refused at write time. | 5 failing tests → `resolve_choice()` → 22 passed |
| 2026-08-08 | **P1 recon: the label→action router is already built AND already wired — but not where the repo claims.** Live path is `~/.hermes/plugins/otto-inbound/__init__.py:1147` → `chat_router.route_telegram_ceo:59` → `natural_ops.match_natural_op:348` → `handle_estate_action`. `gateway/run.py:8500` deliberately stands down when that plugin file exists (`chat_router.py:149-152`). A repo-scoped grep shows `route_telegram_ceo` with zero callers and is **misleading** — the caller lives outside the repo. P1's routing half is therefore a table edit, not a build. | grep of call sites across the repo **and** `~/.hermes/plugins/` |
| 2026-08-08 | **`get_persistent_keyboard()` (`commercial_ui.py:218`) has ZERO callers — "built and unreachable" again, inside P1's own scope.** It returns plain dicts rather than a `ReplyKeyboardMarkup`, and a 6-button operator layout that is not the spec's 5. P1 must supersede it, not call it. | repo-wide grep, 0 call sites |
