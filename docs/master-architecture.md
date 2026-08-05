# Otto — Complete System Architecture v3.0

> For external audit by Gemini. Last updated: 2026-08-03

---

## 1. System Overview

Two independent recursive self-improvement loops connected through shared data:

```
┌──────────────────────────────────────────────────────────────┐
│                    HERMES AGENT (Otto)                        │
│  • Telegram Bot (74 dispatch routes, 14 menu commands)       │
│  • Web Dashboard (FastAPI v2.0, JWT-secured, 10 endpoints)   │
│  • Policy Engine (19 active policies, injection system)      │
│  • Self-Improvement (7 tiers, hourly cron)                   │
│  • Project Registry (14 projects, status engine)             │
│  • Outcome Tracker (SQLite WAL, 14 rows)                     │
└────────────────────────┬─────────────────────────────────────┘
                         │ turn_finalizer hook
                         │ coordinator completions
                         │ outcome_tracker.py
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  PROSPECTOR ENGINE                            │
│  • Business Vetting Pipeline (6 grounded checks)             │
│  • MetricsStore (time-series, 4 alert types)                 │
│  • SelfModificationLog (rollback, config snapshots)          │
│  • KillDecay (exponential decay, diversity floor)            │
│  • SimulationHarness (deterministic mock mode)               │
│  • CanaryRunner (A/B testing with statistical decisions)     │
│  • Causal Attribution (paired comparison, effect sizes)      │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Hermes Agent — Self-Improvement Tiers

### 2.1 Health Score (6 dimensions, 0–1 scale)

| Dimension | Weight | Current | Data Source | Note |
|-----------|--------|---------|-------------|------|
| auto_fixes | 22% | 66.7% | ops-monitor.jsonl | Moat pauses per incident |
| injection_relevance | 20% | 99.2% | injection-log.jsonl | Policies reaching tasks |
| policy_firings | 18% | 40.0% | policy-firings.jsonl | Weekly enforcer activity |
| learning | 15% | 100.0% | policies/ directory | New policies/week (target: 7) |
| estate_health | 13% | 40.0% | ops-monitor + PAUSE file | Multi-factor |
| cron_health | 12% | 55.5% | cron/jobs.json | Healthy active jobs |

**Bugs fixed:** Datetime comparison (naive vs aware dropped 378 entries — score was 21%), auto-fix denominator (92→6 events), firing formula (ratio→rate).

### 2.2 Tier 0–7 Infrastructure

| Tier | File | Purpose | Key Functions |
|------|------|---------|--------------|
| T0a | `scripts/outcome_tracker.py` | SQLite-backed task outcome tracking (migrated from JSONL) | `record()`, `stats()`, `auto_detect_outcome()` |
| T0b | `scripts/auto-push.sh` | Git lock handling, cron delivery | `auto-push.sh` |
| T0c | `scripts/constitutional_validator.py` | 7 immutable invariants, separate enforcement | `validate()`, 7 check functions |
| T1 | `scripts/holdout_eval.py` | 70/30 train/holdout corpus split, policy attribution | `split_corpus()`, `measure_policy_effect()` |
| T2 | `scripts/cost_policy_mgmt.py` | Self-improvement credit tracking, auto-throttle | `CostTracker.record()`, `should_throttle()` |
| T3 | `scripts/cost_policy_mgmt.py` | Policy compression (Jaccard dedup), domain scoping, 50-policy ceiling | `PolicyCompressor.analyze()`, `compress()` |
| T4 | `scripts/quality_defense.py` | Distributional drift detection (EMD), n≥50 sample floor | `DistributionalMonitor.compare_distributions()` |
| T5 | `scripts/quality_defense.py` | 7 injection pattern detectors, content sanitization | `InjectionDefender.sanitize_task_content()` |
| T6 | `scripts/auto_close_identity.py` | Gap→policy auto-close (low auto-promote, medium shadow, high escalate) | `GapCloser.auto_close_if_safe()` |
| T7 | `scripts/auto_close_identity.py` | Agent versioning, snapshots, rollback, compliance reports | `AgentIdentity.snapshot()`, `compliance_report()` |

### 2.3 Self-Improvement Runner (hourly cron)

`scripts/self_improve_runner.py` — in-process pipeline, zero subprocess:

```
1. gap-finding.py → find_gaps() → auto_close_gaps()
2. meta-improver.py → load_metrics() → track_outcome()
3. self-regression.py → run_regression() → auto_fixer.auto_fix_all() [circuit breaker protected]
4. outcome_tracker.py → measure_policy_effectiveness()
5. health_panel.py → render_weekly_digest() → Telegram push (Mondays)
```

### 2.4 Safety Infrastructure

| Component | File | Function |
|-----------|------|----------|
| Circuit Breakers | `scripts/circuit_breaker.py` | 5 breakers, exponential backoff, stops infinite retry loops |
| Pre-flight | `scripts/preflight.py` | 40 module imports + dispatch safety before restart |
| Safe Restart | `scripts/safe-restart.sh` | Preflight → cache clear → restart → post-flight scan |
| Health Monitor | `scripts/health_monitor.py` | Every 5min: gateway, crash errors, dispatch response |

---

## 3. Telegram UI Architecture

### 3.1 Dispatch System

74 handlers in `_dispatch()` in `estate.py`. Module-level `with_nav` import prevents scope bugs.

**Key routes:**

| Route | Panel | Module |
|-------|-------|--------|
| `refresh` | Home (triage from status cache) | `status_engine.py` |
| `health` | 6-dim health + Tier evidence | `health_panel.py` |
| `rsi` | RSI control (monitor/configure/steer) | `rsi_control.py` |
| `rsi_goals` | Active RSI goals + progress | inline |
| `rsi_run` | Trigger self-improvement cycle | `rsi_control.py` |
| `dashboard` | Web dashboard link with auto-auth token | inline |
| `compliance` | Identity, invariants, governance | `auto_close_identity.py` |
| `help` | 20+ commands in 5 sections | `discovery.py` |
| `project:<key>` | Project dashboard (SDLC, CI) | `projects.py` |
| `client_mode:<key>` | White-label client view | `commercial_ui.py` |
| `deploy:<key>` | Trigger deployment | inline |
| `onboard` | Conversational onboarding wizard | `commercial_ui.py` |

### 3.2 Natural Language Router

Hierarchy: natural_ops.py → NaturalRouter (16 patterns) → fallback suggestions.

Type: `deploy prospector`, `what's broken`, `fix all`, `show tie`, `client prospector`, `health`, `what did otto learn`

### 3.3 Telegram Menu

14 commands registered (operator mode): panel, status, **health**, **dashboard**, inbox, fleet, brief, cron, busy, notify, revert, missions, help, sethome.

### 3.4 Message Hygiene

- `pin_edit=False` — no auto-pinning, fresh messages only
- Unpin-all code at telegram.py lines 4460, 6580

---

## 4. Web Dashboard (FastAPI v2.0)

### 4.1 Architecture

**Replaces:** `mini_app_server.py` (ThreadingHTTPServer) 
**Now:** FastAPI + uvicorn, JWT-secured, rate-limited

| Endpoint | Auth | Returns |
|----------|------|---------|
| `/api/health` | None | Health score (public) |
| `/api/v1/health` | Bearer / ?token= | Score + outcomes + invariants |
| `/api/v1/status` | Bearer / ?token= | Estate status |
| `/api/v1/outcomes` | Bearer / ?token= | Task outcome stats (SQLite) |
| `/api/v1/invariants` | Bearer / ?token= | Constitutional validator status |
| `/api/v1/policies` | Bearer / ?token= | Policy corpus analysis |
| `/api/v1/compliance` | Bearer / ?token= | Full compliance report |
| `/api/v1/circuit_breakers` | Bearer / ?token= | Breaker states |
| `/api/v1/rsi/goals` | Bearer / ?token= | RSI goals |
| `/` | None | Dashboard HTML (auto-auth via ?token=) |

**One-tap access:** Telegram 📱 Dashboard button generates URL with `?token=<key>` — opens fully authenticated.

### 4.2 Security

- Rate limiting: 100 req/min per token
- CORS: wildcard (auth protects endpoints)
- API docs disabled (no `/docs`)

---

## 5. Project Registry

`~/.hermes/projects.json` — 14 projects registered.

### 5.1 Active Products (6)
| Project | Risk | CI | Repos |
|---------|------|----|-------|
| Prospector | low | github | 3 |
| Haworks Platform | low | github | 1 |
| Signal Engine | money | github | 1 |
| TIE | identity (client) | github | 1 |
| RitualWorks | low | github | 1 |
| Portfolio Site | low | github | 1 |

### 5.2 Status Engine

`scripts/status_engine.py` — background daemon, refreshes every 60s. Pre-computes git/CI/severity. Home panel reads cache — 17ms render.

---

## 6. Prospector Engine

### 6.1 Modules

| Module | Purpose | Tests |
|--------|---------|-------|
| `metrics_store.py` | Time-series metrics, 4 alert types (yield_decline, gate_dominance, diversity_collapse, health_decline) | 9 |
| `self_modify.py` | SelfModificationLog + ConfigSnapshot + rollback | 13 |
| `attribution.py` | Welch's t-test paired comparison, effect sizes | 4 |
| `simulation.py` | Deterministic mock pipeline, adaptation vs baseline | 5 |
| `canary.py` | A/B canary runner, auto-promote/revert | 5 |
| `kill_decay.py` | Exponential kill reason decay, Shannon entropy diversity floor | 10 |

### 6.2 Integration

Wired into `prospector/run.py`: after each vet batch → MetricsStore.record_run() with yield rate, kill-by-gate, diversity.

---

## 7. Data Flow — Complete

```
Agent Task Completes
    │
    ├── turn_finalizer.py → OutcomeTracker (SQLite) ──┐
    ├── coordinator.py → _record_task_outcome() ───────┤
    └── self-detect.py → failure → reflect → policy    │
                                                       │
                                              ┌────────▼──────────┐
                                              │ outcomes.db (SQLite)│
                                              │ 14 rows, WAL mode  │
                                              └────────┬──────────┘
                                                       │
                         ┌─────────────────────────────┼─────────────────┐
                         │                             │                 │
               ┌─────────▼────────┐    ┌───────────────▼──────────┐      │
               │ PolicyAttribution│    │ DistributionalMonitor    │      │
               │ (Bayesian A/B)   │    │ (n≥50 sample floor)     │      │
               └─────────┬────────┘    └──────────────────────────┘      │
                         │                                               │
                         └───────────────────┬───────────────────────────┘
                                             │
                                ┌────────────▼────────────┐
                                │ change-outcomes.jsonl    │
                                │ (meta-improver input)     │
                                └────────────┬────────────┘
                                             │
                                ┌────────────▼────────────┐
                                │ self_improve_runner.py   │
                                │ (hourly cron)            │
                                │ [circuit breaker gates]  │
                                └──────────────────────────┘
```

---

## 8. Audit Response — External Recommendations

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | Runaway retries (463 heal attempts) | CRITICAL | ✅ Circuit breakers deployed (5 breakers, exponential backoff) |
| 2 | Drift detection on sparse data | HIGH | ✅ n≥50 minimum sample floor |
| 3 | JSONL without ACID | CRITICAL | ✅ SQLite WAL migration (14 rows, legacy archived) |
| 4 | Welch's t-test on small samples | HIGH | ✅ Bayesian A/B engine (Beta-Binomial, works on n=10) |
| 5 | Unauthenticated web endpoints | CRITICAL | ✅ FastAPI + JWT token auth deployed |
| 6 | Policy deduplication (Jaccard) | HIGH | 🔜 Vector embeddings + cosine similarity (needs embedding model) |
| 7 | Telegram router O(N) regex | MEDIUM | 🔜 Command pattern router (planned, not blocking) |

---

## 9. Known Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| Outcome data sparse (14 tasks) | Policy effectiveness 0% | Hooks wired, data accumulates automatically |
| 3 failing cron jobs | Cron health 55% | Circuit breakers stop retries, needs root cause fix |
| Ephemeral tunnel URL | Dashboard URL changes on restart | Named Cloudflare Tunnel or custom domain (one-time setup) |
| Policy injection broadcasts all policies | Context window bloat risk at 50+ policies | Domain-scoped injection + compression (T3) active |
| No vector-based policy retrieval | Semantic duplicates may bypass Jaccard | Vector store (Qdrant/pgvector) planned for Phase 3 |

---

## 10. Verification

```bash
# Full pipeline (53 checks)
python3 scripts/verify_pipeline.py

# Self-improvement cycle
python3 scripts/self_improve_runner.py --all

# Pre-flight safety gate
python3 scripts/preflight.py

# Safe restart
./scripts/safe-restart.sh

# Circuit breaker status
python3 scripts/circuit_breaker.py --list

# Bayesian A/B demo
python3 scripts/bayesian_ab.py --demo

# API server
OTTO_API_KEY=<key> ~/.hermes/hermes-agent/venv/bin/python scripts/api_server.py --port 8800
```

---

## 11. File Inventory

**New files created (this session):**

| File | Purpose |
|------|---------|
| `scripts/circuit_breaker.py` | Circuit breaker with exponential backoff |
| `scripts/bayesian_ab.py` | Bayesian A/B testing engine (Beta-Binomial) |
| `scripts/api_server.py` | FastAPI v2.0 production server |
| `scripts/outcome_tracker.py` | SQLite-backed task outcome tracker |
| `gateway/operator_shell/rsi_control.py` | RSI control panel for Telegram |
| `gateway/operator_shell/commercial_ui.py` | 6 commercial UI features |
| `gateway/operator_shell/discovery.py` | Discovery hints + help + fallback |
| `gateway/operator_shell/health_panel.py` | Health panel with Tier 0-7 evidence |
| `gateway/operator_shell/projects.py` | Project registry + Home + Dashboard |
| `state/rsi-goals.json` | 3 active RSI goals |
| `state/status-cache.json` | Cached project status (60s refresh) |
| `state/outcomes.db` | SQLite outcome database (WAL mode) |
| `docs/commercial-interface-spec.md` | UX specification |
| `docs/self-improvement-architecture.md` | Architecture document (this file) |
