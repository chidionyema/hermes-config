# Hermes Log Analysis — Action Items (2026-08-05)

_Source: `~/.hermes/reports/log-analysis-2026-08-05.md` + `.json`_

## 🔴 Blockers (today)

### M1 — Top up provider (fallback chain is broken)
**Time:** 2 min · **Blocked on:** nothing (web payment)
**Action:** Top up DeepSeek ($2 min) OR disable exhausted providers via `/model`
**Evidence:** 232× Token Plan + 78× HTTP 402 + 60× Anthropic credits + 6× Gemini RESOURCE_EXHAUSTED

---

## 🔴 Code changes (this week, Claude's lane)

### M2 — Gateway restart storm at 02:00–04:00
**Time:** 1-2 days · **Files:** `gateway/run.py`, `gateway/source_watch.py`
**Fix:** jittered backoff + circuit breaker + operator alert after N bootstrap failures

### M3 — Cron jobs die on idle timeout during retry backoff
**Time:** 1 day · **Files:** `cron/scheduler.py`
**Fix:** idle detector should not count scheduled retry-backoff as idle

### M4 — test_domain gaps pollute gap registry (8/10 garbage)
**Time:** 1 hour · **Files:** `scripts/coordinator.py`
**Fix:** gate test gaps behind `HERMES_TEST_MODE=1` env var

### M5 — gateway-exit-diag.log noise (1.37 MB)
**Time:** 1 hour · **Files:** `gateway/run.py`
**Fix:** rotate log + drop clean-exit records

### M6 — Dead chat ID 123456 in restart notifications
**Time:** 30 min · **Files:** `gateway/run.py`
**Fix:** validate notification target on startup

---

## 🟡 Minor (housekeeping)

| # | Finding | Time |
|---|---|---|
| m1 | High-cardinality ThreadPoolExecutors | 2h |
| m2 | Bootstrap delete webhook runs on every polling-mode restart | 30m |
| m3 | signalengine frozen on ccxt.binance, fetched=0 | 1h |
| m4 | `No module named 'numpy'` warning fires 80× per startup | **30s** (pip install) |
| m5 | Bootstrap webhook retry loop has 0 retries | 5m |
| m7 | No test suite for cron scheduler (1866 lines) | 1 day |
| m8 | Disk at 86% + backups/*.gz not in .gitignore | 5m |
| m9 | 8+ Telegram notifications per restart (6,144 sent) | 2h |
| m10 | Cron jobs burst on same minute (no stagger) | 30m |

---

## Suggested sequence

1. **M1** (right now) — top up provider so the agent can work
2. **m4** (parallel, 30s) — `pip install numpy`
3. **m8** (parallel, 5m) — `.gitignore` backups + repomix
4. **M2** (this week) — gateway restart storm
5. **M3** (this week) — cron idle timeout
6. **M6, M5, M4** (Thursday) — cleanup pass
7. **m1, m2, m3, m5, m7, m9, m10** (Friday) — minor polish
