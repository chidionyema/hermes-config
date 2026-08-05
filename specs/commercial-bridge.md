# Commercial Bridge Spec — Rounds L, M, N
**Goal:** Bridge from working prototype to sellable product.
**Current:** 94 tests, discoverability fixed, estate.yaml system built.
**Target:** A company can onboard in 5 minutes, get alerted on any channel, manage incidents with full lifecycle, and prove ROI.

---

## Files to create
- `~/.hermes/scripts/incident_manager.py` — L1-L4: Full incident lifecycle
- `~/.hermes/scripts/alert_router.py` — M1: Multi-channel alert routing
- `~/.hermes/scripts/report_generator.py` — N1-N3: Reporting engine
- `~/.hermes/scripts/estate_migrator.py` — Migration from hardcoded → estate.yaml
- `~/.hermes/hermes-agent/gateway/operator_shell/incident_panel.py` — Telegram incident panel
- `~/.hermes/tests/test_commercial_bridge.py` — Acceptance tests

## Files to modify
- `~/.hermes/hermes-agent/gateway/operator_shell/estate.py` — New actions
- `~/.hermes/hermes-agent/gateway/operator_shell/natural_ops.py` — New patterns
- `~/.hermes/scripts/ops-monitor.py` — Wire incident creation
- `~/.hermes/scripts/otto_health.py` (operator_shell) — Add ROI metrics
- `~/.hermes/estate.yaml` — Default config for existing estate

---

## Round L: Incident Management (the core value prop)

### L1: Incident Lifecycle
**Script:** `incident_manager.py`
**States:** `detected → diagnosing → fixing → verifying → resolved → postmortem_done`
**Data model:**
```json
{
  "id": "inc-20260802-001",
  "title": "Prospector moat down",
  "status": "resolved",
  "severity": "critical",
  "detected_at": "2026-08-02T15:00:00Z",
  "resolved_at": "2026-08-02T18:36:00Z",
  "duration_minutes": 216,
  "affected_projects": ["prospector"],
  "root_cause": "Cursor and Claude credits exhausted",
  "fix_actions": ["auto_paused prospector", "founder topped up credits"],
  "auto_resolved": false,
  "postmortem": "Credits exhausted due to increased verification traffic..."
}
```
**Functions:**
- `create_incident(title, severity, affected_projects)` → incident_id
- `update_incident(id, status, detail)` → progress the lifecycle
- `resolve_incident(id, fix_actions)` → close and trigger postmortem
- `generate_postmortem(id)` → auto-write postmortem from incident data
- `active_incidents()` → list unresolved
- `incident_history(days)` → past incidents with stats

### L2: Auto-escalation
**Logic:** When incident unresolved:
- >15min: notify primary operator again
- >30min: escalate to secondary operator (or all operators)
- >1h: send to all channels (Telegram + email + webhook)
- >2h: CRITICAL — call webhook (PagerDuty/OpsGenie compatible)
**Config:** `estate.yaml` `escalation_policy` section

### L3: Incident panel (Telegram)
**Panel:** `incident_panel.py`
**Views:**
- Active incidents list: "🔴 2 active: moat down (3h), cron failing (1h)"
- Incident detail: full timeline, actions taken, fix buttons
- Postmortem view: what happened, why, how fixed, prevention

### L4: Wire into ops-monitor
When ops-monitor detects moat/cron/credit failures, auto-create incidents.

---

## Round M: Commercial Operations

### M1: Multi-Channel Alert Router
**Script:** `alert_router.py`
**Channels:** telegram, email (SMTP), slack (webhook), discord (webhook), pagerduty (events API), generic webhook
**Config:** `estate.yaml` `alerting` section:
```yaml
alerting:
  channels:
    telegram: {enabled: true, chat_id: "8868748055"}
    email: {enabled: false, smtp_host: "", to: ""}
    slack: {enabled: false, webhook_url: ""}
    pagerduty: {enabled: false, routing_key: ""}
  routing:
    info: [telegram]
    warning: [telegram, slack]
    error: [telegram, slack, email]
    critical: [telegram, slack, email, pagerduty]
```
**Function:** `send_alert(message, severity="warning")` → routes to configured channels
**Wire:** Replace raw `hermes send` calls in ops-monitor, auto_fixer with `alert_router.send_alert()`

### M2: Role-Based Panel Access
**Logic:** Each operator has a `role` in estate.yaml. Roles define allowed panels.
```yaml
roles:
  executive: [status, brief, dashboard, health, reports]
  engineer: [all]
  operator: [status, diagnose, fix, daemons, logs]
```
**Wire:** `chat_router.py` or `otto-inbound` checks operator role before dispatching panel.
**Default:** If no role config, all panels allowed (backward compatible).

### M3: Operator Management
**NL commands:** `operators` → list all, `operator add <name> <telegram_id> <role>`
**Script:** `estate_config.py` already has operator CRUD — just need the panel + NL.

---

## Round N: Proof of Value

### N1: ROI Dashboard
**Add to Otto Health panel:** "This week: 5 incidents, 3 auto-resolved, 2h saved. $6.03 AI spend. Estate uptime: 99.2%."
**Metrics tracked:**
- Incidents this week/month (total, auto-resolved, manual)
- Mean time to resolve (MTTR) — trending up or down?
- AI spend vs estimated human cost (assume $150/h for engineer)
- Uptime % per project
- Policies created (showing system is learning)

### N2: Weekly/Monthly Report Generator
**Script:** `report_generator.py`
**Outputs:** 
- Plain text for Telegram: "📊 *Weekly Report: Aug 2* …"
- Markdown for email/export
- JSON for API
**Sections:** Executive summary, incidents, estate health, AI spend, top actions, improvement velocity

### N3: Executive PDF (stretch)
Generate a proper PDF report for stakeholders. Requires `reportlab` or similar.

---

## Bridge: Migrate existing estate to estate.yaml

### Script: `estate_migrator.py`
**What it does:**
1. Scans existing hardcoded projects (Prospector, Signal Engine, TIE, Haworks)
2. Detects their health checks from existing panels
3. Generates `estate.yaml` with all discovered projects
4. Validates: runs health checks against generated config
5. Reports: "✅ 4 projects discovered. 12 health checks configured. estate.yaml written."
**Run once:** `python3 scripts/estate_migrator.py --migrate`
**Dry-run first:** `--dry-run` shows what would be generated

---

## Default estate.yaml

Generate from the existing estate so it works immediately:
```yaml
estate:
  name: "Chidi's Estate"
  projects:
    - name: prospector
      repo: "~/Documents/code/prospector"
      health_checks:
        - type: process
          pattern: "prospector.scheduler"
        - type: log_check
          path: "~/Documents/code/prospector/store/scheduler/ticks.jsonl"
          error_pattern: '"error": "'
      dependencies: [cursor_cli, claude_cli]
    
    - name: signal-engine
      repo: "~/Documents/code/signal-engine"
      health_checks:
        - type: process
          pattern: "signal.engine"
      dependencies: [tcc_permission, exchange_api]
    
    - name: hermes
      repo: "~/.hermes/hermes-agent"
      health_checks:
        - type: process
          pattern: "gateway.run"
        - type: process
          pattern: "coordinator"
        - type: log_check
          path: "~/.hermes/logs/errors.log"
          error_pattern: "CRITICAL|FATAL"
      dependencies: [telegram_api, anthropic_api]
  
  ai_providers:
    - name: anthropic
      type: anthropic
      health_checks:
        - type: credit_balance
    - name: cursor_cli
      type: cursor_cli
      health_checks:
        - type: api_key_valid
          env_var: "CURSOR_API_KEY"
  
  operators:
    - name: "Chidi"
      telegram_id: "8868748055"
      role: admin
  
  alerting:
    channels:
      telegram: {enabled: true}
    routing:
      info: [telegram]
      warning: [telegram]
      error: [telegram]
      critical: [telegram]
  
  settings:
    daily_digest_time: "09:00"
    auto_pause_on_moat_failure: true
    moat_failure_threshold: 5
```

---

## Acceptance tests (~/.hermes/tests/test_commercial_bridge.py)

1. Incident: create → update → resolve → postmortem lifecycle
2. Incident: auto-escalation triggers at correct thresholds
3. Incident panel renders active incidents
4. Alert router sends to configured channels (mock)
5. Alert router respects severity routing
6. Role-based access: executive can't access diagnose panel
7. Role-based access: engineer can access everything
8. Operator management: add/list/remove operators
9. ROI metrics compute correctly
10. Weekly report generates all sections
11. Estate migrator discovers hardcoded projects
12. Estate migrator generates valid estate.yaml
13. All new NL commands route correctly
14. estate.yaml validates and loads

## Verify command
```bash
cd ~/.hermes && python3 tests/test_commercial_bridge.py
```