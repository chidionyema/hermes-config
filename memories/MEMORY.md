[tags: project:hermes-config domain:infra type:decision] Hermes-Claude model: Hermes owns control loop. Claude consulted at decision points (planning, decomposition, judgment, verification). Pass full state each call. Claude returns structured JSON output (plan, next_action, rationale). Model tiering: Opus for hard strategy, Sonnet for lighter planning, Minimax for cheap execution.
§
INVARIANTS — always injected. (1) Source-or-die: every factual claim cites retrievable source or is unverifiable. (2) Verdict-from-retrieval-only: model rules only from fetched passages. (3) Kill-fast: cheapest decisive gate first. (4) Hermes owns control loop; Claude consulted at decisions; Minimax for cheap execution. (5) Never commit secrets. (6) Never substitute fabricated output for real execution results.
§
When user gives me a problem I'm unsure how to fix: delegate to Claude Code with full context, the problem spec, and what's been tried. Track the task in todo, report progress and result. Never guess or attempt a fix I'm not confident about.
§
[tags: project:prospector] Go-live: 362 pass, .NET 39, P0: legal+live payments (user blocked). CI/entitlements/guard/pricing fixed.
§
Default model: claude-sonnet-4 (via Anthropic API, key from ~/.config/llm/secrets.sh). Switched from DeepSeek-V3 2026-06-18 per "why are we running DeepSeek V3? Let's use Claude instead." Fallback: minimax-m3.
§
CRITICAL: delegate_task MUST always use background=True (never default foreground). Foreground blocks Telegram chat — user can't steer. This has been called out repeatedly. Prefer background=True + notify_on_complete. Tool-level guard at ~/.hermes/scripts/dispatch-guard.py.
§
[tags: project:otto domain:autonomous-agents type:spec]
Otto Radical Improvement Plan delivered 2026-06-18. Sections: A (slope/composition), B (self-detected failure+success), C (idle work), D (ceiling-breaking/chained sigmoids), E (introspection surface), F (hardening — retrieval prereq, eval regression, conflict resolution, confidence spectrum). Build order: 1. Injection log + E 2. Retrieval 3. B (gated behind F2) 4. A 5. C 6. D. Boundary: no in-loop improvement of the improver.