# Hermes + Prospector Self-Improvement Architecture

## System Overview

Two independent recursive self-improvement loops that share data through integration points:

```
┌──────────────────────────────────────────────┐
│                 HERMES (Agent)               │
│  Otto Health Score · Policy Engine · Telegram│
│  Tier 0-7 Modules · RSI Control · Dashboard  │
└──────────────────┬───────────────────────────┘
                   │ turn_finalizer hook
                   │ outcome_tracker.py
                   │ integration.py cron
                   ▼
┌──────────────────────────────────────────────┐
│              PROSPECTOR (Engine)             │
│  Vetting Pipeline · MetricsStore · Canary    │
│  SelfModifyLog · KillDecay · Attribution     │
└──────────────────────────────────────────────┘
```

---

## PART 1: Hermes Agent Self-Improvement

### 1.1 Health Score (otto_health.py)
Location: `~/.hermes/hermes-agent/gateway/operator_shell/otto_health.py`
**6 dimensions, scored 0-1:**

| Dimension | Weight | What it measures | Data source |
|-----------|--------|-----------------|-------------|
| auto_fixes | 22% | Auto-pauses per moat incident | ops-monitor.jsonl |
| injection_relevance | 20% | Policies reaching tasks with relevant matches | injection-log.jsonl |
| policy_firings | 18% | Weekly enforcer activity | policy-firings.jsonl |
| learning | 15% | New policies created this week | policies/ directory |
| estate_health | 13% | PAUSE state + degradation + credit pressure | ops-monitor.jsonl + PAUSE file |
| cron_health | 12% | Active cron jobs with ok status | cron/jobs.json |

**FIXED BUGS:**
- Datetime comparison: naive vs aware silently dropped 378 injection entries → score was 21%, now 69%
- Auto-fix formula: denominator was all 92 ops events, changed to 6 moat events → 4%→67%
- Policy firings formula: was dividing by 378 injections, changed to weekly rate → 0.5%→40%

### 1.2 Tier 0-7 Infrastructure (scripts/)

| Tier | Module | Purpose | CLI |
|------|--------|---------|-----|
| T0a | `outcome_tracker.py` | Task-level success/failure with domain partitioning, auto-detection, human validation queue | `python3 scripts/outcome_tracker.py stats` |
| T0b | `auto-push.sh` | Git lock handling, cron delivery fix | Runs as cron job |
| T0c | `constitutional_validator.py` | 7 immutable invariants, separate enforcement process | `python3 scripts/constitutional_validator.py` |
| T1 | `holdout_eval.py` | 70/30 train/holdout corpus split, policy attribution with before/after measurement | `python3 scripts/holdout_eval.py split` |
| T2 | `cost_policy_mgmt.py` | Self-improvement credit/latency tracking, auto-throttle | `python3 scripts/cost_policy_mgmt.py costs` |
| T3 | `cost_policy_mgmt.py` | Policy compression (Jaccard dedup), domain scoping, 50-policy ceiling | `python3 scripts/cost_policy_mgmt.py analyze` |
| T4 | `quality_defense.py` | Distributional drift detection (entropy shift, EMD distance), auto-pause on degradation | `python3 scripts/quality_defense.py check-drift` |
| T5 | `quality_defense.py` | 7 suspicious pattern detectors, content sanitization, policy validation | `python3 scripts/quality_defense.py sanitize` |
| T6 | `auto_close_identity.py` | Gap→policy auto-close pipeline (low-risk auto-promote, medium shadow-deploy, high escalate) | `python3 scripts/auto_close_identity.py identify-gap` |
| T7 | `auto_close_identity.py` | Agent versioning (semver), snapshots, rollback, compliance reports | `python3 scripts/auto_close_identity.py version` |

### 1.3 Self-Improvement Loop (self_improve_runner.py)
Location: `~/.hermes/scripts/self_improve_runner.py`
**Runs hourly via cron. All in-process imports, zero subprocess.**

Pipeline:
```
1. gap-finding.py → find_gaps() → auto_close_gaps()
2. meta-improver.py → load_metrics() → track_outcome() → append_metric()
3. self-regression.py → run_regression() → auto_fixer.auto_fix_all()
4. outcome_tracker.py → measure_policy_effectiveness()
5. health_panel.py → render_weekly_digest() → Telegram push (Mondays only)
```

### 1.4 Safety Net
| Layer | File | Purpose |
|-------|------|---------|
| Pre-flight | `preflight.py` | 40 module imports + dispatch route safety check before restart |
| Safe restart | `safe-restart.sh` | Preflight → clear cache → restart → post-flight error scan |
| Health monitor | `health_monitor.py` | Every 5min: gateway alive, no crash errors, dispatch responding → Telegram alert |
| Auto-guard | `auto-guard.sh` | File watcher: on change → preflight → safe restart |


## PART 2: Prospector Engine Self-Improvement

### 2.1 Modules (prospector/)
Location: `~/Documents/code/prospector/prospector/`

| Module | Purpose | Key functions | Tests |
|--------|---------|--------------|-------|
| `metrics_store.py` | Time-series metrics: yield, diversity, health trends, 4 alert types | `record_run()`, `trend()`, `alert_check()` | 9 |
| `self_modify.py` | Audit log for self-modifications, rollback, config snapshots | `record()`, `rollback()`, `snapshot()`, `restore()` | 13 |
| `attribution.py` | Welch's t-test paired comparison, effect sizes, significance | `measure_effect()`, `attribute_all_active()` | 4 |
| `simulation.py` | Deterministic mock pipeline, adaptation vs baseline comparison | `simulate_runs()`, `SimulationHarness.run_batch()` | 5 |
| `canary.py` | A/B canary runner, auto-promote/revert, statistical decision | `start_canary()`, `evaluate()`, `promote()`, `revert()` | 5 |
| `kill_decay.py` | Exponential kill reason decay, Shannon entropy diversity floor, re-seeding | `get_active_steers()`, `check_diversity_floor()` | 10 |

### 2.2 Integration Point
Wired into `prospector/run.py` line ~806: after every vet batch completes, MetricsStore records yield rate, kill-by-gate, and diversity score automatically.


## PART 3: Telegram UI Architecture

### 3.1 Dispatch System (estate.py)
Location: `~/.hermes/hermes-agent/gateway/operator_shell/estate.py`
**74 dispatch handlers in `_dispatch()` function. Module-level imports prevent scope bugs.**

Key routes:
| Route | Action | Panel | Module |
|-------|--------|-------|--------|
| `refresh`, `mission`, `""` | Home | Triage + self-improvement summary | `status_engine.py` (cached) |
| `health` | Health | 6 dims + Tier 0-7 evidence | `health_panel.py` |
| `rsi`, `learning`, `self_improve` | RSI Control | Monitor/configure/steer | `rsi_control.py` |
| `rsi_goals` | RSI Goals | View active goals + progress | inline in estate.py |
| `rsi_changes` | Changes | Health trend + effectiveness history | `rsi_control.py` |
| `rsi_run` | Trigger Cycle | Run self-improvement cycle now | `rsi_control.py` |
| `rsi_pause` / `rsi_resume` | Pause/Resume | Toggle OFF_SWITCH file | `rsi_control.py` |
| `dashboard` | Web Link | Current tunnel URL | inline in estate.py |
| `compliance` | Compliance | Identity, invariants, governance | `auto_close_identity.py` |
| `help` | Help | All 20+ commands in 5 sections | `discovery.py` |
| `commands` | Quick Actions | 8 essential commands | inline in estate.py |
| `project:<key>` | Project Dashboard | SDLC, CI, actions | `projects.py` |
| `client_mode:<key>` | Client View | White-label project view | `commercial_ui.py` |
| `operator_mode` | Operator View | Back to full operator view | `commercial_ui.py` |
| `deploy:<key>` | Deploy | Trigger CI workflow | inline in estate.py |
| `onboard` | Onboarding | Conversational wizard | `commercial_ui.py` |
| `find` | Projects Map | All projects with health | `atlas.py` (repurposed) |

### 3.2 Natural Language Router (chat_router.py + commercial_ui.py)
Hierarchy:
1. `natural_ops.py` matcher (existing, ~50 patterns)
2. `NaturalRouter.match()` (new, 16 patterns) — catches what natural_ops misses
3. Fallback: discovery suggestions

Type any of these:
- `deploy prospector` → deploys Prospector
- `what's broken` → triage Home
- `fix all` → auto-fixer
- `show tie` → TIE dashboard
- `client prospector` → white-label Prospector view
- `health` → self-improvement score
- `what did otto learn` → weekly digest

### 3.3 Discovery & Hints (discovery.py)
Every panel ends with contextual hints:
```
💡 Try typing:
• `what's broken` — see what needs attention
• `deploy prospector` — trigger a deploy
• `health` — see Otto's self-improvement score
```

Help command shows all 20+ capabilities in 5 sections: Home & Status, Projects, Actions, Self-Improvement, Discovery.

### 3.4 Telegram Menu
14 commands registered (operator mode): panel, status, **health**, **dashboard**, inbox, fleet, brief, cron, busy, notify, revert, missions, help, sethome.

### 3.5 Message Hygiene
- pin_edit=False — no more auto-pinning, every message is fresh
- Auto-unpin code exists in telegram.py (lines 4460, 6580)


## PART 4: Web Dashboard

URL: `https://<tunnel>.trycloudflare.com` (tunnel auto-restarts)
Location: `~/.hermes/mini-app/index.html` + `~/.hermes/scripts/mini_app_server.py`

### 4.1 5 Tabs
| Tab | Content | API |
|-----|---------|-----|
| 📊 Overview | Health score gauge, 6-dim breakdown, activity feed | `/api/health`, `/api/status`, `/api/metrics` |
| 🔬 Pipeline | 5 Prospector gates, score components | `/api/status` |
| 🚨 Incidents | Active incidents with assign/comment | `/api/incidents` |
| 💡 Insights | AI-generated estate insights | `/api/insights` |
| 🛡️ Ops | Invariants, task outcomes, policy corpus, compliance | `/api/invariants`, `/api/outcomes`, `/api/policies_status`, `/api/compliance` |

### 4.2 10 API Endpoints
health, status, incidents, metrics, insights, team, outcomes, invariants, policies_status, compliance — all return valid JSON.

### 4.3 Server
`ThreadingHTTPServer` on port 8800 (fixed from single-threaded HTTPServer that caused "Loading..." forever).


## PART 5: Project Registry

Location: `~/.hermes/projects.json`
**14 projects registered: 6 active, 4 incubating, 4 archived.**

| Project | Type | Risk | CI | Repos |
|---------|------|------|-----|-------|
| Prospector | product | low | github | 3 |
| Haworks Platform | product | low | github | 1 |
| Signal Engine | product | money | github | 1 |
| TIE | client | identity | github | 1 |
| RitualWorks | product | low | github | 1 |
| Portfolio Site | product | low | github | 1 |
| Crux | incubating | low | — | 1 |
| Lux | incubating | low | — | 3 |
| PopDD | incubating | low | — | 2 |
| Sentinel Loop | incubating | low | — | 1 |

### 5.1 Status Engine
Location: `~/.hermes/scripts/status_engine.py`
Background daemon refreshes every 60s. Pre-computes git status, CI status, commit age, severity classification. Home panel reads from cache — 17ms render, no git I/O.


## PART 6: Data Flow — How Everything Connects

```
Agent Task Completes
    │
    ├── turn_finalizer.py → OutcomeTracker.record() ──┐
    │                                                   │
    ├── self-detect.py → failure? → reflect → policy   │
    │                                                   │
    └── coordinator.py → _record_task_outcome() ────────┤
                                                        │
                                              ┌─────────▼──────────┐
                                              │  task-outcomes.jsonl│
                                              └─────────┬──────────┘
                                                        │
                              ┌─────────────────────────┼─────────────────────┐
                              │                         │                     │
                    ┌─────────▼────────┐    ┌───────────▼──────────┐  ┌──────▼────────┐
                    │ PolicyAttribution │    │ DistributionalMonitor│  │ OutcomeTracker│
                    │ (before/after)    │    │ (drift detection)    │  │ (stats)       │
                    └─────────┬────────┘    └──────────────────────┘  └──────┬────────┘
                              │                                              │
                              └──────────────────┬───────────────────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │   change-outcomes.jsonl  │
                                    │   (meta-improver input)   │
                                    └────────────┬────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │   self_improve_runner.py │
                                    │   (hourly cron)          │
                                    │   gap-find → regress →   │
                                    │   meta-improve → digest  │
                                    └──────────────────────────┘
```


## PART 7: Known Gaps & Limitations

| Gap | Severity | Detail |
|-----|----------|--------|
| Outcome data sparse | High | Only 10 task outcomes recorded. Need coordinator tasks to complete through the hook path. |
| Policy effectiveness 0% | High | No per-domain outcome data to measure against. Will improve as outcomes accumulate. |
| 3 failing cron jobs | Medium | hermes-config-auto-push (71 heal attempts), summarizer (463), strategist-audit (382) |
| CI watcher not pushing | Low | Code exists, not wired to active push yet |
| Web dashboard tunnel URL changes | Low | Cloudflare tunnels are ephemeral. Consider ngrok paid or custom domain |

## PART 8: Verification

```bash
# Full pipeline verification (53 checks):
python3 scripts/verify_pipeline.py

# Self-improvement cycle:
python3 scripts/self_improve_runner.py --all

# Pre-flight before restart:
python3 scripts/preflight.py

# Safe restart:
./scripts/safe-restart.sh
```
