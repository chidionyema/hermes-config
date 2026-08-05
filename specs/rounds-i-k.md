# Rounds I-K Implementation Spec
**Date:** 2026-08-02

## Files to create
- `~/.hermes/scripts/auto_fixer.py` — I1-I2: auto-fix engine with verification
- `~/.hermes/scripts/cross_project.py` — K1-K3: cross-project intelligence
- `~/.hermes/hermes-agent/gateway/operator_shell/diagnose_panel.py` — J1: Telegram diagnose panel
- `~/.hermes/hermes-agent/gateway/operator_shell/predict_panel.py` — J2: Telegram predict panel
- `~/.hermes/hermes-agent/gateway/operator_shell/features_panel.py` — J4: Telegram features panel
- `~/.hermes/tests/test_rounds_i_k.py` — Acceptance tests

## Files to modify
- `~/.hermes/hermes-agent/gateway/operator_shell/estate.py` — New actions
- `~/.hermes/hermes-agent/gateway/operator_shell/natural_ops.py` — New NL patterns
- `~/.hermes/hermes-agent/gateway/operator_shell/otto_health.py` — I6: fix success rate
- `~/.hermes/scripts/ops-monitor.py` — I5: post-fix policy creation
- `~/.hermes/scripts/idle-learning-run.sh` — New phases

---

## Round I: Closed-Loop Operations

### I1: Auto-fix common failures
**Script:** `auto_fixer.py` function `auto_fix_all(dry_run=False) -> dict`
**Logic:**
- Scan ops-monitor.jsonl for recent failures
- For each failure type, check if there's a known fix:
  - `cron_failures` with HTTP 429 → wait 5min, retry cron job
  - `gateway_crash` → kickstart launchd job
  - `config_push_failing` → git pull + retry push
  - `coordinator_stale` → kickstart coordinator
  - `moat_down` → already handled by ops-monitor auto-pause
- Each fix is SAFE (restart only, no config changes, no money)
- Returns: `{"fixed": [{"problem": "cron_429", "action": "retry", "result": "ok"}], "skipped": [...], "failed": [...]}`
- Called by idle-learning Phase 2.7

### I2: Fix verification
**Script:** `auto_fixer.py` function `verify_fix(problem_type, details) -> dict`
**Logic:**
- After each fix, run the relevant health check
- `cron_fix` → check cron job last_status
- `gateway_fix` → check if gateway is responding
- `coordinator_fix` → check heartbeat age
- Returns: `{"verified": True/False, "evidence": "heartbeat now 2s (was 300s)"}`
- If verification fails, escalate (log + notify)

### I3: Guided fix panels
**New panel:** `diagnose_panel.py` function `render_fix_guide(target) -> (text, buttons)`
**Logic:**
- For `fix credits`: renders step-by-step with buttons
- Each step is a button that opens the URL or marks as done
- Progress bar: "Step 2/4: Top up Cursor credits → [Open cursor.sh] [✓ Done]"
- When all steps done: "✅ Credits should be restored. Run `diagnose moat` to verify."
**Estate action:** `fix_guide:<target>`

### I4: "Fix everything you can" with report card
**New action:** `estate:fix_all` (enhances existing fix_all_safe)
**Logic:**
- Runs auto_fixer
- Verifies each fix
- Returns report card panel:
```
🛠 *Auto-Fix Report*
✅ Restarted cron hermes-config-auto-push — now ok
✅ Kickstarted coordinator — heartbeat 2s
⚠️ Gateway restart skipped — already running
❌ Cursor credits — needs manual top-up
```
**NL:** `fix all` or `fix everything`

### I5: Post-fix learning
**Modify:** `ops-monitor.py` and `auto_fixer.py`
**Logic:**
- After any successful auto-fix, create/update a policy:
```json
{
  "id": "pol-auto-fix-{type}-{date}",
  "trigger": "same failure pattern detected",
  "rule": "auto-fix procedure that worked",
  "confidence": 0.5,
  "auto_generated": true
}
```
- If policy already exists, increment confidence
- If fix fails 3x, decrement confidence and escalate

### I6: Fix success rate in Otto Health
**Modify:** `otto_health.py`
**Logic:**
- Read auto_fixer logs
- Compute: total_attempts, successful, failed, skipped
- Add to Otto Health dashboard: "Auto-fix rate: 85% (17/20). Manual: 3 this week."
- Factor into score: successful auto-fixes boost the auto_fixes score component

---

## Round J: Telegram-Native Panels

### J1: Diagnose panel
**New panel:** `diagnose_panel.py` function `render_diagnose(target=None) -> (text, buttons)`
**Logic:**
- Runs diagnostics.py for the target (or full)
- Renders as Telegram card with emoji per check:
```
🔍 *Diagnostic: Moat*

🟢 Network: api.cursor.sh reachable
🔴 Cursor API: usage limit reached
🔴 Claude API: credit balance too low

*Root cause:* Both providers exhausted
*Fix:* [📋 Fix credits guide] [🛠 Auto-fix]
```
**Estate action:** `diagnose_panel:<target>`
**NL:** `diagnose` now renders panel instead of raw text

### J2: Predict panel
**New panel:** `predict_panel.py` function `render_predict(target="credits") -> (text, buttons)`
**Logic:**
- Runs predictor.py for target
- Renders as card with forecast + sparkline:
```
🔮 *Credit Forecast*

Cursor: exhausts in ~3h at current rate (12 errors/h)
  Last 6h: ████▅▃▁
Claude: already exhausted (credit balance too low)

*Actions:* [🔝 Top up Cursor] [🔝 Top up Claude] [🛠 Auto-fix]
```
**NL:** `predict` now renders panel

### J3: Score panel (phone-optimized)
**Modify:** `otto_health.py` to have a compact phone mode
**Logic:**
- Shorter version of Otto Health for phone screen
- Triggered by `score` (currently shows JSON)
- Shows: score, sparkline, top gap, one action button

### J4: Features panel
**New panel:** `features_panel.py` function `render_features() -> (text, buttons)`
**Logic:**
- Groups features by round
- Each group is a button row
- Tapping a feature jumps to its panel/natural command
```
📋 *Features* (30 built)

*Monitor:* [📊 Status] [🔭 Prospector] [🚀 Fleet]
*Diagnose:* [🔍 Diagnose] [🔮 Predict] [💳 Fix credits]
*Improve:* [🧠 Health] [📈 Score] [🛠 Fix all]
*Info:* [📜 Activity] [📋 Features] [❓ Help]
```

---

## Round K: Cross-Project Intelligence

### K1: Estate-wide health score
**Script:** `cross_project.py` function `estate_health_score() -> dict`
**Logic:**
- Check all subsystems independently:
  - Prospector: moat health, tick success rate
  - Signal Engine: process running, TCC granted, API reachable
  - TIE: daemon status, last review
  - Haworks: repo health, CI status
  - Hermes: coordinator, gateway, cron, policies
- Weight and combine into single 0-100 score
- Return breakdown per project
**NL:** `estate health`

### K2: Cross-project correlation
**Script:** `cross_project.py` function `correlate_estate() -> dict`
**Logic:**
- Scan all error sources (errors.log, ops-monitor, watchdog)
- Find clusters where multiple projects fail simultaneously
- Identify shared root cause (credits, network, disk space)
- Return: `{"clusters": [{"time": "15:00-15:30", "projects": ["prospector","hermes"], "shared_cause": "API credits"}]}`
**NL:** `correlate` or `what is the root cause`

### K3: Project dependency map
**Script:** `cross_project.py` function `dependency_map() -> dict`
**Logic:**
- Hard-coded map of known dependencies:
  - Prospector → Cursor CLI, Claude CLI, API credits
  - Signal Engine → TCC, exchange API, account balance
  - Hermes → Telegram API, GitHub, coordinator DB
  - Otto → Hermes, Claude/MiniMax API
- For each dependency, check current health
- If dependency is down, mark dependent as blocked
- Return: `{"prospector": {"status": "blocked", "blocked_by": "Cursor credits exhausted"}}`
**NL:** `dependencies` or `what depends on what`

---

## New NL patterns (add BEFORE existing generic patterns):

```python
# Round I
(r"fix\s+(all|everything)", "fix_all", "", "Auto-fix everything safe"),
(r"fix\s+guide\s+(.+)", "fix_guide", "{g1}", "Guided fix"),
(r"auto.?fix", "fix_all", "", "Auto-fix"),

# Round J  
# diagnose already exists, just needs panel render

# Round K
(r"estate\s+health", "estate_health", "", "Estate-wide health"),
(r"correlate|what\s+is\s+the\s+root\s+cause|root\s+cause", "correlate", "", "Cross-project correlation"),
(r"dependencies|what\s+depends\s+on\s+what", "dependencies", "", "Dependency map"),
```

## New estate actions:
- `fix_all` — runs auto_fixer + verification + report card
- `fix_guide:<target>` — guided fix panel
- `diagnose_panel:<target>` — Telegram diagnose panel (default if no target)
- `predict_panel:<target>` — Telegram predict panel
- `features_panel` — Telegram features panel
- `estate_health` — cross-project health score
- `correlate` — cross-project correlation
- `dependencies` — dependency map

## Idle learning new phase:
```
Phase 2.7: Auto-Fixer — python3 scripts/auto_fixer.py --fix --verify
```

## Acceptance tests (~/.hermes/tests/test_rounds_i_k.py):
1. auto_fixer runs and returns structured results
2. auto_fixer verification works
3. Each new NL command routes correctly (10 routes)
4. Each new estate action dispatches without crashing
5. Estate health score computes 0-100
6. Cross-project correlation finds clusters
7. Dependency map returns valid structure
8. Fix guide panel renders for known targets
9. All new panels render without crashing
10. Post-fix policy creation works

## Verify command
```bash
cd ~/.hermes && python3 tests/test_rounds_i_k.py
```