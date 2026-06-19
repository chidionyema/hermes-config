Default model: claude-sonnet-4 (Anthropic), pinned 2026-06-18. User rejected DeepSeek as default. This is an invariant — never change without explicit confirmation. Cron jobs should prefer no_agent over LLM-driven; LLM-driven jobs must have documented reasoning.
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
§
[tags: domain:infra type:lesson] Cron-budget subprocess pattern (2026-06-18): _run_handler must bound timeout (2s) AND cache results (5min per-handler) so N fingerprints × slow handler can't bust the cron's 120s wall cap. Companion: any script that dispatches long work (pytest, jest) needs TOTAL_BUDGET < cron cap, PER_REPO_TIMEOUT <= TOTAL_BUDGET/n, and fut.result(timeout=remaining) wall-clock cut. Pattern documented at dropped-ball-prevention/references/cron-budget-subprocess-pattern.md.
§
[tags: domain:workflow type:preference] User demands probe-as-answer for state questions (estate/cron/processes/git state): run read-only probe, return full stdout verbatim in fenced code block — no interpretation/summarization. The probe IS the answer. Skill at ~/.hermes/skills/estate-ground-truth-probe/. ALSO: "forwarding" to a stalled Claude is cosplay — when Claude session has no fresh capture-pane output (>5min stale), kill it and either fix directly with bounded tools+probes OR start one fresh session with merged context. Investigate, don't relay. Self-cadence: never say "going dark" / "polling in 60s" / "standing by" — every gap is a fix in flight or an outcome delivered.