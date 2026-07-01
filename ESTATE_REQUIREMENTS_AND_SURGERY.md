# ESTATE REQUIREMENTS & SURGERY — work backwards from what the founder needs

*2026-06-25. Companion to `ESTATE_NORTH_STAR.md` and `ESTATE_FEATURE_ROADMAP.md`. Every reality
claim is backed by `file:line` / command output re-run on disk today. Each surgical step carries an
ACCEPTANCE TEST — proof of done, not theater. No code has moved.*

---

## A. THE REQUIREMENTS (the spine that never existed — reconstructed from the founder's own words)

> "I'd like to be able to manage my core projects — prospector, tie, signalengine — building new
> features, managing daemons, reports… the cockpit, the otto agent with skills, daily goal,
> self-improvement… and proof that things are being done."

| # | Requirement | Acceptance (what "satisfied" looks like) |
|---|---|---|
| R1 | **Operate the 3 core projects from Telegram** | From the phone: see status, trigger a feature/run, unblock — for prospector, tie, signalengine |
| R2 | **Manage daemons from Telegram** | See alive/dead; start/stop/restart any daemon from the phone |
| R3 | **Reports on the phone** | Daily/audit reports are delivered to Telegram, not buried in logs |
| R4 | **Run Otto** | Skills, daily goal, self-improvement plan — all visible and controllable from the phone |
| R5 | **Proof, not theater** | Every "done" carries machine-verified evidence. POPDD demonstrably runs on prospector/DeepSeek |

**The surgical test for every component in the estate:** *does it serve R1–R5?* If yes → wire it ON
and prove it. If no → amputate or park it. Nothing stays "built but dark."

---

## B. CURRENT REALITY, MAPPED TO THE REQUIREMENTS (proven today)

| Req | Status | Evidence |
|---|---|---|
| R1 prospector | 🟡 alive but not from phone for *features* | daemons PID 15362/15684; `com.prospector.scheduler`+`watchdog`; 22 cockpit refs (`menu.py`) — but only trigger/status, no feature mgmt |
| R1 signalengine | 🔴 dormant + invisible | no process; **0** cockpit refs; last commit 2026-06-20; coordinator `risk_class: money` |
| R1 tie | 🔴 dormant + invisible | no process; `com.tie.ai-review` plist not running; **0** cockpit refs; last commit 2026-06-12; `risk_class: identity` |
| R2 daemons | 🟡 partial | cockpit `/daemon` view exists (`menu.py`); start/stop/restart callbacks dropped (`menu.py:440-478` has no `estate:`) |
| R3 reports | 🔴 broken delivery | `glob` NameError breaks audit-report attach (`otto-inbound/__init__.py:352`, per North Star §6) |
| R4 skills | 🟢 real | 192 skills `~/.hermes/skills/`; invoked `agent.log` 2026-06-20 08:40 |
| R4 daily goal | 🔴 paused | cron `goal-of-the-moment` `enabled=False`; goal file stale 2026-06-19 |
| R4 self-improvement (RSI) | 🔴 disarmed | `OFF_SWITCH absent` `rsi-autorun.log` 2026-06-25T04:30; last real run 2026-06-21 |
| R5 POPDD on prospector | 🔴 **OFF — founder was right** | last receipt `prospector/.lux/receipts/2026-06-17.jsonl` (Jun 17); 20+ commits Jun 20–21 with **no receipts**; `.git/hooks/pre-commit` **not installed**; DeepSeek (`run_v2.py`) doesn't call the gate |
| R5 audit signing | 🟡 works but fenced | `evidence_verify.py` functional; gated behind `OFF_SWITCH` (absent) |
| R5 inline claims gate | 🔴 unwired | `hermes_claims.py` only ref'd by `tests/test_dropped_ball.py:7` |

**The three diseases, named:**
1. **Control plane is split** — the live cockpit cannot drive the estate (callbacks dropped).
2. **Proof plane is off** — POPDD not installed on prospector; RSI disarmed; inline gate unwired. *This is the one the founder explicitly distrusts, and the distrust is correct.*
3. **Project plane is uneven** — only prospector lives; signalengine + tie are dormant and off-phone.

---

## C. THE SURGERY (sequenced; each phase has a proof-of-done)

### Phase 0 — Safety. Free, zero-risk, needs no decision.
- Disable the gateway plist (`ai.hermes.gateway.plist`: add `<key>Disabled</key><true/>`).
- Commit the untracked daemon launchers into `~/.hermes/.git`.
- **Acceptance:** plist shows Disabled; `git -C ~/.hermes status` shows launchers tracked.

### Phase 1 — Turn the PROOF plane ON. The trust fix. Needs NO architecture decision — can start now.
- Install prospector's gate: symlink `.lux/hooks/pre-commit` → `.git/hooks/pre-commit`.
- Make the DeepSeek prospector workflow invoke the LUX gate (`run_v2.py` → `ci-gate.sh`) so every run emits a receipt.
- Backfill: run the gate on current `HEAD` to produce a proof for the un-receipted Jun 20–21 work.
- **Acceptance:** a new `prospector/.lux/receipts/2026-06-25.jsonl` exists for HEAD; a commit with no passing proof is **blocked** by the hook.

### Phase 2 — Make the CONTROL plane single. Needs Decision A.
- Port `task:` / `estate:` / `update_prompt:` branches into `menu.py:handle_callback` (logic reference: gateway `telegram.py:4082-4176`). Estate-pause already exists server-side (`coordinator.py:1565`).
- Add `/tasks` (escalated list + approve/reject) and `unblock_mission()`.
- **Acceptance:** tapping Approve on the phone moves an escalated task → `executing` in `coordinator.db`; tapping Pause sets `set_estate_paused(True)`.

### Phase 3 — VISIBILITY plane (R2/R3).
- `/cron` (surfaces the paused goal job + the job erroring since Jun 23), `/fuel` (spend), daemon start/stop, satellite tiles for signalengine + tie.
- Fix the audit-report `glob` NameError (`otto-inbound/__init__.py:352`).
- **Acceptance:** `/cron` lists the paused + erroring jobs; a report lands in Telegram.

### Phase 4 — OTTO liveness (R4). Deliberate re-arm, not drift.
- Re-enable `goal-of-the-moment` (or cut it — Decision). Decide RSI: arm `OFF_SWITCH` deliberately or keep fenced (money/safety call).
- **Acceptance:** daily goal posts to Telegram, or it is explicitly removed.

### Phase 5 — PROJECT scope (R1). Needs Decision C.
- signalengine + tie: either wire into the cockpit (status + trigger) OR explicitly **park** them with a documented "mothballed, not abandoned" status so they stop reading as unjustified complexity.

---

## D. THREE DECISIONS THAT GATE THE SURGERY (founder's call — recommendations given)

- **(A) Single Telegram door** — *recommend: finish into the cockpit* (live, webhook-secured, self-healing; reviving the gateway re-arms the two-poller `deleteWebhook` landmine). Gates Phase 2.
- **(B) Source of truth** — *recommend: bless `~/.hermes/.git`* (matches what runs; least disruption). Not on the critical path — can be deferred.
- **(C) Project scope** — ✅ **DECIDED 2026-06-25: both signalengine and tie are ACTIVE goals.** Phase 5
  wires all three (prospector, signalengine, tie) into the cockpit with status + trigger. signalengine
  (`risk_class: money`) and tie (`risk_class: identity`) must pass the proof gate before any execution
  is enabled for them — never run money/identity work unproven.

**Phase 0 and Phase 1 need none of these — they are the trust fix and they can start immediately.**
