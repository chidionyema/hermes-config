[tags: project:hermes-config domain:infra type:decision] Hermes-Claude model: Hermes owns control loop. Claude consulted at decision points (planning, decomposition, judgment, verification). Pass full state each call. Claude returns structured JSON (plan, next_action, rationale). Model tiering: Opus for hard strategy, Sonnet for lighter planning, Minimax for cheap execution.
§
Prospector: 380 pass, 0 fail. 5 API keys in .env (GEMINI, DEEPSEEK, ANTHROPIC, MINIMAX, EXA). BRAVE not needed. 14 golden-set tests pass.
§
[tags: project:otto domain:infra type:lesson] Skill update pattern: after every substantive session, patch otto-operating-model with new corrections (batch-fix protocol, automatic pattern, human-friendly design). Add references/ for reproducible methodology documents. Never leave a session without embedding at least one correction into skills.
§
Self-improvement pipeline: 7 phases (preflight, reflection hook, meta-analysis, gap-finding, near-miss, trend analysis, consolidation, postflight). Auto-creates policies for uncovered high-severity domains. Outcome accelerator logs every task completion as a meta-improver outcome. Trend analyzer compares across days. Morning briefing reads reflection + gap-finding + near-miss.
§
[tags: domain:infra type:system] Alert resolution system built: alert-resolver.py closes probe/watchdog findings when conditions clear. Watchdog fixed: gateway process regex corrected. 54/75 alerts resolved, 0 open. improvement-probe silent when healthy. Prospector 380 tests, 0 fail. Signal Engine daemon live at 60s. 17 cron jobs: prospector hourly, signal-daemon watchdog every 5m, estate daily 6am.
§
Estate inventory cron job runs daily at 6am, catalogs every component (scripts, skills, policies, cron, repos, logs, pipeline phases). Output to ~/.hermes/reports/estate-inventory.md — delivered to Telegram on change.
§
9 policies: 7 active (002,003,006,007,008,010,012), 1 provisional (001,004). Escalation chains: decision-making (003→007→008) and infra/dispatch (002→012). Pipeline skips chain members from drift/archive warnings.