# SPEC — Make the Mothership Cockpit CEO-level (for DeepSeek execution)

**Author:** Claude (Opus 4.8). **Owner of review/merge:** Claude. **Executor:** DeepSeek (gate-locked harness).
**Canonical state:** run `bash ~/.hermes/scripts/verify_estate.sh` (exit 0 = OPERATIONAL). Map: `~/.hermes/ESTATE_STATE.md`.
**Discipline:** every claim below is anchored to `file:line` verified on disk on 2026-06-26. Every work item ships
with a test/repro — "done" with no green check is not done (proof-of-claim).

---

## 0. READ FIRST — non-negotiable constraints (violating any of these fails review)

1. **The ONE safety rule:** exactly one process owns the Telegram bot token. The cockpit webhook is canonical.
   - NEVER start the gateway or `scripts/quarantine/reliable_otto.py.DANGER`. NEVER call `deleteWebhook`.
   - Evidence: `~/Documents/code/sentinel-loop/scripts/quarantine/README.md`; `ESTATE_STATE.md` "The Mothership".
2. **Founder fence — money/identity/contract NEVER execute from DeepSeek's code.** You may build INTAKE and
   READ paths for them, but the *execution trigger* and the *approve write* stay Claude-only:
   - `task:approve` must not write from the cockpit — fence text at `menu.py:833-839` ("Do NOT call C.approve()").
   - No `signalengine` (money) or `tie`/Introduction-Exchange (identity) execution/deploy trigger in cockpit code.
     Probe enforces this: `verify_estate.sh:196-200` FAILS if such a trigger appears in `menu.py`.
   - No edits under any `gateway/**` path.
   - `signalengine` = money, `tie` = identity, `prospector` = low, `haworks-platform` = low
     (source: `~/.hermes/projects.json`). When a work item touches a money/identity project, you implement only
     the LOW-risk path directly and route money/identity through the existing coordinator approval gate (WI-5).
3. **Deploy model:** the cockpit is `uvicorn sentinel.cockpit.server` with **no `--reload`**, launched by launchd
   `ai.hermes.cockpit` against on-disk files. A restart deploys the working tree:
   `launchctl kickstart -k gui/$(id -u)/ai.hermes.cockpit`. "Written ≠ running" until restarted.
4. **Tests stay green.** Keep the existing suite passing; add tests under `tests/cockpit/`. Run the project's
   `verify_build` (pytest) and paste the verdict lines in your PR. Do not dump full logs.
5. **Scope of edits:** `~/Documents/code/sentinel-loop/sentinel/cockpit/*.py` and `tests/cockpit/` only, except
   the fenced items above. The dead `ui_engine.py` (`CockpitUIEngine`) is NOT wired into the live webhook path
   (no import in `server.py`/`menu.py`) — do not build on it; the live UI is `menu.py` + `server.py`.

Deliver one PR per phase (WI-1…WI-8), each independently verifiable. Branch off `main`.

---

## 1. The live architecture you are editing (verified anchors)

- Webhook entry: `server.py:502` `POST /webhooks/telegram` → auth (`X-Telegram-Bot-Api-Secret-Token` +
  `validate_telegram_user`, `server.py:502-532`) → routes slash commands and callbacks.
- Telegram send helper: `menu.py:15 _api(method, body)`; `menu.py` `send()` wraps `_api("sendMessage", body)`.
- Slash dispatch: `_dispatch_slash_command(cmd)` (called from `server.py:449`).
- Callback router: `menu.py:465 handle_callback(data, chat_id, cbq_id)` — current prefixes:
  `nv: ac: dx: dh: dg: da: ds: dk: di: dz: dl: dr:` then `estate:` (`menu.py:527`), `task:` (`menu.py:776`),
  choice (`menu.py:855`). **There is NO `deploy:` branch.**
- Free-text (non-slash) → Otto chat relay: `server.py:567-576` → `_call_otto()` (`server.py:109`, POSTs
  `http://127.0.0.1:8802/chat`). Never `coordinator.inject()`.
- Persistent menu registration: `server.py:184 register_persistent_menu()` — sets `setMyCommands` +
  `setChatMenuButton` for the **first** allowed user id only (`server.py:200-240`).
- Coordinator (task engine, separate process, `~/.hermes/scripts/coordinator.py`):
  `connect()` (:322), `open_task(conn, *, title, body="", kind="injected", ...)` (:546),
  `fence_class(text)` (:612, returns low|money|identity|contract), `send_telegram_buttons(msg, task_id)` (:108),
  `escalate(...)` (:1361). DB: `~/.hermes/coordinator.db`.

---

## WI-1 — Persistent nav bar (zero command-memorization)  [risk: low]

**Problem (verified):** the always-visible button bar does not exist.
- `server.py:469` calls `_reply_keyboard_markup()` — `grep -rn "_reply_keyboard_markup"` across the cockpit
  returns **only this call site; the function is never defined** (NameError if ever hit).
- `server.py:452 _send_with_keyboard(...)` — `grep -rn "_send_with_keyboard" sentinel/cockpit/*.py` returns
  **only its `def`; it has no callers** → dead code. So no `ReplyKeyboardMarkup` is ever attached to any message.
- Net effect: the user must type slash-commands or tap the MENU icon. This is the founder's complaint
  ("how does Dario remember the commands").

**Required change:**
1. Implement `_reply_keyboard_markup()` returning a Telegram `ReplyKeyboardMarkup` with
   `{"keyboard": [...], "resize_keyboard": true, "is_persistent": true}` and 4–6 top-level buttons whose
   *button text* maps to existing screens, e.g. `🏠 Home`, `🛰 Projects`, `🏛 Estate`, `✅ Tasks`, `🚀 Deploy`,
   `🔄 CI/CD`.
2. Attach the reply keyboard on `/start` and `/dashboard` responses (Telegram persists it across subsequent
   messages until replaced — you do NOT need to attach it to every message). Either revive `_send_with_keyboard`
   and call it for those two responses, or set it inline.
3. In the free-text router (`server.py:567-576`), match those exact button-label strings BEFORE relaying to Otto,
   and dispatch each to its screen handler (so a tap on `🏠 Home` renders the dashboard, not an Otto chat reply).

**Acceptance test:** new authorized user sends `/start` → an always-visible button bar appears at the bottom of
the chat; tapping `🏠 Home` renders the dashboard without typing anything. Add `tests/cockpit/test_reply_keyboard.py`
asserting `_reply_keyboard_markup()` returns the expected structure and that each button label resolves to a handler.

---

## WI-2 — Kill the dead-end screens  [risk: low]

**Problem (verified):** slash paths for `/heartbeat` (`menu.py:378-387`), `/schedule` (`menu.py:390-397`),
`/alerts` (`menu.py:400-403`) return text-only with no back/home button — the user is stranded and must recall
another command. (Note: the *callback* paths `dh:/ds:/da:` exist, so this is specifically the slash path.)

**Required change:** introduce a `_home_kb()` helper returning an inline keyboard with at least `[🏠 Home]` (plus a
contextual `← Back` where a parent exists), and append it to EVERY leaf screen returned by a slash command or
callback. No screen may return bare text.

**Acceptance test:** every command in the registered list renders with a Home button. Add a parametrized test in
`tests/cockpit/test_no_dead_ends.py` that invokes each screen builder and asserts a non-empty `inline_keyboard`
containing a Home action.

---

## WI-3 — Wire the dead `deploy:` button + deploy-from-phone  [risk: low for prospector/haworks; FENCED for money/identity]

**Problem (verified):** `github_processor.py:109` emits buttons `callback_data="deploy:<repo>:<token>"` (replay
token scheme described `github_processor.py:50`), but `handle_callback` (`menu.py:465`) has no `deploy:` branch →
tapping does nothing.

**Deploy targets (verified):** `tie` web+dotnet → Fly.io (`the-introduction-exchange/web/fly.toml`,
`the-introduction-exchange/dotnet/fly.toml`, region `lhr`); `signalengine` → Northflank via GitHub Actions
(`signalengine/.github/workflows/deploy.yml`, push-to-main triggered); `prospector` → CI only, no deploy.

**Required change:**
1. Add `elif data.startswith("deploy:"):` to `handle_callback`. Parse `deploy:<repo>:<token>`, validate the token
   against the candidate set (per `github_processor.py:50`), then a **two-step confirm** (reuse the estate-restart
   confirm pattern at `menu.py:620-624`).
2. **Low-risk projects only (prospector, haworks):** on confirm, trigger the deploy (e.g. `flyctl deploy -a <app>`
   or `gh workflow run deploy.yml`) via a registry template (extend `acl.py:COMMAND_REGISTRY`, never inject raw
   text), stream status back, end with 🟢/🔴.
3. **FENCED — signalengine (money) / tie (identity):** the `deploy:` handler must NOT execute their deploy. Instead
   it calls `coordinator.open_task(...)` (WI-5) to raise a fenced approval task. Leave a clearly-commented hook
   `# FENCE: money/identity deploy → approval gate, Claude-only execution` so Claude wires the actual trigger.

**Acceptance test:** tapping a low-risk deploy button confirms → deploys → reports status. Tapping a deploy button
for `signalengine`/`tie` creates an `awaiting_approval` coordinator task and sends approve/cancel buttons; it does
NOT deploy. `verify_estate.sh:196-200` still passes (no money/identity execution trigger in `menu.py`).
Test: `tests/cockpit/test_deploy_handler.py`.

---

## WI-4 — Live CI/CD: see + re-run pipelines  [risk: low for low-risk repos; FENCED for money/identity]

**Problem (verified):** CI status is push-driven notifications only (`github_processor.py` parses `workflow_run`
→ 🟢/🔴/🟡 to Telegram); there is no trigger/retry. The CI/CD menu node exists only in the DEAD `ui_engine.py:164`.

**Workflows (verified):** `prospector/.github/workflows/ci.yml`, `signalengine/{ci,deploy}.yml`,
`haworks-platform` (ci/deploy/e2e/codeql/…), `the-introduction-exchange` workflows.

**Required change:** add a LIVE `/cicd` screen in `menu.py` listing recent runs per project (via `gh run list`
JSON or GitHub API) with status icons, and a `Re-run` inline button (`gh run rerun` / `workflow_dispatch`) for
**low-risk repos**. For money/identity repos, the Re-run button routes to the approval gate (WI-5), not a direct run.

**Acceptance test:** `/cicd` lists runs with 🟢/🔴 status and a Home button; Re-run on a low-risk repo re-triggers;
money/identity repos show "requires approval". Test: `tests/cockpit/test_cicd_screen.py` (mock `gh`).

---

## WI-5 — Feature intake: "build feature X" from the phone  [risk: low intake; fence enforced downstream]

**Problem (verified):** free-text → Otto *chat* only (`server.py:567-576`); it never opens a work item. The
coordinator pipeline (diagnose → execute → verify → escalate → approve) exists but has no phone front door.

**Required change:** add an explicit `➕ Request` affordance — a reply-keyboard button and/or `/request <text>` —
that calls `coordinator.open_task(conn, title=<short>, body=<full text>, kind="injected")` (`coordinator.py:546`).
Distinguish "ask Otto a question" (stays chat) from "request work" (opens a task) by the explicit button, so there
is no ambiguity. The existing loop then diagnoses, drafts a remediation PR (`create_remediation_pr`,
`coordinator.py:207`), and returns a preview + Approve/Cancel buttons via `send_telegram_buttons`
(`coordinator.py:108`).

**FENCE (enforced, do not weaken):** `open_task`→`fence_class` (`coordinator.py:612`) already routes
money/identity/contract to `awaiting_approval`. The **approve write stays Claude-only** (`menu.py:833-839`). DeepSeek
implements INTAKE only — it must not auto-approve, must not bypass `fence_class`, must not call `C.approve()`.

**Acceptance test:** `➕ Request: add CSV export to prospector` opens a task → coordinator diagnoses → Telegram shows
a PR preview + Approve button. A money/identity request stops at `awaiting_approval` and cannot be approved from the
cockpit. Test: `tests/cockpit/test_feature_intake.py` (mock coordinator).

---

## WI-6 — Every project equal  [risk: low; read-only for money/identity beyond fence]

**Problem (recon):** only `prospector` has deep screens; `signalengine`/`tie`/`haworks` are thin tiles.

**Required change:** a single per-project view template driven by `~/.hermes/projects.json` rendering, for all 4:
status, last deploy, current CI state (WI-4), daemons, recent activity. Money/identity projects render READ-ONLY
beyond the fence (no execution buttons; deploy/CI actions route through WI-5 approval).

**Acceptance test:** each of the 4 projects opens a consistent detail screen with a Home button.
Test: `tests/cockpit/test_project_views.py`.

---

## WI-7 — Proactive action pings  [risk: low]

**Required change:** when the coordinator escalates (already partially via `send_telegram_buttons`) OR a CI run
fails (`github_processor` `workflow_run` conclusion=failure), push a Telegram message carrying an inline action
button (Approve / View / Re-run) so the CEO acts in one tap rather than navigating.

**Acceptance test:** a simulated failing `workflow_run` event pushes a 🔴 message with a `Re-run`/`View` button.
Test: `tests/cockpit/test_proactive_pings.py`.

---

## WI-8 — Harden the state probe so it can never lie again  [risk: low; Claude reviews]

**Problem (verified):** `verify_estate.sh` reported `✅ OPERATIONAL` while (a) the door rejected the real user
(ACL allowlist held one id; rejects were silently dropped — now logged, `acl.py:68-80`) and (b) the nav bar was
broken (WI-1). The probe checked "webhook is set", not "a user can actually use it".

**Required change — add these checks to `~/.hermes/scripts/verify_estate.sh`:**
1. **ACL readout:** print the count of allowed Telegram user IDs; WARN (not silent) if 0 or 1, and FAIL if the door
   denies-all (empty allowlist) since that is functionally down.
2. **No called-but-undefined UI helper:** static check that every `_xxx()` called in `server.py`/`menu.py` resolves
   (catches exactly the WI-1 regression class). Minimum: `python -c "import sentinel.cockpit.server, sentinel.cockpit.menu"`
   import smoke + a grep that `_reply_keyboard_markup` (and any helper attached to a send) is defined.
3. **Render smoke:** import the dashboard builder and assert it returns a non-empty inline keyboard (door renders).

**Acceptance test:** probe exits 1 if the allowlist is empty, if a called UI helper is undefined, or if the cockpit
module fails to import; exits 0 only when a user could actually navigate. Claude reviews this item before merge.

---

## Definition of done (whole spec)

- `bash ~/.hermes/scripts/verify_estate.sh` exits 0 with the new WI-8 checks present and green.
- `pytest` (verify_build) green; new `tests/cockpit/*` included; paste the verdict lines.
- Fences intact: no money/identity execution trigger in `menu.py`; `task:approve` cannot write from the cockpit;
  no `gateway/**` edits; `verify_estate.sh` FENCES block still ✅.
- A fresh authorized user can, with zero typed commands: open the bot, see a button bar, tap to any project,
  deploy a low-risk project, see CI state, and file a feature request that lands in the approval gate.
