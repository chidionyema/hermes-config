# Phase C — Log Analysis (2026-07-31 21:51 → 2026-08-04 11:15)

Window: ~3.9 days. Sources: `errors.log` (10,471 lines), `agent.log` (17,389), `gateway.error.log` (19,283), `signalengine-daemon.{out,err}.log` (66,528), `estate-watchdog.log` (12,384).

## Volume

| Day | errors.log lines | gateway.error.log (no timestamps) |
|---|---|---|
| 2026-07-31 | 4,117 | many |
| 2026-08-01 | 261 | — |
| 2026-08-02 | 1,117 | — |
| 2026-08-03 | 97 | — |
| 2026-08-04 | 1,518 | — |

The 2026-07-31 spike is dominated by Telegram `response_delivery_dropped` (2,878 lines). The 2026-08-04 spike is dominated by provider payment exhaustion warnings.

## Real bugs found (NEW, not in prior audit)

### C-1 (HIGH) — `session_store` AttributeError on `pre_gateway_dispatch`
- **Where**: `gateway/run.py:4211` and `:4472` — both use bare `self.session_store` (no `getattr` guard like line 2787 does).
- **Symptom**: 30 occurrences of `WARNING gateway.run: pre_gateway_dispatch invocation failed: 'GatewayRunner' object has no attribute 'session_store'` between 21:51:57 and 21:56:21 on 2026-07-31.
- **Why it fires**: Line 2262 sets `self.session_store = SessionStore(...)` inside some code path, but `pre_gateway_dispatch` is invoked before that path completes (or on an alternative init path that skips it). Line 2787 already uses `if hasattr(self, "session_store") and self.session_store is not None:` — but the failing call sites at 4211/4472/4486/4858/4859 do **not** have that guard.
- **Fix**: Use `getattr(self, "session_store", None)` and skip if None, matching the existing guard pattern at line 2787.
- **Repro**: Trace `pre_gateway_dispatch` callers → look at the early-startup ordering of `__init__` vs the dispatch hook.

### C-2 (HIGH) — `with_nav` UnboundLocalError in Telegram callback
- **Where**: `gateway/operator_shell/command_palette.py:84` calls `with_nav(buttons, "commands")` inside an estate callback handler, but `with_nav` is not in scope (or is shadowed by a local).
- **Symptom**: 5 occurrences of `ERROR gateway.platforms.telegram: [Telegram] estate callback query failed: cannot access local variable 'with_nav' where it is not associated with a value` on 2026-08-03 07:04.
- **Context**: `with_nav` is defined in `gateway/operator_shell/panel_chrome.py:125` and imported by many panels (`help_card`, `smart_home`, `first_run`, `predict_panel`, `features_panel`, `host`, `health_panel`, `signal_engine`, `otto_health`, `rsi_control`, `command_palette`, `incident_panel`, `brain`, `sdlc`, `status_summary`, `inbox`).
- **Why this one fires**: The commit `18c23a8018 operator_shell: migrate 11 panels to with_nav spine + fix help_card orphan` migrated 11 panels to use `with_nav` but the callback that wraps `command_palette.py:84` either (a) failed to import `with_nav` at module level, or (b) has a local `with_nav` variable somewhere that shadows the import on the UnboundLocal path.
- **Fix**: Audit `command_palette.py` for missing `from .panel_chrome import with_nav` and for any local variable named `with_nav`.
- **User impact**: 5 callbacks crashed with 0 successful deliveries → the "commands" panel button is broken.

### C-3 (HIGH) — Source-watch restart storm
- **Where**: `gateway/run.py` source-watch loop is too eager.
- **Symptom**: 73 gateway restarts in 4 days; 49 on 2026-08-02 alone (~2/hour). Log: `Source watch: gateway source changed and settled — restarting so the new code is live`.
- **Estate watchdog corroborates**: 6 different gateway PIDs between 07:08 and 07:59 on 2026-08-03 (`92157, 4500, 15566, 22826, 46758, 51805`) — 6 different processes in 50 minutes, each spinning up cleanly.
- **Cost**: Each restart takes 30–60s to drain, kills in-flight sessions, and risks the `session_store` race (see C-1).
- **Possible causes**:
  1. Genuine development workflow editing files rapidly
  2. Source-watch debounce is too short (sampling artifact)
  3. Source-watch includes write targets that change as a side-effect of normal operation (e.g., logs, pid files, lock files)
- **Need to verify**: Does the watcher's path allowlist exclude log/state directories? Look for `watchdog`/`inotify`/polling setup in source.

### C-4 (HIGH) — Telegram DNS / connectivity is sustained-bad
- 921 `Primary api.telegram.org connection failed ([Errno 8] nodename nor servname provided, or not known)` — DNS resolution failures.
- 670 `Fallback IP ... failed: <empty>` — fallback IP attempts also failing.
- 259 `Fallback IP ... failed: All connection attempts failed`.
- 221 `Connect attempt ... failed: httpx.ConnectError: All connection attempts failed`.
- **Total**: 2,071 Telegram-connectivity warnings since 2026-07-31.
- **Cost**: When Telegram is unreachable, the estate can't deliver messages — most user-facing flows fail silently.
- **Possible causes**: Local DNS issue; ISP block; Telegram-specific routing. Worth checking `dig api.telegram.org` and tracing why fallback IPs also fail.

### C-5 (HIGH) — `discord.utils` import collision
- **Where**: Discord adapter plugin.
- **Symptom**: 60 occurrences of `ERROR plugins.platforms.discord.adapter: Could not install hook on live ws: No module named 'discord.utils'; 'discord' is not a package`.
- **Diagnosis**: A local module or directory is named `discord.py` and shadows the real `discord` PyPI package. Standard Python package-shadow trap.
- **Fix**: `find . -name 'discord.py' -not -path '*/site-packages/*'` to locate the shadow.
- **User impact**: Discord adapter is non-functional. 4 follow-on `NoneType.get_channel` errors in `discord.adapter` from same window.

### C-6 (MEDIUM) — Provider payment exhaustion across the board
- **Symptoms**:
  - OpenRouter: 88× `marking openrouter unhealthy for 60s (payment / credit error)`
  - Nous: 88× `marking nous unhealthy for 60s (payment / credit error)` + 88× `no Nous authentication found (run: hermes auth)` — **Nous auth missing entirely**
  - DeepSeek: 9× `HTTP 402: Insufficient Balance`
  - Anthropic claude-haiku-4: 36× `credit balance is too low`
  - MiniMax (current model): 43× `HTTP ... Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits` in gateway.error.log + 13× `API call failed after 3 retries ... Token Plan usage limit reached`
- **Diagnosis**: Multiple providers exhausted simultaneously. This is the dominant 2026-08-04 pattern.
- **User-facing impact**: Agent cannot respond to most user requests during this window — every provider in the failover chain is failing.
- **Why no Nous auth**: `Auxiliary Nous client unavailable: no Nous authentication found (run: hermes auth).` — user has never run `hermes auth` to set up Nous credentials.

### C-7 (MEDIUM) — Cron jobs hitting idle-timeout
- `daily-strategist-audit`: 1030s idle vs 600s limit
- `morning-briefing`: 937s idle vs 600s limit
- Cron jobs blocked from `execute_code` (9×): `BLOCKED: execute_code runs arbitrary local Python (including subprocess calls that bypass shell-string approval checks). Cron jobs run without a user present to approve it.`
- **Diagnosis**: Provider timeouts (C-6) cascade into cron timeouts (C-7) because cron jobs depend on the same provider pool.

### C-8 (MEDIUM) — OMS datetime arithmetic error (signal-engine upstream)
- 218 occurrences: `ERROR signal_engine.execution.oms: OMS background worker error: can't subtract offset-naive and offset-aware datetimes`
- **Diagnosis**: Mixing `datetime.utcnow()` (naive) with `datetime.now(tz=...)` (aware) — Python refuses to subtract them.
- **Where in upstream**: `signal_engine.execution.oms` — this is in the upstream `NousResearch/hermes-agent` monorepo, not in your operator_shell code. Hard to fix without forking signal-engine.

### C-9 (MEDIUM) — Telegram DM "Topics mode not enabled"
- 6 occurrences: `[Telegram] Cannot create DM topic 'Cron' in chat : Topics mode is not enabled. The user must open the DM with this bot in Telegram, tap the bot name at the top, and enable 'Topics' in chat settings before topics can be created.`
- **Diagnosis**: A one-time user setup step is required in Telegram but never completed. The bot keeps trying and failing.

### C-10 (LOW) — Telegram polling "Bootstrap delete Webhook" retry loop
- 65 occurrences of `Network Retry Loop (Bootstrap delete Webhook): Failed run number N of N. Aborting.`
- 45 occurrences of `No error handlers are registered, logging exception.`
- 16 occurrences of `Updater: Error while calling get_updates one more time...`
- **Diagnosis**: Telegram library's startup race — tries to delete a webhook that doesn't exist, then can't mark updates as fetched on shutdown. Mostly cosmetic but generates noise.

### C-11 (LOW) — API server starts with placeholder key
- 4 occurrences: `gateway.platforms.api_server: Refusing to start: API_SERVER_KEY is set to a placeholder value.`
- **Diagnosis**: Refusing to start is correct behaviour, but the error message is repeated. Probably retrying on each platform init cycle.

## Gate analysis (B-phase + C-phase cross-reference)

The pre-commit hook has 4 gates: COMPILE, LANE GUARD, TEST GATE (operator_shell only), UNTRACKED-IMPORT. The TEST GATE only fires when `gateway/operator_shell/*` OR `tests/gateway/operator_shell/*` is in `git diff --cached`. The 18 currently-failing tests live in those paths, so any commit touching operator_shell or its tests should have triggered the gate. Either:

1. The most recent commits that broke the suite used `--no-verify` (escape hatch documented in hook).
2. The gate was working, the failing tests were added in a separate commit after a passing one (race: tests added red on purpose as failing-by-design, e.g., `test_detect_fence_is_keyword_only_and_misses_paths` from prior audit).
3. Production code in `gateway/run.py` or other non-operator_shell paths changed behaviour in a way that broke cockpit tests, and the gate's allowlist doesn't include the breaking file.

Need to inspect: `git log -p tests/gateway/operator_shell/test_cockpit_ia.py` to see if these tests were added green and went red later, or were always red.