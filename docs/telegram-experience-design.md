# Hermes Telegram Experience — Complete Design

## Problem

After 3+ iterations, the Telegram menu still doesn't feel right because we've been fixing symptoms rather than designing the whole experience. We have:

- 68 dispatch handlers, 97 discoverable commands, 95 pinned messages
- Self-improvement infrastructure (7 tiers, 45 tests) that has NO Telegram surface
- A project registry (14 projects) bolted onto a single-project architecture
- Home screens that have swung from "too sparse" to "wall of text" to "triage" without a coherent philosophy

## Design Principles

1. **The bot is the cockpit, not the engine.** Telegram shows what matters; the backend does the work. Never expose implementation details.
2. **Attention-first, not information-first.** The bot's job is to tell you what needs YOU, not what exists.
3. **Natural language is primary. Buttons are shortcuts.** Every action must work by typing. Buttons are accelerators.
4. **Self-improvement must be VISIBLE.** If Otto is learning, the operator must see evidence of learning.
5. **Client view vs operator view.** Same data, different lens. Clients see their project. Operator sees everything.
6. **One action = one response.** No deep menu trees. Max 2 taps from Home to any action.

---

## PART 1: Information Architecture

### The 4-Panel Model

Every interaction resolves to one of 4 panels. No more, no less.

| Panel | Trigger | Shows |
|-------|---------|-------|
| **Home** | `/start`, `hi`, 🏠 | What needs attention NOW. Severity-ranked. |
| **Project** | Project name, tap project button | Single project: status, SDLC stage, quick actions |
| **Health** | `/health`, 🧠 | Otto score breakdown, invariants, compliance, learning evidence |
| **Action** | Any command | Result of an action + what to do next |

### Navigation

- **Home** is always one tap away (spine button)
- **Back** undoes the last navigation (nav stack preserved)
- **Type anything** to search or command (natural language router)
- No panel is ever more than 2 taps from Home

---

## PART 2: The 4 Panels — Detailed Design

### 2.1 HOME

```
🏠 Otto
─────────────────
🟢 All systems operational · $1.64 today

🔴 Needs attention
• Signal Engine — money project, 6w stale
• TIE — client project, 7w stale

🟡 Watch  
• RitualWorks — 12w no activity

🟢 Clear — Prospector, Haworks, Crux, Lux, PopDD, Sentinel

🧠 Learning — score 69% · 19 policies · 378 injections this week
─────────────────
[🔴 Signal] [🔴 TIE]
[🛠 Fix All] [📊 All Projects]
[🧠 Health] [➕ New]
[🏠 Home] [⚡ Actions] [🗺 Browse]
```

**Design notes:**
- Self-improvement summary ALWAYS visible on Home (🧠 Learning line)
- Critical section shows ONLY things needing human action
- Watch section shows things that MIGHT need action soon
- Clear projects are names only (no git branches, no CI details)
- Home is the ONE panel pinned in Telegram (always)

### 2.2 PROJECT (tap any project)

```
📁 Signal Engine 🔐
─────────────────
🟡 Dirty working tree · 6w since last commit
Money project — requires confirmation for all actions

SDLC: Assign → Board → Fleet → Review → Ship → Learn

Recent activity:
• 3 missions blocked · 0 inflight tasks
• Last deploy: 6w ago

Quick actions:
[🛠 Clean up] [📊 SDLC] [📜 History]
[🧠 Health] [⚙️ Config]

🧠 Learning impact:
• 2 policies cover this project
• Last injection: today · relevant
─────────────────
[🏠 Home] [⚡ Actions] [🗺 Browse]
```

**Design notes:**
- Self-improvement context: which policies cover this project, when they last fired
- Actions are contextual to the project state (dirty → "Clean up", CI failing → "Fix CI")
- Client mode hides SDLC details, shows "Status: Healthy" or "Status: Needs attention"

### 2.3 HEALTH (🧠 button or `/health`)

```
🧠 Otto Health — 69%
─────────────────
Auto-fixes     ████████░░  67%  4 pauses this week
Injections     ██████████  99%  375/378 relevant
Policy firings ████░░░░░░  40%  2 firings this week  
Learning       ██████████ 100%  14 new policies
Estate         ████░░░░░░  40%  Paused + degraded
Cron           ██████░░░░  59%  3 failing jobs

🛡️ Invariants: ✅ All 7 passing
📊 Outcomes: 100% success (1 task, 0 failures)
📋 Policies: 19 active / 50 ceiling · 19 unscoped
📜 Compliance: Otto v1.0.0 · 0 snapshots · Rollback: None

Weekly evidence of learning:
• Created pol-auto-api-credits (Aug 2)
• Created pol-auto-engineering-reliability (Jul 30)
• 378 policy injections · 99.2% relevant
• Regression corpus: 47KB · holdout split active
─────────────────
[📊 Details] [📜 Compliance Report]
[🏠 Home] [⚡ Actions] [🗺 Browse]
```

**Design notes:**
- Every health dimension visible with sparkline bars
- Self-improvement evidence section: "Here's what Otto learned this week"
- Constitutional invariant status always visible
- Compliance one tap away

### 2.4 ACTION (result of any command)

```
🛠 Fix All — Results
─────────────────
✅ Prospector — moat health check passed
⚠️ Signal Engine — repo dirty, no automatic fix
   → Recommend: commit or stash changes
✅ Cron — 2 orphaned jobs cleaned up
❌ TIE — identity project, manual review required

What next?
[🔍 Diagnose remaining] [📊 Full report]
[🏠 Home]
```

**Design notes:**
- Action results show what happened AND what to do next
- Never leave the operator stranded
- Failed actions explain WHY and suggest next step

---

## PART 3: Self-Improvement Visibility in Telegram

This is the critical missing piece. All 7 tiers exist but are invisible.

### What the operator sees

| Tier | Telegram Surface | Where |
|------|-----------------|-------|
| T0a Outcomes | "📊 Outcomes: 85% success rate, improving" | Health panel |
| T0b Cron | "⏰ Cron: 3/23 jobs failing · 2 orphans" | Health panel |
| T0c Invariants | "🛡️ Invariants: ✅ All 7 passing" | Health panel |
| T1 Holdout | "Holdout pass rate: 72% · policies generalizing" | Health panel |
| T2 Costs | "💰 Self-improvement cost: $0.42 today" | Health panel |
| T3 Compression | "📋 Policies: 19/50 · 2 near-duplicates found" | Health panel |
| T4 Drift | "📉 Drift: No distributional shift detected" | Health panel |
| T5 Injection defense | "🛡️ Injection defense: 0 blocked this week" | Health panel |
| T6 Gap closing | "🔧 Gaps: 0 auto-closed, 2 escalated" | Health panel |
| T7 Identity | "📜 Otto v1.0.0 · 0 snapshots" | Health panel |

### Weekly learning digest (pushed to Telegram)

Every Monday morning, the bot sends:

```
🧠 Otto Weekly Learning Digest

This week Otto:
• Created 14 new policies
• Injected policies into 378 tasks (99.2% relevant)
• Fired 2 policy enforcements
• Auto-paused Prospector 4 times
• Scored 69% on self-assessment (↑ from 21% last month)

Most impactful policy:
pol-auto-api-credits — triggered 27 times, prevented credit exhaustion

Needs human attention:
• 2 escalated gaps in auth domain
• 3 failing cron jobs
• Holdout pass rate 72% — review missed cases
```

---

## PART 4: Natural Language Router

The bot must understand these without button navigation:

| User types | Bot does |
|-----------|---------|
| `hi`, `start`, `menu` | Show Home |
| `what's broken` | Show critical + watch items in detail |
| `prospector`, `tie`, etc | Open that project |
| `deploy prospector` | Trigger deploy for that project |
| `fix all` | Run fix-all across all projects |
| `health` | Show Health panel |
| `health prospector` | Show project-specific health |
| `onboard` | Start onboarding wizard |
| `onboard client acme` | Fast-track client onboarding |
| `learn` | Show learning digest |
| `compliance` | Show compliance report |
| `logs prospector error` | Search logs |
| `who is working on tie` | Show inflight tasks for that project |

Implementation: extend `natural_ops.py` match patterns, not a separate system.

---

## PART 5: Proactive Alerts

The bot should PUSH, not just respond.

| Trigger | Alert |
|---------|-------|
| CI fails | `🔴 Prospector CI failed — main branch` |
| Credit low | `🟡 API credits low — 27 warnings today` |
| Moat down | `🔴 Prospector moat down — pipeline blocked` |
| Policy firing | `🛡️ Policy fired: pol-api-credits blocked an action` |
| Cron failing 3+ times | `⏰ hermes-config-auto-push failing — needs attention` |
| Invariant violation | `🚨 INV-002 violated: credential leak detected` |
| Weekly digest | `🧠 Otto Weekly Learning Digest` (Monday 9am) |
| New project onboarded | `✅ Crux onboarded — 1 repo, low risk` |

---

## PART 6: Implementation Plan

### Phase 1: Home + Project panels (today)
- [x] Triage-based Home with severity classification
- [x] Project dashboard with client/operator modes
- [x] Auto-unpin old messages
- [ ] Add self-improvement line to Home

### Phase 2: Health panel (today)
- [ ] Build render_health() that calls ALL tier endpoints
- [ ] Wire `/health` and 🧠 button
- [ ] Add learning evidence section
- [ ] Weekly digest generator

### Phase 3: Natural language + proactive alerts
- [ ] Extend natural_ops.py with project-aware patterns
- [ ] Wire proactive alert triggers into gateway
- [ ] CI failure → Telegram push

### Phase 4: Polish
- [ ] Client mode toggle
- [ ] Onboarding wizard polish
- [ ] Remove remaining old panels (Atlas rooms fully deprecated)
- [ ] Test every dispatch path

---

## PART 7: What we STOP doing

- ❌ Flat lists of all projects with git status
- ❌ 97-command search palette
- ❌ Atlas rooms metaphor (Money/Code/Machine/Brain)  
- ❌ Multiple pinned messages accumulating
- ❌ Separate SDLC/Tune tabs (folded into project/health views)
- ❌ Exposing branch names and git details on Home
- ❌ Buttons that don't explain what they do
