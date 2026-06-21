# Estate v2 — One Loop Runtime
_Architecture for a hands-off, Telegram-run autonomous estate. 2026-06-21. Grounded in `reports/ESTATE-AUDIT-2026-06-21.md`._

## The one idea

**Every piece of autonomous work in the estate becomes an instance of one contract — a Loop — and a single supervised runtime executes all of them with uniform terminal states and a uniform operator handoff.**

That's the whole design. Everything below follows from it. If you remember one sentence, it's that one.

## Why the estate is broken today (the diagnosis, not opinions)

The audit found `🔴 BROKEN`: 0 active tasks, 23/33 (69%) escalated into silence, every tick `advanced=0`, `notify_interval=0`, three daemons dead *again*, one mission stuck 3 days, zero operator projects shipped. Those are **symptoms of one structural fault:**

> The estate is a pile of independent mechanisms — the coordinator task loop, 22 cron jobs, missions, the war-room, the RSI tuner, the watchdog, the progress daemon — each with **its own state store, its own scheduler, and no shared rule for what happens when it can't finish.** So work escalates into a silent pile, daemons die unnoticed, two schedulers drift, state is smeared across three databases, and nothing the operator actually cares about gets done.

It isn't that the parts are bad. The gateway works, the coordinator works, the war-room is *proven*. **The failure is integration discipline.** You can't fix that with more parts — you fix it by making every part obey one contract and run on one spine.

## The contract: what a Loop is

A Loop is the loop-library feedback cycle made mandatory and observable. Every Loop instance declares:

| Field | Meaning | Why it kills a current failure |
|---|---|---|
| `trigger` | on-demand / scheduled / event | One trigger model replaces cron×22 + missions + ad-hoc |
| `scope` | read/write allowlist + `fence` flag | Money/identity/contract/migration → human-gated, structurally |
| `gate` | an **observable, re-runnable** acceptance check (a function, not a vibe) | Empty-spec tasks can't pretend to pass (R3) |
| `step` | one bounded, reversible action | No half-applied state |
| `verify` | re-run `gate` under recorded conditions | "It compiles" ≠ proof |
| `record` | append evidence to the Loop's ledger | Resumable; auditable |
| **`terminal`** | exactly one of: **success · no-op · blocked · approval · exhausted · stagnated** | The core fix |
| `handoff` | what each terminal does (below) | The estate stops going dark (R4) |
| `stop` | structural no-progress stop, not an invented timer | No runaway, no premature give-up |

**The invariant that fixes everything:** *a terminal state that is not `success`/`no-op` MUST emit an operator handoff.* Silence becomes structurally impossible.

| Terminal | Handoff |
|---|---|
| success / no-op | silent log |
| **blocked** | DM the operator a **specific question** ("Prospector clone needs a target dir — which?") |
| **approval** | DM with tap-to-approve/reject (the founder fence, finally surfaced) |
| **exhausted** | DM "tried N times, here's what I learned, your call" — never reported as success |
| **stagnated** | no measurable progress for K ticks → DM |

The `Otto audit` command I already shipped (`scripts/estate-audit.py`) is this contract's **reference implementation**: observe → assess against a fixed gate → emit one named verdict → hand off. The contract already runs. This isn't theory.

## The three layers

```
┌─ Operator Plane (Telegram) ──────────────────────────────┐
│  Uniform projection of Loop state. One surface for every │
│  pending handoff. Estate speaks first on any non-silent  │
│  terminal. "Otto audit / brief / approve / answer".      │
└───────────────▲──────────────────────────────────────────┘
                │ handoffs up, answers/approvals down
┌───────────────┴── Loop Runtime (the kernel) ─────────────┐
│  ONE supervised process. Owns the tick. Runs Loops.      │
│  Enforces the contract (terminal → handoff). ONE state   │
│  store. Self-heals: the liveness check is itself a Loop.  │
└───────────────▲──────────────────────────────────────────┘
                │ loads typed definitions
┌───────────────┴── Loop Library (the catalog) ────────────┐
│  Typed loop defs: audit · project · incident · maintenance│
│  · learning · decision. New capability = new def, not a  │
│  new daemon. War-room is the decision engine for hard/    │
│  fenced loops.                                            │
└──────────────────────────────────────────────────────────┘
```

1. **Loop Runtime (kernel).** Small, dumb, reliable: a tick that selects runnable Loops, runs one `step`, enforces the contract, persists. Cleverness lives in loop defs and the war-room, *never* in the kernel — a boring kernel is a kernel that doesn't crash.
2. **Loop Library (catalog).** The estate's capabilities as typed loop definitions. Adding "nightly changelog" or "incident sweep" = a 20-line def, not a new launchd agent with its own failure mode.
3. **Operator Plane.** Telegram output becomes a *projection* of Loop state, not hand-coded per feature. Today every view (`brief`, `backlog`, `decisions`) is bespoke regex+SQL; in v2 they're one query over the loop store. The estate **pushes** on every non-silent terminal — that's what makes it heavenly instead of a thing you have to poll.

## What v2 deletes (the brittleness, named and removed)

- **5 independent dying daemons → 1 supervised kernel + a liveness Loop.** watchdog/progress/rsi stop being separate launchd agents that die in silence; they become Loops the kernel runs and revives, and the kernel itself is launchd-`KeepAlive` + pings you if its own tick stalls. (Fixes R1's *recurrence*, not just one instance.)
- **Two schedulers (cron×22 + missions) → one tick.** Cron jobs become scheduled Loops. No more drift, no more cron-origin Telegram noise.
- **Three state stores → one loop store + an archive.** `kanban.db` is dead (0 rows) → delete. `coordinator.db` → the loop store. `state.db` (26 MB chat log) → archive, read-only.
- **The 23-task silent pile → impossible by contract.** Non-success terminals must hand off.
- **Empty-spec strategist → `blocked` is a real terminal with a question.** (R3)
- **Proven-but-unwired war-room → the `decision` engine for fenced/hard Loops.** (R5)
- **Estate that never speaks → operator plane pushes on every handoff.** (R4)

Every line of this section maps to a finding in today's audit. The design isn't aspirational; it's the audit, inverted.

## The missing heart: a Portfolio

The estate does **100% housekeeping** because nothing feeds it your real goals. v2 makes a **Portfolio** first-class: your projects are long-lived `project` Loops that decompose into work; housekeeping Loops are subordinate. The daily proactive brief = projection of portfolio progress + pending handoffs. *This is the one input only you can give — the actual project list. The architecture provides the slot; you fill it.*

## Migration — strangler, not big-bang (this is how I earn the "once and for all")

A rewrite is how you lose an estate. We strangle the old mess one provable step at a time; each step ships and is proven before the next:

1. **Contract + kernel interface** (spec + the audit-loop already proves the shape). ✅ shape proven.
2. **Wrap the existing coordinator tick as the first kernel host; add the terminal→handoff enforcement layer.** → instantly ends the 23-task silence (R3/R4) *without* rewriting anything. Highest leverage, lowest risk. **Do this next.**
3. **Migrate the 5 daemons into supervised Loops**, liveness first → fixes R1 recurrence.
4. **Fold cron×22 into scheduled Loops; delete `kanban.db`.**
5. **Wire war-room as the decision engine** for fenced/hard Loops.
6. **Introduce the Portfolio**; point the workforce at real projects.

Money/identity/contract/migration loops never leave Claude (founder fence). Nothing here touches the signalengine working tree.

## What I would deliberately NOT do (an architect is their "no"s)

- **Not** rewrite from scratch — the parts work; the integration doesn't. Strangler.
- **Not** add a daemon or a database — the brittleness *is* too many moving parts; v2 removes parts.
- **Not** make the kernel clever — dumb tick + contract enforcer. Intelligence is in loop defs and the war-room, where it can be tested in isolation.
- **Not** keep the empty-spec "try harder" behaviour — a loop that can't define its gate is `blocked`, and `blocked` asks you. Asking is a feature, not a failure.

## The one risk, and its mitigation

Consolidating 5 daemons into one kernel = one process whose death kills everything. Mitigation: the kernel is *tiny* and launchd-`KeepAlive`, and the **liveness Loop DMs you if the tick stalls** — which is precisely the alarm that's missing today (three daemons died and you found out from an audit, not a ping). One supervised heart with a pulse you can see beats five silent ones.

---
_Reference implementation already shipped: `scripts/estate-audit.py` + `Otto audit` (commit b8c2e97) — the Loop contract, running today. The next commit is step 2: terminal→handoff in the coordinator tick._
