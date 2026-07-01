# DEEPSEEK WORK-ORDER — Estate Cockpit Convergence (Phases 2–4 + read-only 5)

**Author:** Claude (Opus 4.8) · **Date:** 2026-06-26 · **For:** DeepSeek, gate-locked harness
**Companion docs:** `ESTATE_REQUIREMENTS_AND_SURGERY.md`, `ESTATE_NORTH_STAR.md`, checkpoints/LATEST.md
**Status of Phases 0 & 1:** DONE + PROVEN by Claude (safety plist disabled; prospector POPDD gate
installed; 507/0 receipt). This work-order is Phases 2–4 and the *read-only* parts of Phase 5.

Every file:line anchor below was re-verified on disk on 2026-06-26. If a line number has drifted,
search for the quoted snippet — the snippet is authoritative, the line number is a hint.

---

## 0. READ THIS FIRST — non-negotiable constraints

### 0.1 THE ONE SAFETY RULE (violating this blinds the founder)
Exactly **one** process owns the Telegram bot token. The **cockpit webhook is canonical**:
`uvicorn sentinel.cockpit.server:create_app` on `127.0.0.1:8801`, public via ngrok. The old
**gateway is dead and its launch plist is now `Disabled`** — DO NOT start the gateway, DO NOT call
`setWebhook`/`deleteWebhook`/`getUpdates` long-polling, DO NOT run `reliable_otto.py`. You PORT logic
*out of* the gateway file into the cockpit; you never run the gateway.

### 0.2 THE FENCE — these are CLAUDE-ONLY. Do NOT implement them. Leave the marked stubs.
The founder rule: **money / identity / contract / migration logic never leaves Claude.** Therefore:
- ❌ **Task APPROVE write path** (escalated → approved/executing). Approving can release a *money*
  (signalengine) or *identity* (tie) task. You implement the LIST and CANCEL paths; for APPROVE you
  emit the exact stub in Task A2 and STOP. Claude wires approve with risk-class + proof-gate checks.
- ❌ **signalengine (`risk_class: money`) and tie (`risk_class: identity`) TRIGGER / run / execute.**
  You may build **read-only status tiles** (Task D1) — never a "run" or "trigger" button for them.
- ❌ **RSI / self-improvement arming** (the `OFF_SWITCH`). Out of scope entirely.
- ❌ Any change under `~/.hermes/hermes-agent/gateway/**` (it's the dead door; read-only reference).

If a task tempts you across the fence, STOP and write `# FENCE: Claude-only — see spec §0.2`.

### 0.3 CANONICAL FACTS (verified 2026-06-26)
- Cockpit code repo: `/Users/chidionyema/Documents/code/sentinel-loop`, module `sentinel.cockpit`.
- Live coordinator DB: **`~/.hermes/coordinator.db`** (daemon PID held it open; 1.5 MB). The file
  `~/.hermes/scripts/coordinator.db` is **0 bytes and DEAD — never touch it.** Always open the DB via
  `coordinator.connect()` (which defaults to `DB_PATH = ~/.hermes/coordinator.db`, coordinator.py:301,322).
- Coordinator module: **`~/.hermes/scripts/coordinator.py`**. Import as `import coordinator as C`
  (the cockpit must add `~/.hermes/scripts` to `sys.path` if not already importable — verify first).
- Reference (dead gateway) handlers: `~/.hermes/hermes-agent/gateway/platforms/telegram.py`.

### 0.4 COORDINATOR API you will call (verified signatures, coordinator.py)
| Symbol | Line | Signature | Use |
|---|---|---|---|
| `connect` | 322 | `connect(db_path=DB_PATH) -> sqlite3.Connection` | open the live DB |
| `approve` | 1486 | `approve(conn, task_id: str) -> bool` | **FENCED — Claude only** |
| `_set` | 568 | `_set(conn, task_id: str, **fields) -> None` | set status (e.g. cancelled) |
| `estate_paused` | 1558 | `estate_paused() -> bool` | read pause state |
| `set_estate_paused` | 1565 | `set_estate_paused(on: bool) -> bool` | write pause state |
| `escalate` | 1361 | `escalate(conn, task, reason, notifier, decision=False)` | (reference) |
- Tasks table: `SELECT id, status, title FROM tasks WHERE id LIKE ?` (status values include
  `escalated`, `executing`, `cancelled`). Match short ids with `task_id + '%'` (gateway pattern).

---

## 1. HOW YOU WORK (gate-locked harness rules)

1. **Branch.** Work on `estate-cockpit-convergence` off the cockpit repo's current branch. Never commit
   to `main` directly.
2. **POPDD gate is LIVE on prospector but NOT on sentinel-loop.** For THIS repo (sentinel-loop) the
   proof obligation is: every task ships a **pytest** that fails before your change and passes after,
   committed in the same change. No test, no done. (Mirror prospector's discipline.)
3. **Each task is one commit** with message `cockpit(phaseN): <task id> <summary>` and a trailer
   `Proof: <path to the test + its pass output>`. Do not bundle tasks.
4. **Review fence.** After each commit, STOP and request Claude review BEFORE the next task. Claude
   runs (not reads) your test. This is the gate; do not self-merge to main.
5. **No new dependencies.** Use stdlib + whatever `sentinel.cockpit` already imports.
6. **Acceptance has two layers per task:** (a) an automated pytest, (b) a manual phone check the
   founder can run. Both are specified. (a) is your obligation; (b) is the founder's confirmation.

---

## 2. PHASE 2 — CONTROL PLANE (restore remote control; unblocks ~16 stuck `escalated` tasks)

### Current state (verified)
- Cockpit callback router: `sentinel/cockpit/server.py:538-579`. It dispatches `callback_query.data`:
  - `server.py:548` routes `nv:` / `ac:` / `d*` prefixes to `menu.handle_callback`.
  - `server.py:552` handles `action:` inline.
  - **No branch for `task:`, `estate:`, `update_prompt:`** → those buttons are silently dropped.
- Callback handler: `sentinel/cockpit/menu.py:437` `async def handle_callback(data, chat_id, cbq_id)`;
  current prefixes: `nv: ac: dx: dh: dg: da: ds: dk: di: dz: dl: dr:` (menu.py:440-478). None of ours.
- Reference impl in dead gateway: `telegram.py:4082` (`task:`), `4207` (`estate:`), `4503`
  (`update_prompt:`). The estate button row is `telegram.py:6245-6258`
  (resume/pause/refresh/restart/list_active/view_logs/system_fuel).

### Task A1 — Route the three prefixes into the cockpit
**File:** `sentinel/cockpit/server.py` (~line 548, the dispatch chain).
**Do:** add, before the generic fallback, routing so that data starting with `estate:`,
`task:`, or `update_prompt:` is dispatched to new handlers in `menu.py`
(`handle_estate_callback`, `handle_task_callback`, `handle_prompt_callback`). Always call
`answer(callback_query["id"])` so the phone's spinner clears (match existing pattern at server.py:553).
**Acceptance (auto):** `tests/cockpit/test_callback_routing.py` posts a fake update with
`callback_query.data == "estate:refresh"` to the FastAPI app (use `fastapi.testclient.TestClient`)
and asserts the estate handler is invoked (monkeypatch it) and `answerCallbackQuery` is sent.
**Acceptance (phone):** tapping any estate button no longer "does nothing".

### Task A2 — `task:` handler (LIST + CANCEL only; APPROVE is FENCED)
**File:** `sentinel/cockpit/menu.py` — add `async def handle_task_callback(data, chat_id, cbq_id)`.
**Reference:** gateway `telegram.py:4082-4205`. Data shape is `task:<choice>:<id>`; choices include
`approve`, `cancel`. Port the id-resolution (`SELECT id, status, title FROM tasks WHERE id LIKE ?`
with `task_id + '%'`; handle 0 / >1 matches) and:
- `choice == "cancel"` → `C._set(conn, full, status="cancelled")`, confirm to chat.
- `choice == "approve"` → **DO NOT IMPLEMENT.** Emit exactly:
  ```python
  # FENCE: Claude-only — approve releases money/identity tasks. See spec §0.2.
  send(chat_id, "🔒 Approve is handled by Claude (risk-gated). Not enabled here yet.")
  return
  ```
- Also add a `/tasks` text command (and a `task:list` callback) that lists rows where
  `status='escalated'` with short id + title (reference gateway list-active at telegram.py:~4226).
**Authorization:** reuse the cockpit's existing chat-id allowlist (find how server.py:482 derives
`from_id`/authorization; do NOT invent a new auth scheme).
**Acceptance (auto):** `test_task_cancel.py` seeds a temp sqlite with an `escalated` task, calls the
handler with `task:cancel:<id>`, asserts the row becomes `cancelled`. A second test asserts
`task:approve:<id>` leaves status UNCHANGED and sends the fence message.
**Acceptance (phone):** `/tasks` lists the stuck escalated items; Cancel works; Approve shows the lock.

### Task A3 — `estate:` handler (pause / resume / status / logs / restart-with-confirm)
**File:** `sentinel/cockpit/menu.py` — add `async def handle_estate_callback(data, chat_id, cbq_id)`.
**Reference:** gateway `telegram.py:4207-4360`. Port these `estate:<action>` branches:
- `refresh` / status → read `C.estate_paused()`, render status + the button keyboard
  (port `_status_keyboard(paused)`, telegram.py:6240-6260).
- `pause` / `resume` → `C.set_estate_paused(action == "pause")`; reply paused/resumed.
- `view_logs` → tail `~/.hermes/logs/coordinator.log` (last ~30 lines).
- `list_active` → list non-terminal tasks from the DB.
- `restart` → **two-step**: first tap shows a confirm button `estate:restart_confirm`
  (telegram.py:4349); only `restart_confirm` performs the restart. Restart =
  `launchctl kickstart -k gui/$(id -u)/<coordinator-label>` — VERIFY the coordinator's launchd label
  first (`launchctl list | grep -i coordinat`); if you cannot verify the label, leave `restart_confirm`
  as a `# FENCE: needs verified launchd label` stub rather than guessing a kill.
**Acceptance (auto):** `test_estate_pause.py` monkeypatches `C.set_estate_paused`/`C.estate_paused`,
drives `estate:pause` then `estate:resume`, asserts the calls and the reply text. Logs test asserts a
bounded tail.
**Acceptance (phone):** Pause shows "Estate PAUSED"; `C.estate_paused()` returns True in the live DB;
Resume reverses it. This is the **emergency STOP** — it must work.

### Task A4 — `update_prompt:` handler
**File:** `sentinel/cockpit/menu.py` — `async def handle_prompt_callback(data, cbq_id)`.
**Reference:** gateway `telegram.py:4503+`. Data is `update_prompt:y` / `update_prompt:n`. Port the
approve/decline of a pending prompt update. If the pending-prompt state lives in a gateway-only place
you cannot reach from the cockpit, implement the handler to acknowledge + render "no pending update"
and mark `# TODO(Claude): wire pending-prompt store` rather than faking an apply.
**Acceptance (auto):** handler returns/acks for both `y` and `n` without raising.

---

## 3. PHASE 3 — VISIBILITY (reports + cron + fuel + daemon control)

### Task B1 — Fix the audit-report `glob` NameError (smallest, do first)
**File:** `~/.hermes/plugins/otto-inbound/__init__.py:353`. The function (audit handler at ~line 342)
calls `glob.glob(...)` but `glob` is NOT imported at module top (top imports end at line 25; other
functions import it *locally* at 563/629/659). So this path raises `NameError` and the full audit
report never attaches to Telegram.
**Do:** add `import glob` — preferably at module top with the other stdlib imports (line ~20). One line.
**Acceptance (auto):** `test_audit_glob.py` imports the module and asserts `hasattr(module, 'glob')`
OR (better) calls the audit function with a fake `_scripts` dir containing a
`reports/ESTATE-AUDIT-x.md` and asserts no NameError and that `_ack_file` is called with the newest.
**Acceptance (phone):** ask Otto "audit the estate" → the full `ESTATE-AUDIT-*.md` arrives as a document.

### Task B2 — `/cron` view (surface paused + disabled jobs)
**File:** `sentinel/cockpit/menu.py` + register command in server/menu router.
**Source:** `~/.hermes/cron/jobs.json` (jobs are a list; each has `id`, `name`, `enabled`, `schedule`).
Render each job: name, schedule `display`, and ✅/⏸ by `enabled`. **Highlight disabled ones** —
verified disabled today: `8b3beb82ae6e` **goal-of-the-moment**, plus `d2cb4cf8d9db`, `f0b2079864c5`,
`8b3beb82ae6e`. Read-only view; no enable/disable buttons in this task.
**Acceptance (auto):** `test_cron_view.py` points the reader at a fixture jobs.json with one enabled +
one disabled job and asserts both render with correct state markers.
**Acceptance (phone):** `/cron` lists every job and clearly flags goal-of-the-moment as paused.

### Task B3 — `/fuel` view (spend) — LOWER PRIORITY, discovery first
**Do FIRST:** find the spend source. Grep `~/.hermes` for a spend/cost/token ledger (json/db/log). The
dead gateway has an `estate:system_fuel` handler (`telegram.py:~4280`, "Fuel status fetched") — read it
to learn the source it reads, then port THAT source into a cockpit `/fuel` view. If no durable spend
source exists, render "fuel tracking not yet wired" and mark `# TODO(Claude): define spend ledger` —
do NOT fabricate numbers.
**Acceptance (auto):** if a source is found, a test asserts the parse; if not, a test asserts the
honest "not wired" message.

### Task B4 — Daemon start/stop from the phone
**Source of truth:** launchd plists in `~/Library/LaunchAgents/ai.hermes.*` and the wrappers
`~/.hermes/scripts/{cockpit,ngrok,otto}-daemon.sh` (now tracked). Build an `estate:daemons` view that
lists each daemon's alive/dead state (via `launchctl list` / `pgrep`) and start/stop buttons that call
`launchctl kickstart`/`launchctl kill`. **HARD CONSTRAINT:** the **gateway** must NOT appear as a
start target (it's the fenced dead door); only cockpit/ngrok/otto/coordinator/prospector daemons.
**Acceptance (auto):** `test_daemon_view.py` monkeypatches the status probe and asserts the gateway is
absent from start targets and each listed daemon shows correct alive/dead.
**Acceptance (phone):** `/daemons` shows live/dead truthfully; stop+start of a SAFE daemon (e.g. ngrok)
round-trips. Do not test-kill the cockpit (you'd cut your own webhook).

---

## 4. PHASE 4 — OTTO LIVENESS

### Task C1 — Re-enable `goal-of-the-moment`
**File:** `~/.hermes/cron/jobs.json`, job `id == "8b3beb82ae6e"`, currently `"enabled": false`.
**Do:** flip to `"enabled": true`. Then trigger the cron runner to reload (find the reload mechanism —
the runner reads jobs.json; coordinator.py:1989 references it. Verify whether a signal/restart/CLI is
needed, or it re-reads on schedule). Document the reload step you used.
**Acceptance (auto):** `test_goal_enabled.py` asserts the job parses with `enabled == true`.
**Acceptance (phone):** the daily goal posts to Telegram at its next scheduled fire (interval 60m).
**NOTE:** RSI / self-improvement arming is **FENCED** (§0.2) — do not touch the OFF_SWITCH.

---

## 5. PHASE 5 — PROJECTS (read-only tiles ONLY; triggers FENCED)

Decision C: signalengine + tie are both ACTIVE goals. But both are fenced:
- signalengine = `~/Documents/code/signalengine` — `risk_class: money`.
- tie = `~/Documents/code/the-introduction-exchange` — `risk_class: identity`.

### Task D1 — Read-only status tiles for all three projects
**File:** `sentinel/cockpit/menu.py`. Add tiles that show, per project from `~/.hermes/projects.json`:
name, repo, `risk_class`, last status-report timestamp, and the latest line of
`~/.hermes/reports/project-status-<key>.md` if present. **READ-ONLY.** prospector (`risk_class: low`)
MAY get a "trigger status report" button. signalengine + tie get **NO trigger button** — display only,
with a `🔒 money`/`🔒 identity` marker. Claude wires their triggers behind the proof gate later.
**Acceptance (auto):** `test_project_tiles.py` asserts all three render, and that signalengine/tie
expose no trigger/run callback (only prospector does).
**Acceptance (phone):** all three projects visible with risk markers; no run button on the fenced two.

---

## 6. GLOBAL VERIFICATION CHECKLIST (the founder runs this from the phone)
- [ ] Tapping an estate button no longer dies silently (A1).
- [ ] `/tasks` lists the ~16 stuck `escalated` tasks; Cancel works; Approve shows the 🔒 lock (A2).
- [ ] Pause → `C.estate_paused()` is True in `~/.hermes/coordinator.db`; Resume reverses it (A3).
- [ ] "audit the estate" delivers the full `ESTATE-AUDIT-*.md` document (B1).
- [ ] `/cron` flags goal-of-the-moment as paused (B2); after C1 it shows enabled and fires.
- [ ] `/daemons` shows truthful live/dead and the gateway is NOT a start target (B4).
- [ ] All 3 projects show with risk markers; signalengine/tie have no run button (D1).
- [ ] Every task shipped with a pytest Claude ran and saw pass; nothing merged to main unreviewed.

## 7. WHAT CLAUDE KEEPS (NOT in this work-order — do not attempt)
1. Task APPROVE write path, risk-class-aware, proof-gated (A2 fence).
2. signalengine (money) + tie (identity) trigger/execute wiring, behind the POPDD gate.
3. RSI / self-improvement OFF_SWITCH arming.
4. Any edit inside `~/.hermes/hermes-agent/gateway/**`.
