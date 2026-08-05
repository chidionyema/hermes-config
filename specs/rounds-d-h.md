# Round D-H Implementation Spec
**Date:** 2026-08-02
**Delegate:** Builder ladder

## Files to create/modify

### New files:
- `~/.hermes/scripts/diagnostics.py` — Active diagnosis engine (E1-E4)
- `~/.hermes/scripts/predictor.py` — Predictive intelligence (D1-D4)
- `~/.hermes/scripts/resilience.py` — Operational resilience (F1-F4)
- `~/.hermes/scripts/feature_registry.py` — Feature registry (G1-G4)
- `~/.hermes/scripts/score_driver.py` — Score improvement engine (H1-H4)
- `~/.hermes/scripts/agent_simulator.py` — Simulated agent traffic (H2)
- `~/.hermes/tests/test_rounds_d_h.py` — Acceptance tests for all new features

### Modified files:
- `~/.hermes/hermes-agent/gateway/operator_shell/natural_ops.py` — Add new commands
- `~/.hermes/hermes-agent/gateway/operator_shell/estate.py` — Add new actions
- `~/.hermes/scripts/idle-learning-run.sh` — Add new phases

## Round D: Predictive Intelligence

### D1: Credit exhaustion predictor
**Script:** `predictor.py` function `predict_credit_exhaustion()`
**Logic:** 
- Scan errors.log for credit/rate-limit errors in last 6h
- Count events per hour, extrapolate
- If rate > 0, estimate time until next exhaustion
- Return: `{"provider": "cursor", "errors_last_6h": 12, "rate_per_hour": 2, "estimated_exhaustion_h": 3.5, "action": "Top up at cursor.sh/account"}`
**NL command:** `predict credits` → runs predictor, shows results

### D2: Failure correlation engine
**Script:** `predictor.py` function `correlate_failures()`
**Logic:**
- Load errors.log, ops-monitor.jsonl, watchdog.jsonl
- Group failures by 30-min windows
- Find clusters where 2+ failure types co-occur
- Return grouped failures with shared root cause hypothesis
- e.g.: "3 failure types in window 15:00-15:30: moat_preflight + cron_429 + anthropic_400 → shared cause: API credit exhaustion"

### D3: Anomaly detection
**Script:** `predictor.py` function `detect_anomalies()`
**Logic:**
- Load 14 days of daily snapshots from `~/.hermes/logs/self-audit/daily/`
- Compute baseline: mean ± 2σ for prospector_runs, errors, spend
- Flag today if outside baseline
- Return: `{"metric": "prospector_runs", "today": 3, "baseline_mean": 50, "baseline_std": 15, "anomaly": True, "direction": "below"}`

### D4: MTTR tracking
**Script:** `predictor.py` function `track_mttr()`
**Logic:**
- Parse ops-monitor.jsonl for moat_auto_pause and moat_auto_resume events
- Compute duration between pause and resume
- Track monthly averages
- Return: `{"outages_this_month": 3, "avg_duration_h": 4.2, "last_month_avg_h": 2.1, "trend": "worsening"}`

## Round E: Active Diagnosis

### E1: "Why is the moat down?"
**Script:** `diagnostics.py` function `diagnose_moat()`
**Logic:**
1. Check network: ping api.cursor.sh, api.anthropic.com
2. Check API: run `cursor_cli --health` or equivalent, capture output
3. Check credits: parse error messages for "usage limit" vs "credit balance" vs "rate limited"
4. Return structured diagnosis:
```json
{
  "status": "down",
  "checks": [
    {"check": "network", "status": "pass", "detail": "api.cursor.sh reachable"},
    {"check": "cursor_api", "status": "fail", "detail": "HTTP 402: usage limit reached"},
    {"check": "claude_api", "status": "fail", "detail": "HTTP 400: credit balance too low"}
  ],
  "root_cause": "Both Cursor and Claude credits exhausted",
  "fix": "1. Top up Cursor at cursor.sh/account\n2. Add Anthropic credits at console.anthropic.com\n3. Run `otto diagnose moat` to verify"
}
```
**NL command:** `diagnose moat` or `why is prospector failing`

### E2: "Why is the engine down?"
**Script:** `diagnostics.py` function `diagnose_engine()`
**Logic:**
- Check process: is signal engine daemon running?
- Check TCC: does python have Full Disk Access?
- Check API: can we reach the exchange API?
- Check balance: does the account have funds?
**NL command:** `diagnose engine` or `why is signal engine down`

### E3: "Fix my credits" guided flow
**Script:** `diagnostics.py` function `credit_fix_guide()`
**Logic:**
- Determine which providers are exhausted from recent errors
- Return step-by-step instructions with URLs
- Include estimated time and cost
**NL command:** `fix credits`

### E4: One-click diagnostic report
**Script:** `diagnostics.py` function `full_diagnostic()`
**Logic:**
- Run all diagnostic checks (moat, engine, cron, daemons, credits)
- Return single report card with pass/fail per check
- Summary line: "🔴 3 failures, 🟡 1 warning, 🟢 4 healthy"
**NL command:** `diagnose` or `otto diagnose` or `health check`

## Round F: Operational Resilience

### F1: ticks.jsonl rotation
**Script:** `resilience.py` function `rotate_ticks()`
**Logic:**
- If ticks.jsonl > 500KB, archive entries older than 30 days
- Write archived entries to `ticks-YYYY-MM.jsonl.gz`
- Truncate original to only last 30 days
- Log rotation event
**Called by:** idle-learning Phase 1 (preflight)

### F2: Coordinator DB health check
**Script:** `resilience.py` function `check_db_health()`
**Logic:**
- Run `PRAGMA integrity_check` on coordinator.db
- Check file size, warn if >50MB
- Run `PRAGMA optimize` if needed
- Return health status
**Called by:** idle-learning Phase 1 (preflight)

### F3: Backup verification
**Script:** `resilience.py` function `verify_backups()`
**Logic:**
- Check git remote is reachable
- Verify last push was <24h ago
- Validate config.yaml parses correctly
- Check MEMORY.md and policies/ are committed
**Called by:** idle-learning Phase 8 (postflight)

### F4: Graceful degradation
**Script:** `resilience.py` function `degradation_status()`
**Logic:**
- Check each subsystem independently
- Return which features are available vs degraded
- Panel shows: "🟢 Mission card · 🟢 Prospector panel · 🔴 Coordinator (DB down) · 🟢 Ops monitor"
**NL command:** `system health`

## Round G: Developer Experience

### G1: Feature registry
**Script:** `feature_registry.py` — static registry of all 28+ features
**Data structure:**
```python
FEATURES = [
    {"id": "mission-panel-stamp", "name": "Mission card panel_stamp", "round": "UI", "test": "test_mission_panel_stamp", "built": "2026-08-02"},
    ...
]
```
**NL command:** `features` or `what features exist`

### G2: Self-benchmark
**Script:** `feature_registry.py` function `run_benchmark()`
**Logic:**
- Run acceptance tests
- Measure latency of each panel render
- Report score trend
- Output: "24/24 tests passing · avg panel 12ms · score 0.21 ↑0.03"
**NL command:** `benchmark` or `otto bench`

### G3: Changelog auto-generation
**Script:** `feature_registry.py` function `generate_changelog()`
**Logic:**
- Read feature registry
- Read git log since last changelog
- Generate markdown: "## 2026-08-02 · Built 12 features · Score 0.21"
- Write to `~/.hermes/logs/CHANGELOG.md`
**Called by:** acceptance test suite on pass

### G4: "What can Otto do?"
**Script:** `feature_registry.py` function `render_capabilities()`
**Logic:**
- Read feature registry
- Group by category
- Return text: "I can: monitor your estate (5 features), diagnose problems (4), self-improve (9), help you navigate (10)"
**NL command:** `what can you do` or `capabilities`

## Round H: Score-Driven Improvement

### H1: Score burn-down
**Script:** `score_driver.py` function `score_burndown()`
**Logic:**
- Current score vs target
- Which factor has biggest gap
- Concrete action to improve it
- Output: "Score 0.21 → target 0.50. Biggest gap: policy_firings (0.00). Action: run agent_simulator to generate traffic."
**NL command:** `score target`

### H2: Simulated agent traffic
**Script:** `agent_simulator.py`
**Logic:**
- Generate fake task descriptions from a list of realistic prompts
- Run each through the injection pipeline (memory_retrieval.py)
- This triggers policy matching and enforcer firing
- Run once per hour via idle-learning Phase 2.6
- Log results: firings, injection relevance
**Called by:** idle-learning Phase 2.6

### H3: Score regression alert
**Script:** `score_driver.py` function `check_score_regression()`
**Logic:**
- Load last 3 days of scores from velocity.jsonl
- If 2 consecutive drops, alert via hermes send
- "⚠️ Score declining: 0.25 → 0.22 → 0.21. Check policy firings and injection relevance."
**Called by:** idle-learning Phase 8 (postflight)

### H4: Score leaderboard
**Script:** `score_driver.py` function `score_leaderboard()`
**Logic:**
- Load all velocity.jsonl entries
- Group by week
- Show weekly averages with sparkline
- Output: "Week 30: 0.00 · Week 31: 0.21 · Week 32: 0.35 ↑"
**NL command:** `score history`

## Wiring

### New idle-learning phases:
```
Phase 2.6: Agent Simulator     — python3 scripts/agent_simulator.py
Phase 1a: Resilience checks    — python3 scripts/resilience.py --check
Phase 1b: Predictor            — python3 scripts/predictor.py --all
```

### New natural_ops patterns:
- `diagnose`, `diagnose moat`, `diagnose engine` → `estate:diagnose:...`
- `fix credits` → `estate:fix_credits`
- `predict`, `predict credits` → `estate:predict:...`
- `features`, `what features exist` → `estate:features`
- `benchmark`, `otto bench` → `estate:benchmark`
- `capabilities`, `what can you do` → `estate:capabilities`
- `score`, `score target`, `score history` → `estate:score:...`
- `system health` → `estate:system_health`

### New estate actions:
- `diagnose` — runs full diagnostic, renders report
- `diagnose:<target>` — target-specific (moat, engine)
- `fix_credits` — credit fix guide
- `predict:<target>` — prediction (credits, anomalies)
- `features` — feature registry
- `benchmark` — self-benchmark
- `capabilities` — capabilities list
- `score:<target>` — score info (target, history)
- `system_health` — degradation status

## Acceptance tests

Create `~/.hermes/tests/test_rounds_d_h.py` with tests for:
1. Each script runs and returns structured output (predictor, diagnostics, resilience, feature_registry, score_driver, agent_simulator)
2. Each NL command routes correctly (14 new routes)
3. Each estate action dispatches without crashing
4. Score burn-down computes correctly
5. MTTR tracking produces accurate durations
6. Anomaly detection flags out-of-bounds values
7. ticks.jsonl rotation preserves data integrity
8. Full diagnostic runs all checks

## Verify command
```bash
cd ~/.hermes && python3 tests/acceptance-tests.py --quick && python3 tests/test_rounds_d_h.py
```
