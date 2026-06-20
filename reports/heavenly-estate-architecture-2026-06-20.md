# The Autonomous Estate — holistic architecture (war-room, 2026-06-20)

**Founder demand (verbatim intent):** stop firefighting. One designed system you can TRUST to
run itself. DeepSeek = coordinator, Claude = strategist/spec-writer, MiniMax = executor, driven
from Telegram, tasks followed-up and completion reported back. Never again "remind me to
investigate." Self-improvement PROVEN, not claimed. Resilient and robust. Experience heavenly.

**The one principle that unifies all of it:**
> **Investigate-before-escalate. A human is pinged only for a DECISION, never for a DIAGNOSIS.**

Today the estate does the opposite: failure → handler fails → escalate to you. That single
inversion is the whole disease. Everything below removes it.

---

## Where we are (recon verdict, 2026-06-20)
- **Coordinator:** Otto-dispatch is a single-threaded 5-min cron relay. Reads failures, dedups,
  escalates. NOT a persistent coordinator; no task ownership, no follow-up. (`scripts/otto-dispatch.py`)
- **Strategist + Executor:** do not exist. Only comments ("escalate to strategist") and
  recovery-log events (`replan_no_strategist`). The 3-role design is aspirational.
- **Task store:** `kanban.db` (SQLite) EXISTS with full lifecycle (status, started_at,
  completed_at, consecutive_failures, worker_pid, last_heartbeat_at) — but NOTHING reads/writes it.
  `task-state/current_task.json` is a singleton; `recovery_log.jsonl` already has retry primitives
  (transient/logic/blocked classification, 3× backoff 2s/5s/15s).
- **Providers:** `config.yaml` → `providers: {}`, `fallback_providers: []`, default MiniMax-M3
  only. No per-role routing, no fallback. One 429 blocks the estate.
- **Telegram path (works for alerts):** queue (`hermes_queue.py submit`) → `otto-dispatch` →
  `hermes send --to telegram` (gateway IPC, liveness via the load-immune `os.kill` probe shipped
  this session).
- **Single biggest gap:** no persistent coordinator loop owning task lifecycle. Cron one-shot →
  escalate → done.

## Phase 0 — reliability foundation (DONE + PROVEN this session)
Commits `dc10e25`, `8f942d6`, `139ab4c`, `3914ce5`. Sensors no longer lie (load-immune
`os.kill` liveness, three-state UNKNOWN); the healer can't forge proof (actuator/verifier
separation — a fix may never write the field its verifier reads); no self-feeding alert loops
(watchdog-heals-watchdog broken); probes are read-only (enforced by `known_classes.validate()`
self-test that fails loud on pytest/npm/git/file-write); orphan subprocess class killed
(`run_bounded` process-group kill). **You cannot build a trustworthy autonomous worker on a
sensor that lies or a healer that forges — so this had to come first. It is proven against the
live estate, not a quieted box.**

---

## The architecture (roles map to a task lifecycle the coordinator owns)

```
failure fingerprint (queue)  ─┐
Telegram task ("Otto, do X") ─┴─►  COORDINATOR (DeepSeek V4, persistent daemon)
                                     owns kanban.db lifecycle: open→diagnose→spec→execute→verify→report
                                       │
                        ┌──────────────┼───────────────┐
                        ▼              ▼                ▼
                  STRATEGIST       EXECUTOR         VERIFIER
                  (Claude)         (MiniMax)        (the hardened resolver/probes)
                  root cause +     runs the spec    confirms condition absent across N ticks
                  exact steps +    returns evidence AND acceptance test passes — no self-grading
                  acceptance test
                        │              │                │
                        └──────────────┴────────────────┘
                                     │
                          report PROGRESS + COMPLETION ──► Telegram (one honest line)
                          escalate ONLY on: human-decision-required OR N cycles failed w/ evidence
```

- **Coordinator (DeepSeek V4)** — always-on daemon (NOT cron one-shot). For each failure or
  injected task: opens a `kanban.db` task, routes it, dispatches strategist→executor→verifier,
  polls status against a deadline/heartbeat, reports progress + completion to Telegram, follows
  up. This is the missing persistent loop. Reaps stalled workers (orphan-safe via `run_bounded`).
- **Strategist (Claude)** — invoked for DIAGNOSIS + a structured fix spec (root cause, exact
  steps, acceptance test). Does not execute. **Founder fence: money/identity/contract/migration
  tasks stay here and pause for one-tap human approval before execution.**
- **Executor (MiniMax)** — runs the strategist's spec, returns result + evidence. Bulk mechanical.
- **Verifier** — the alert-resolver/probes hardened in Phase 0. A task is "done" only when the
  condition is absent across N ticks AND the executor's acceptance test passes.

---

## Resilience layer (the "robust" you asked for — designed against failure, not hope)
1. **Per-role provider fallback chain.** Populate `config.yaml` `providers{}` + `fallback_providers[]`:
   coordinator deepseek→anthropic; strategist anthropic→deepseek; executor minimax→deepseek→gemini.
   A thin `route(role, prompt)` primitive rotates provider on 429/503/timeout.
2. **Task persistence = kanban.db is the source of truth.** A restart re-reads open tasks and
   resumes. No work lost on crash/restart (today's singleton JSON loses it).
3. **Retry with backoff + provider rotation** — wire the existing `recovery_log` primitives
   (transient/logic/blocked, 3× backoff) into the coordinator dispatch.
4. **Investigate-before-escalate** — coordinator inserts the strategist diagnosis step BEFORE any
   user ping. Escalate only when strategist says "human decision required" or N cycles fail with
   evidence attached.
5. **Heartbeats + deadlines** — each task carries expected_completion; a stalled executor is
   reaped (orphan-safe) and retried; never silently hangs.

## Proof plan (self-improvement PROVEN, not claimed)
- **Convergence:** `open_fingerprints == 0` across 3 consecutive morning briefings = "ahead of the fires."
- **Autonomy ratio:** % of failures resolved with NO human ping. Target rising; the
  "remind to investigate" count must trend to **0**. This is the metric that measures YOUR pain directly.
- **MTTR per fingerprint** trending down; **recurrence rate** — a fixed fingerprint must not
  reappear within 7 days (proves "fixes stay fixed").
- **Acceptance gate:** no fix is "done" until verifier confirms absent across N ticks AND
  acceptance test passes. No self-grading (the Phase-0 rule, now a system invariant).
- **CHAOS PROOF (resilience proven against the live fire):** a fault-injection harness that
  (a) kills the gateway, (b) returns 429 from the primary provider, (c) orphans a child. The
  estate must self-recover, fall back, and report — the test asserts recovery. Same philosophy
  as the war room: prove the design while the fire burns.

## Heavenly-experience enhancements (actively making it better, not just less-broken)
- **One honest line, not a storm.** Noise budget: one morning briefing + only completion/decision
  pings between. Everything else is absorbed.
- **"What Otto did overnight" digest** — proactive summary of autonomously-resolved tasks, so you
  SEE it working (trust-building).
- **Two-way Telegram task injection** — "Otto, port the PayPal refund flow" → coordinator opens a
  task → strategist specs → executor drafts → you get a PR link. Not just alerts.
- **Decision inbox** — when human input IS needed: a crisp A/B question with a recommendation and
  a one-tap answer, never "go investigate."
- **Confidence-tagged autonomy** — low-risk classes auto-execute; money/identity classes
  auto-DIAGNOSE + draft but pause for your approval (founder fence preserved, friction removed).
- **Self-improving registry** — when a NEW failure class is resolved, the coordinator proposes a
  `known_classes` entry (with a read-only probe — enforced by the Phase-0 guard) so next time it's
  auto-handled. The estate learns; recurrence approaches zero.

---

## Build plan — phased, each GATED BY PROOF (fresh-session work; not hour-38 of a marathon)
- **Phase 1 — Provider resilience (smallest, highest leverage; de-risks everything).**
  Populate `config.yaml` providers + per-role fallback; build `route(role, prompt)` with rotation
  on 429/503/timeout. **PROOF:** kill the primary provider mid-task; task still completes via fallback.
- **Phase 2 — Coordinator loop on kanban.db.** Persistent daemon (launchd) that opens/tracks/closes
  tasks; wire `kanban.db`; resume open tasks on restart. **PROOF:** task survives a coordinator restart.
- **Phase 3 — Investigate-before-escalate.** Insert strategist diagnosis between failure and any
  user ping. **PROOF:** seed a failure; autonomy ratio rises; zero "remind to investigate" pings.
- **Phase 4 — Executor + acceptance-gated completion + two-way Telegram injection.** **PROOF:**
  end-to-end "Otto, fix X" → completion report; chaos test green.
- **Phase 5 — Self-improving registry + overnight digest.** **PROOF:** a resolved NEW class becomes
  an auto-handled known class; recurrence within 7 days = 0.

**Recommended start:** Phase 1. It is small, it is the root of "not resilient," and every later
phase depends on a model call that can't be killed by one provider's rate limit.
