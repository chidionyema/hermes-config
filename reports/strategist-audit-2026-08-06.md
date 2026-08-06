## Otto Audit — 2026-08-06

**Policy health:** 10 active, 24 provisional, 0 retired/demoted  
**Regression coverage:** 79% (corpus: 325 entries)  
**Uncovered failures:** automation (1); infra/dispatch (2); engineering/research (1)  
**Active alerts:** 4 in latest watchdog summary; 19 open fingerprints

### 🔴 Issues
- Daily strategist audit is failing and silent-stretched: `last_run_at stuck at 2026-07-29T09:53:12`, 8 missed schedules (`~/.hermes/logs/alerts/watchdog.jsonl`, 2026-08-06T06:52:06Z).
- Morning briefing is blocked by HTTP 429 Token Plan usage limit (`~/.hermes/logs/alerts/watchdog.jsonl`, 2026-08-06T06:52:06Z).
- Reliability watchdog exits with `RELIABILITY: NOT PROVEN — state changed`, classified as CRON_ERROR (`~/.hermes/logs/alerts/watchdog.jsonl`, 2026-08-06T06:52:06Z).
- Latest health-bridge entries show dirty repositories: signalengine 24, lux 4, prospector 11 (`~/.hermes/logs/self-regression-corpus.json`, 2026-08-06T06:51:11Z).

### 🟡 Warnings
- Trend data covers 23 days but only 5 outcomes, all on 2026-06-18 (`~/.hermes/logs/trends/latest.json`).
- Gap report: automation uncovered; testing/task-management weak with 54/52 failures (`~/.hermes/logs/maintenance/gaps-2026-08-06.md`).
- Yesterday's reflection contains repeated auto-reflection blocks at 19:23:11 and 21:28:30 (`~/.hermes/logs/reflection/2026-08-05.md`).
- Long-untriggered policies remain: pol-20260618-008 (329 scans), -004 (283), -002/-003/-006/-010 (220 each) (`~/.hermes/logs/trends/latest.json`). Review rule text and chain metadata before archival.

### 🟢 Good
- Gateway is up with `daemon_up: true`, `restart_loop: false` (`~/.hermes/logs/alerts/watchdog.jsonl`, 2026-08-06T06:52:06Z).
- Silent-stretch alerts for idle-continuous-learning, idle-curiosity, and reflection-pulse-30m were marked `resolved`, `resolution: probe_verified` (`~/.hermes/logs/alerts/watchdog.jsonl`, 2026-08-06T06:52:06Z).
- Corpus continues receiving entries timestamped 2026-08-06T06:51:11Z.

### 💡 Improvement suggestions for today
1. Restore the strategist audit path: inspect its cron script/status, run it manually with a bounded timeout, fix the root cause, and verify `last_run_at` plus report creation.
2. Separate provider quota failures from script failures: route briefing/audit to an available provider or add explicit quota classification, then verify a successful run.
3. Add runtime probes for outcome ingestion and reflection cursor advancement; the trend is stale and reflection still duplicates blocks.
4. Deduplicate repeated dirty-repository health-bridge findings structurally and distinguish generated/runtime files from source changes.

### Evidence index
- Reflection: `~/.hermes/logs/reflection/2026-08-05.md` (5,350 bytes).
- Corpus: `~/.hermes/logs/self-regression-corpus.json` (111,672 bytes).
- Watchdog: `~/.hermes/logs/alerts/watchdog.jsonl` (9,292 rows).
- Trends: `~/.hermes/logs/trends/latest.json` (generated 2026-08-06T06:51:12Z).
- Gap report: `~/.hermes/logs/maintenance/gaps-2026-08-06.md`.
