# Otto Commercial Product Readiness Audit
**Date:** 2026-08-02
**Auditor:** Deep architecture review
**Scope:** Full product — 41 panels, 97 NL commands, 77 actions, 94 tests

---

## Executive Summary

Otto has the bones of a world-class estate manager. 94 automated tests prove every feature works. The self-improvement loop runs end-to-end. But the product has three fatal gaps that prevent it from being a commercial product:

1. **Discoverability Crisis** — 97 commands with no discovery mechanism. The user must memorize them.
2. **No Universal Estate Model** — Tightly coupled to one founder's specific projects (Prospector, Signal Engine, TIE). Can't plug in arbitrary companies.
3. **No User Journey** — Features were built bottom-up from engineering needs. No coherent user story ties them together.

These are fixable. The architecture is sound. What's missing is the product layer on top.

---

## Part 1: Current State Assessment

### 1.1 What works brilliantly

| Capability | Evidence |
|---|---|
| **Monitoring** | Ops-monitor detects moat failures, cron errors, credit exhaustion. Auto-pauses on 5+ consecutive failures. Push notifications via hermes send. |
| **Diagnosis** | `diagnose` runs multi-check diagnostics. Identifies root cause. Suggests fixes. |
| **Prediction** | `predict` forecasts credit exhaustion from error rate trends. |
| **Self-healing** | Auto-fixer restarts cron, coordinator, config-push. Verifies each fix. Creates learning policies. |
| **Self-improvement** | RSI armed. 19-phase idle pipeline. Score tracking (0-100). Policy creation from failures. |
| **Cross-project** | Estate health score. Failure correlation. Dependency map. |
| **Testing** | 94 automated acceptance tests. Every feature proven working. |

### 1.2 What's broken for users

| Problem | Severity | Detail |
|---|---|---|
| **Command discovery** | 🔴 Critical | 97 NL commands. Help card shows 8. `capabilities` shows JSON dump. No way to browse or search commands from the phone. |
| **No onboarding** | 🔴 Critical | New user sees a mission card with jargon. No tutorial, no setup wizard, no "first 5 minutes" guide. |
| **Feature overload** | 🔴 Critical | 41 panels. Spine shows 5 destinations. Everything else is hidden behind typed commands the user doesn't know exist. |
| **No universal config** | 🟡 High | Projects are hardcoded. Adding a new project requires code changes in 3+ files. |
| **Fragmented UX** | 🟡 High | Some features are CLI-only (scripts), some are panels, some are raw JSON output. No consistent interaction pattern. |
| **No user roles** | 🟡 High | CEO sees same panels as engineer. No way to customize what each user sees. |
| **No mobile-first design** | 🟡 Medium | Built for Telegram which IS mobile-first, but panels vary in length dramatically (100-1400 chars). No compact/expanded toggle. |

---

## Part 2: Product Vision

### 2.1 The Universal Estate Manager

Otto should manage ANY company's estate. The founder configures:

```yaml
# ~/.hermes/estate.yaml
estate:
  name: "Acme Corp"
  
  projects:
    - name: "web-platform"
      repo: "~/code/web-platform"
      health_checks:
        - type: git_status
        - type: ci_badge
          url: "https://github.com/acme/web-platform/actions"
      dependencies:
        - "postgres-db"
        - "stripe-api"
      sla:
        uptime_target: 99.9
        response_time_ms: 200
    
    - name: "data-pipeline"
      repo: "~/code/data-pipeline"
      health_checks:
        - type: process
          pattern: "data-pipeline"
        - type: log_check
          path: "~/logs/pipeline.log"
          error_pattern: "FATAL|CRITICAL"
      dependencies:
        - "s3-bucket"
        - "redis-cache"
  
  infrastructure:
    - name: "postgres-db"
      type: database
      health_checks:
        - type: tcp_connect
          host: "localhost"
          port: 5432
    
    - name: "redis-cache"
      type: cache
      health_checks:
        - type: tcp_connect
          host: "localhost"
          port: 6379
  
  ai_providers:
    - name: "claude"
      type: anthropic
      health_checks:
        - type: api_key_valid
        - type: credit_balance
    - name: "cursor"
      type: cursor_cli
      health_checks:
        - type: cli_health

  operators:
    - name: "Alice (CEO)"
      telegram_id: "123456789"
      role: executive
      panels: [dashboard, brief, status]
    - name: "Bob (Engineer)"
      telegram_id: "987654321"
      role: engineer
      panels: [diagnose, fix, logs, full]
```

### 2.2 User Journey

**Minute 1:** Alice installs Otto. Runs `otto setup`. Otto asks 5 questions: project paths, Telegram chat, AI providers. Generates `estate.yaml`. Starts monitoring.

**Minute 5:** Alice gets her first morning digest. "Good morning Alice. Web-platform: 🟢 healthy. Data-pipeline: 🔴 3 errors in last hour. Postgres: 🟢. Credits: Claude $14.23 remaining."

**Minute 10:** Data-pipeline goes down. Otto sends push: "🔴 Data-pipeline down — FATAL error in pipeline.log. Auto-restart failed (3 attempts). Root cause: disk full on /data. Fix: clear logs or expand volume."

**Minute 30:** Alice types `fix data-pipeline`. Otto guides her through clearing logs. Fix verified. System recovers. Otto writes a policy: "When disk usage >90% on /data → auto-clean logs older than 7 days → notify if still >80%."

**Week 1:** Alice checks `health`. Score: 87/100. "Web-platform uptime: 99.97%. Pipeline recovered in 12 minutes. 3 incidents this week, 2 auto-resolved."

---

## Part 3: Required Features

### Wave 1: Discoverability (critical — fixes the "how do I use this" problem)

| # | Feature |
|---|---|
| W1-1 | **Unified command palette** — Type `?` or tap a button → shows ALL available commands grouped by category with one-tap execution. Like VS Code command palette. |
| W1-2 | **Smart suggestions** — After each action, show "You might also want: ..." with 2-3 related commands. |
| W1-3 | **Recent/frequent commands** — Track what the user actually uses. Show top 5 on home screen. |
| W1-4 | **Onboarding wizard** — `otto setup` → 5 questions → working estate in 5 minutes. |
| W1-5 | **Contextual help** — Every panel has a `?` button that explains what this panel does and what to do next. |

### Wave 2: Universal Estate Model

| # | Feature |
|---|---|
| W2-1 | **estate.yaml config** — Declarative project/infra/provider/operator definitions. Zero code changes to add a project. |
| W2-2 | **Pluggable health checks** — git_status, process, tcp_connect, http_endpoint, log_check, api_key_valid, credit_balance, disk_usage, memory_usage. Each is a ~20-line function. |
| W2-3 | **SLA/SLO tracking** — Define uptime targets per project. Track actual vs target. Alert on breach. |
| W2-4 | **Multi-tenant** — One Otto instance can manage multiple estates (clients, environments). |
| W2-5 | **Template gallery** — Pre-built estate configs for common stacks: "Rails + Postgres + Redis", "Next.js + Vercel", "Python + AWS". |

### Wave 3: Incident Management

| # | Feature |
|---|---|
| W3-1 | **Incident lifecycle** — Open → Diagnosing → Fixing → Verifying → Resolved → Postmortem. Each stage has a panel. |
| W3-2 | **Auto-escalation** — If incident unresolved >30min, escalate to next operator. If >2h, call/webhook. |
| W3-3 | **Postmortem generation** — After resolution, Otto writes: what happened, why, how fixed, what policy prevents recurrence. |
| W3-4 | **On-call rotation** — Schedule who gets alerted when. "Alice Mon-Wed, Bob Thu-Fri, Charlie weekends." |

### Wave 4: Commercial Polish

| # | Feature |
|---|---|
| W4-1 | **Role-based panels** — Executive sees dashboard + brief. Engineer sees full diagnostic suite. Each role has a YAML config of allowed panels. |
| W4-2 | **Multi-channel alerts** — Telegram + email + Slack + webhook + PagerDuty. Configurable per severity. |
| W4-3 | **Reporting** — Weekly PDF summary. Monthly executive report. Quarterly SLA compliance. |
| W4-4 | **Billing/usage** — Track API costs per project. Budget alerts. Cost optimization suggestions. |
| W4-5 | **Audit log export** — Every action, decision, and fix is logged. Exportable for compliance (SOC2, ISO27001). |

---

## Part 4: User Story Map

```
DAY 1: ONBOARDING
├── Install Otto → `curl -sSL https://otto.sh/install | bash`
├── Run setup → `otto setup` (5 questions, 2 minutes)
├── Otto discovers projects → scans ~/code for git repos
├── First health check → "🟢 3 projects found. All healthy."
├── Morning digest configured → "I'll brief you at 9am daily."
└── First command learned → "Try: `status` for estate overview"

WEEK 1: LEARNING
├── Something breaks → "🔴 web-platform: CI failing"
├── User types `diagnose web-platform` → Root cause found
├── User types `fix web-platform` → Otto guides fix
├── Otto writes policy → "When CI fails with 'out of memory' → suggest increasing node heap"
├── User checks `health` → Score: 82. "Improving: 3 incidents, all resolved <10min."
└── User discovers commands → `help` shows palette, `features` shows all 30+ capabilities

MONTH 1: TRUST
├── Incident happens at 3am → Otto auto-fixes, user wakes to "Resolved: web-platform CI OOM"
├── Weekly report → "99.7% uptime. 12 incidents, 9 auto-resolved. $14.23 AI spend."
├── User adds new project → edits estate.yaml, Otto picks it up within 60 seconds
├── Score hits 90+ → "Your estate is healthier than 85% of Otto users."
└── User refers colleague → "It just works. I barely open panels anymore."
```

---

## Part 5: Implementation Priority

**Must do before anyone else can use this:**
1. Command palette (W1-1) — single most impactful UX fix
2. Onboarding wizard (W1-4) — without this, new users are lost
3. estate.yaml config (W2-1) — without this, it only works for one estate

**Should do for commercial viability:**
4. Role-based panels (W4-1)
5. Pluggable health checks (W2-2)
6. Smart suggestions (W1-2)

**Nice to have for enterprise:**
7. SLA tracking (W2-3)
8. Multi-channel alerts (W4-2)
9. Incident lifecycle (W3-1)
10. Audit log export (W4-5)

---

## Part 6: Immediate Actions

These can be built NOW and make the existing product usable TODAY:

1. **Command palette panel** — `?` or `commands` opens a searchable, grouped panel of all 77 actions
2. **"Did you mean?" suggestions** — After `diagnose moat` → "Try: `fix credits` or `predict`"
3. **Usage-based home screen** — Most-used commands appear as buttons on the mission card
4. **Setup wizard** — `otto setup` → asks 5 questions, writes config, starts monitoring
5. **Unified `help` that actually helps** — Groups commands by job: "I want to check health → `status`, `diagnose`, `estate health`"

---

## Verdict

**The engine is world-class.** 94 passing tests, self-improving, auto-healing, predictive. The product layer is missing. A user who doesn't know the 97 commands can't use it. Fix discoverability and onboarding, and this is a commercial product. Add universal estate config, and it works for ANY company.
