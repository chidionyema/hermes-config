[tags: project:hermes-config domain:infra type:decision] Hermes-Claude model: Hermes owns control loop. Claude consulted at decision points (planning, decomp
§
[tags: project:prospector] Go-live: 362 pass, .NET 39, P0: legal+live payments (user blocked). CI/entitlements/guard/pricing fi
§
[tags: project:otto domain:autonomous-agents type:spec] Radical Improvement Plan all sections done except F4 (confidence, waits on holdout). Build order: 1.
§
[tags: project:otto domain:infra type:lesson] Skill update pattern: after every substantive session, patch otto-operating-model with new corrections (batch-fix protocol, automatic pattern, human-friendly design). Add references/ for reproducible methodology documents. Never leave a session without embedding at least one correction into skills.
§
Self-improvement pipeline: 7 phases (preflight, reflection hook, meta-analysis, gap-finding, near-miss, trend analysis, consolidation, postflight). Auto-creates policies for uncovered high-severity domains. Outcome accelerator logs every task completion as a meta-improver outcome. Trend analyzer compares across days. Morning briefing reads reflection + gap-finding + near-miss.
§
Monitoring layer: health watchdog runs every 15min checking cron, git, gateway, disk, policy firings. Alert log at ~/.hermes/logs/alerts/watchdog.jsonl. Audit trail records every decision permanently at logs/audit/decision-trail.jsonl. Strategist daily audit now reads alert log + trend reports.
§
Estate inventory cron job runs daily at 6am, catalogs every component (scripts, skills, policies, cron, repos, logs, pipeline phases). Output to ~/.hermes/reports/estate-inventory.md — delivered to Telegram on change.
§
Estate: 4-stage pipeline (inventory→drift→optimization→remediation) runs 6am daily. Reports: estate-drift.md (change-only), estate-optimization.md, estate-inventory.md. 44 scripts, 83 skills, 14 cron jobs, 9 policies. Policy rule: read rule text + compare trigger conditions before archive — metadata alone is insufficient.