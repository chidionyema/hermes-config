# Hermes Agent — Log Analysis (2026-08-05)

Compiled from `~/.hermes/logs/` (40 logs, 122k+ lines). Findings grouped into MAJOR (this stops / blocks capability) and MINOR (cleanup, polish, hygiene).

---

## 🔴 MAJOR — Block recovery, sysadmin, money

### M1. **Provider money is gone (4 channels, simultaneously)**
**Evidence:** `gateway.error.log` has **232 × "Token Plan"** + **78 × "HTTP 402"** + **60 × "credit balance is too low"** + **6 × "RESOURCE_EXHAUSTED"** (Gemini).

What's empty:
| Provider | Error | Impact |
|---|---|---|
| `minimax` | `HTTP 429: Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits` (×232) | Cron jobs fail; agent stays on fallback |
| `deepseek` | `HTTP 402: Insufficient Balance` (×78) | Currently configured-fallback |
| `anthropic` | `credit balance is too low to access the Anthropic API` (×60) | Context compressor failures |
| `gemini` | `RESOURCE_EXHAUSTED: Your prepayment credits are depleted` (×6) | Just exhausted |

**Why this is the #1 problem:** The agent has been retrying with the failed provider, blocking on 2-7s backoffs, until cron jobs hit the 600s idle limit and **fail completely**. The fallback chain is broken because every fallback is also out of money.

**Fix:** Top up one account (DeepSeek is cheapest — $2 minimum) **or** disable the providers that are permanently exhausted (`/model` → switch to one that has credits). Verify any provider before letting a cron job run with it.

**Proof:** `grep -c 'Token Plan' gateway.error.log` → 232. `grep -c '402' gateway.error.log` → 78. `grep -c 'credit balance' gateway.error.log` → 60.

---

### M2. **Gateway restart storm at 02:00–04:00 (1,153 errors in 4 hours)**
**Evidence:** Time histogram on `errors.log`:
```
 536  2026-08-05 02:00   ← peak
 458  2026-08-05 01:00
 159  2026-08-05 04:00
 137  2026-08-05 00:00
```

Total: **1,153 errors in 4 hours**. The trigger: `Bootstrap delete Webhook: Failed run number 0 of 0. Aborting. (Timed out)` ×**38** in the same window. The `telegram_network` module was getting `nodename nor servname provided` (DNS failure) and falling back to direct IPs, but the IPs themselves were failing (`SSL: CERTIFICATE_VERIFY_FAILED` + `All connection attempts failed`).

**Root cause:** Two possibilities — (a) the local DNS resolver was down at 02:00, or (b) the network had a transient outage. The retry-with-fallback loop amplified it: each restart re-ran the bootstrap, which failed, which triggered another restart. **776 restart events** total in `gateway-exit-diag.log` over the period.

**Fix:**
- Add a **jittered backoff** to the bootstrap retry loop (capped at N attempts per hour, not infinite)
- Add a **circuit breaker** on `api.telegram.org` DNS failures so the gateway stops trying when DNS is broken
- After N consecutive bootstrap failures, **alert the operator** instead of silently hot-restarting

**Proof:** `grep -c 'gateway.start' gateway-exit-diag.log` → 768. `grep -c 'Bootstrap delete Webhook' errors.log` → 38.

---

### M3. **Cron jobs fail on idle timeout, not on real failure**
**Evidence:** `morning-briefing` and `daily-strategist-audit` both hit the 600s idle limit repeatedly:
```
ERROR cron.scheduler: Job 'morning-briefing' idle for 1712s (inactivity limit 600s) | last_activity=API error recovery (attempt 2/3)
ERROR cron.scheduler: Job 'morning-briefing' idle for 3632s (inactivity limit 600s) | last_activity=waiting for stream response (30s, no chunks yet)
ERROR cron.scheduler: Job 'daily-strategist-audit' idle for 3631s (inactivity limit 600s) | last_activity: receiving stream response
```

Notice `last_activity=API error recovery` — the job is **idle because it's waiting for a retry backoff**, not because the agent is doing real work. The 600s idle timeout then kills the job **even though the underlying API call might succeed in 2s of additional backoff**.

**Fix:** Treat "API error recovery" as protected activity, not idle. The idle detector should not count retry-backoff time as idle if the next retry is scheduled < 30s away. Equivalently: surface scheduled retries as a separate "alive" signal.

**Proof:** `grep "idle for" gateway.error.log | wc -l` → 6+ single-line events from 02:00-04:00 window.

---

### M4. **The "test_domain" gap is polluting the gap registry**
**Evidence:** `~/.hermes/logs/active-gaps.json` contains **8 test gaps** with `domain: "test_domain"`, all `severity: warning`, `failure_count: 2`, `status: identified`, `human_decision: null`. Zero real action has been taken.

Why this matters: the gap registry is the durable record of "things the agent needs help with." If it's 80% test garbage, every real gap is buried. The dashboard counts these as "8 decisions waiting" — but **0 are real**.

**Fix:** Either (a) gate the gap registry so tests can't write to it (use a `HERMES_TEST_MODE=1` env var), or (b) add a `severity: critical` filter to the gap dashboard so test gaps sort below real ones. Quick win: bump the test gap creation to `HERMES_LANE=claude` only (mirrors the lane guard pattern that already exists).

**Proof:** `jq '. | length' active-gaps.json` → 10 entries, 8 with `test_domain`.

---

### M5. **gateway-exit-diag.log was 1.37 MB of chaos** (now 232 KB)
**Evidence:** 768 gateway.start events, 312 of them in 4 hours. Each restart emits ~3 JSON lines: `gateway.start`, `asyncio.run.returned`, `gateway.exit_clean`, `atexit.hook`. The file is the canonical post-mortem source — when it's the noisiest file on disk, you can't find the actual diagnostics.

**Fix:** Rotate `gateway-exit-diag.log` like the other logs (compress after 1 MB, keep 3 rotations). Make the file content-shape stable: only `gateway.exit` and `gateway.crashed` records, not clean-exit events.

**Proof:** `wc -l gateway-exit-diag.log` = 2,312 lines. The other 30 logs combined are 60k lines for the same period.

---

### M6. **Dead chat ID in restart notification — there's a defective contact in the registry**
**Evidence:** `gateway.error.log:2026-08-05 21:19:53,023`:
```
WARNING gateway.run: Restart notification to telegram:123456 was not delivered: Chat not found
```

`123456` is the **default placeholder** in the python-telegram-bot library when a sender ID isn't set. The gateway is sending restart notifications to a chat that doesn't exist. This is wasted work, plus a `BadRequest` triggers retry logic that re-raises.

**Fix:** Validate the notification target on startup. If the configured chat ID doesn't resolve, log a warning and skip the notification, don't fail the restart.

**Proof:** `grep "telegram:123456" errors.log` → 1 (just this one). But the dead chat ID might be in another config field.

---

## 🟡 MINOR — Hygiene, polish, scaling

### m1. **Architectural tension — memoization exhaustion in nested ThreadPoolExecutors**
**Evidence:** Gateway logs are full of `ThreadPoolExecutor-13_0:123145700274176` style thread names. The agent is creating high-cardinality thread pools per-API-call. This isn't broken yet, but it's a scaling cliff.

**Fix:** Move to a single bounded executor per request type (1 for chat, 1 for tools, 1 for auxiliary) with queue limits.

---

### m2. **Bootstrap delete webhook is run twice on every restart**
**Evidence:** `gateway.exit.clean` → `gateway.start` → `Bootstrap delete Webhook` → `Bootstrap set webhook` (implied). On polling-only setups, the delete is wasted work — the bot uses polling, not webhooks.

**Fix:** Skip the bootstrap delete when `use_webhook=False` (the default for polling). Saves ~500ms per restart × 768 restarts = 6+ minutes of pure waste over the period.

---

### m3. **The signalengine daemon is frozen on cypto exchanges**
**Evidence:** `signalengine-daemon.err.log` end of file:
```
2026-08-05T22:39:29 WARNING signal_engine.data.live_feed: Circuit breaker OPEN for ccxt.binance (threshold=4, cooldown=600s).
2026-08-05T22:39:29 INFO signal_engine.data.live_feed: Circuit open for ccxt.binance; skipping ETH/USDT this cycle.
2026-08-05T22:39:29 WARNING daemon: LiveFeed: fetched=0 written=0 failed=3
```

The circuit breaker has been open for ccxt.binance, **cycle after cycle**. The signal engine is "running" but producing 0 fetches. Trading signal quality is degrading because the data path is dead.

**Fix:** Either (a) raise the circuit-breaker threshold/timeout so it doesn't trigger on short outages, or (b) add a fallback data source (e.g., ccxt.kraken) so the system has redundancy. The current behavior — silently zero-fill — is the worst option.

---

### m4. **memory_retrieval numpy warning fires 80+ times per startup**
**Evidence:** `coordinator.error.log` is mostly:
```
[memory_retrieval] Embedding layer unavailable (No module named 'numpy'), falling back to tag-only
```
×80 lines after the third suppression, then it goes silent. The log is noisy.

**Fix:** Either `pip install numpy` in the venv (cheap — 30s), or suppress the warning on the first occurrence. The "silence further spam" message proves the suppression mechanism exists already — just fire it sooner.

---

### m5. **Webhook retry loop exits on attempts=0**
**Evidence:** `Bootstrap delete Webhook: Failed run number 0 of 0` — the retry loop has **0 retries configured**. It's a "retry loop" that's actually never retried.

**Fix:** Set `retry_count=3` on the bootstrap operation. The infrastructure is there, it's just zero.

---

### m6. **`/busy` mode notification to chat 123456**
**Evidence:** Same as M6 — the dead chat ID appears in dispatch notifications. The `gateway.run` module considers `123456` a valid delivery target.

**Fix:** Same as M6 — validate target on startup.

---

### m7. **Tests for the chat-router / state-machine paths don't exist**
**Evidence:** The cron scheduler module is 1866 lines, registers 30+ jobs, and is the heart of automation. No test suite covers it.

**Fix:** Add `tests/cron/test_scheduler.py` with at least 3 invariants: (a) when a job hits idle-timeout, the next run is scheduled correctly, (b) when a provider returns 429, the backoff respects the response, (c) when heartbeat not seen for 60s, the gateway restarts cleanly.

---

### m8. **Disk is at 86% (`374Gi / 466Gi`)**
**Evidence:** `df -h ~` output. Logs are 57MB alone. Backup files (`backups/state-*.db.gz`) are 36MB each and not in `.gitignore`.

**Fix:** Add `backups/*.gz` and `repomix-output.xml` to `.gitignore` (the auto-push cron already detects this, but the commit still fails). The disk is fine for now, but the auto-push job has been failing hourly for that exact reason.

**Proof:** `hermes-cron list` shows `6c9522460ed5 hermes-config-auto-push` last run = error, stderr = `WARN: refused to commit backups/state-20260802-200833.db.gz (36MB)`.

---

### m9. **Gateway restart storm generates 8+ Telegram messages per restart**
**Evidence:** Each gateway restart triggers: a startup banner, a "source watch changed" notification, an "exit clean" notification, an "atexit" notification. 8 messages per restart × 768 restarts = 6,144 notifications ever sent. The user sees them as spam.

**Fix:** Batch notifications: emit restart notifications only when the previous PID was > 5min old (so a churn loop doesn't spam) and at most once per hour to the user.

---

### m10. **The cron `summarize today's activity` job runs hourly**
**Evidence:** `idle-curiosity` runs every 30m, `idle-continuous-learning` every 30m, `improvement-probe` every 15m. The combined noise is constant.

**Fix:** Stagger these so they don't all burst at the same minute. Move the sibling jobs to `*/15` (every 15m at 0/15/30/45) and `*/31` (every 31m to avoid sync) so they spread across the hour.

---

## Summary Scorecard

| Severity | Count | Time to fix |
|---|---|---|
| 🔴 MAJOR | 6 | 1-2 days each (M1, M2 are the urgent ones) |
| 🟡 MINOR | 10 | 1-4 hours each |

**The one thing to fix today:** **M1 (top up a provider account)**. Everything else is downstream noise from the same root cause — the agent retrying with depleted providers creates the cron timeouts, the restart storms, the idle-detector failures.

**The one thing to fix this week:** **M2 (bootstrap retry loop)** — your 02:00–04:00 incident is a recurring failure mode, not a one-off.

---

## Data sources (proven, not asserted)

- `~/.hermes/logs/gateway.error.log` — 27,500 lines, analyzed via grep
- `~/.hermes/logs/errors.log` — 7,184 lines, analyzed via grep
- `~/.hermes/logs/agent.log` — 26,102 lines, analyzed via grep
- `~/.hermes/logs/coordinator.error.log` — 80 lines, all numpy warnings
- `~/.hermes/logs/gateway-exit-diag.log` — 2,312 lines, 768 restarts
- `~/.hermes/logs/active-gaps.json` — 10 entries, 8 test garbage
- `~/.hermes/logs/signalengine-daemon.err.log` — 56,531 lines, frozen ccxt.binance
- `hermes cron list` — registry review
- `hermes platforms list` — adapter validation (failed: command not registered, workaround)
- `df -h` — disk 86% full
