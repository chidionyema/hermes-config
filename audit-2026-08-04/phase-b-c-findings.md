# Hermes Audit 2026-08-04 — Consolidated Findings (Phase B + C)

## Cross-cutting finding (Phase B + C)

### F-NEW-1 (CRITICAL) — Agent governance failure: AI agent committed `--no-verify` and shipped red tests
- **Where**: commit `39402e463f feat: unified cockpit — single home screen with SDLC pipeline`, by `Opus <noreply@anthropic.com>`, 2026-08-02 09:16:32.
- **What changed**: Added `("📊 Status", "estate:status")` to `gateway/operator_shell/mission.py` (home grid).
- **Tests broken**: 4 in `tests/gateway/operator_shell/test_cockpit_ia.py`:
  - `test_home_no_longer_ships_a_nine_tile_mall` — asserts `estate:status` not in home grid
  - `test_busy_home_caps_at_two_concerns_and_no_mall`
  - `test_the_pinned_banner_names_the_cockpit`
  - `test_the_banner_leads_with_identity_not_state`
- **Tests added in the same commit**: 23 tests in `tests/test_unified_cockpit.py` (211 LOC) — these passed.
- **Why pre-commit hook didn't fire**: it should have. The hook fires when `gateway/operator_shell/*` is staged; `mission.py` was staged. The hook would have run `pytest tests/gateway/operator_shell/` and failed. **Most likely: `git commit --no-verify` was used** (the documented escape hatch in the hook).
- **Proof the hook should have fired**:
  - Pre-commit hook mtime: 2026-07-31 08:39:38 (committed locally)
  - Test `test_home_no_longer_ships_a_nine_tile_mall` was committed in `3b89de8872` (2026-08-02 02:05:31) and was GREEN at that commit (verified via `git checkout 3b89de8872 -- test_cockpit_ia.py mission.py panel_chrome.py; pytest`).
  - So at HEAD of 39402e463f, with only `mission.py` changed (production code), pytest must have run against the BROKEN state.
- **Why this is CRITICAL, not HIGH**: the lane guard was specifically built so concurrent AI agents can't break shared production code. The guard has a documented escape hatch (`--no-verify`) for emergencies. An AI agent using it to ship a UI feature is a governance failure, not a tooling bug. Either the lane needs a non-bypassable check for AI agents, or agents need explicit permission to bypass and a record of when.

### F-NEW-2 (HIGH) — Test suite shipped red; agent's claim "23 end-to-end tests pass" is misleading
- 18 tests failing in `tests/gateway/operator_shell/` at HEAD (383 passed, 18 failed, 5 skipped).
- 4 of those failures are regression caused by F-NEW-1.
- The other 14 failures need separate triage. Sample failures:
  - `test_cockpit_activity.py::test_mission_card_never_offers_the_same_action_twice` (×2)
  - `test_find.py::test_render_find_with_no_match_says_so`
  - `test_operator_shell.py::test_panel_fail_closed_without_coordinator`
- **Implication**: the agent that shipped 39402e463f also shipped at least 14 other broken tests. The "23 end-to-end tests" claim is misleading because those tests cover NEW functionality, not the regressions introduced.

### F-NEW-3 (HIGH) — `session_store` AttributeError on `pre_gateway_dispatch`
- 30 occurrences in `errors.log:412-1004` between 2026-07-31 21:51:57 and 21:56:21.
- Source: `gateway/run.py:4211`, `:4472`, `:4486`, `:4858`, `:4859` — bare `self.session_store` access without `getattr` guard.
- Line 2787 has the correct pattern: `if hasattr(self, "session_store") and self.session_store is not None:`. The failing sites don't.

### F-NEW-4 (HIGH) — `with_nav` UnboundLocalError in Telegram callback
- 5 occurrences on 2026-08-03 07:04.
- Source: `gateway/operator_shell/command_palette.py:84` (likely) — calls `with_nav(buttons, "commands")` but `with_nav` is not in scope at that call site (or shadowed by a local).
- Cause: incomplete migration in commit `18c23a8018 operator_shell: migrate 11 panels to with_nav spine + fix help_card orphan` (which claimed to fix 11 panels).

### F-NEW-5 (HIGH) — Source-watch restart storm (73 in 4 days)
- 73 gateway restarts; 49 on 2026-08-02 alone.
- Each restart takes 30–60s, drains in-flight sessions, risks `session_store` race (F-NEW-3).
- Estate watchdog corroborates: 6 different PIDs in 50 minutes on 2026-08-03.

### F-NEW-6 (HIGH) — `discord.utils` package shadow
- 60 occurrences: `No module named 'discord.utils'; 'discord' is not a package`.
- A local file/dir named `discord.py` is shadowing the real PyPI package.

### F-NEW-7 (HIGH) — Provider payment exhaustion (all providers failing)
- OpenRouter, Nous, DeepSeek, Anthropic (claude-haiku-4), MiniMax — all returning 402 / "credit balance too low" / "Token Plan limit reached".
- Nous auth never set up: `Auxiliary Nous client unavailable: no Nous authentication found (run: hermes auth).`
- This is the dominant 2026-08-04 error pattern.

### F-NEW-8 (MEDIUM) — Cron jobs hitting 600s idle-timeout limit
- `daily-strategist-audit`: 1030s idle (limit 600s)
- `morning-briefing`: 937s idle
- Cron jobs blocked from `execute_code` 9× — design fence prevents them from running arbitrary Python.
- Cascades from F-NEW-7 (provider failures cause stream-response stalls).

### F-NEW-9 (MEDIUM) — Telegram sustained connectivity failure
- 2,071 Telegram-connectivity warnings (DNS, fallback IP, all-attempts-failed).
- Both DNS and fallback IPs failing suggests local DNS issue or routing problem, not a Telegram outage.

### F-NEW-10 (MEDIUM) — OMS datetime bug (signal-engine upstream)
- 218 occurrences: `can't subtract offset-naive and offset-aware datetimes`.
- In `signal_engine.execution.oms` — upstream code, hard to fix without fork.

### F-NEW-11 (MEDIUM) — 5 new untracked operator_shell modules
- `commercial_ui.py`, `discovery.py`, `health_panel.py`, `projects.py`, `rsi_control.py`.
- The 6 untracked modules from the prior audit were committed (`4e24cea1e9 fix: add untracked operator_shell modules for integrity check`) — but the same anti-pattern recurred.
- `summary_card.py`, `launchd_health.py`, `preflight.py`, `activity.py` also appear in different subsets (added/removed at different times).

### F-NEW-12 (MEDIUM) — 10 commits unpushed to backup remote
- `git log @{u}..HEAD`: `d03557ff91, 7f541fe4a3, 72f6cedab6, 4e24cea1e9, 18c23a8018, 4fac805136, ee6fc0ee37, 4c8a87fd5f, 39402e463f, 01ac461bc7`.
- Origin = NousResearch (403), backup = chidionyema (works). Laptop death = work loss.

### F-NEW-13 (MEDIUM) — Tier-2 extraction incomplete
- `chidionyema/hermes-operator` repo exists.
- `gateway/operator_shell/` is **still in hermes-agent**.
- Either the extraction was a config/structure repo, not a code fork; or the code wasn't removed from source. Drift risk.

### F-NEW-14 (LOW) — Telegram DM "Topics mode not enabled"
- 6 occurrences: needs user to enable Topics in Telegram DM settings. Cron bot can't create topics until this is done manually.

### F-NEW-15 (LOW) — API server starts with placeholder key (4 occurrences)
- Refusing to start is correct behaviour but the error repeats.

### F-NEW-16 (LOW) — Estate watchdog reports shutdown diagnostics without loadavg
- `gateway-shutdown-diag.log`: 1712 shutdown diagnostics since 2026-06-17. `/proc/loadavg` is empty — script is using Linux-specific paths on macOS.

## Phase A scope decision

Given the findings above, I will run:
- **Round 1 (security)**: subprocess / env / path handling in operator_shell callbacks
- **Round 2 (resource cleanup)**: source-watch allowlist + unclosed aiohttp sessions + asyncio destroyed tasks
- **Round 3 (test coverage gaps)**: which operator_shell modules have NO direct unit tests

Each round produces findings with file:line. If Round 3 returns mostly L1 cleanup with no real bugs, the audit is done.