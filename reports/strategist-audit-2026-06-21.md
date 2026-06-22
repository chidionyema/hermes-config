# Otto Audit — 2026-06-21

**Generated:** 2026-06-21 08:00 UTC
**Auditor:** Claude/Gemini strategist (via cron `85385abb646d`)

---

## Headline Numbers

- **Policy health:** 5 active, 5 provisional, 0 retired (10 total)
- **Regression coverage:** 2% (7/318 entries covered)
- **Meaningful regression coverage:** ~37% (7 of ~19 human-derived entries)
- **Corpus size:** 318 entries (96% auto-generated health-bridge templates)
- **Active watchdog alerts:** 0 since 06:00 UTC
- **Idle learning runs:** 88 total, last 3 all Complete (exit 0)
- **Near-miss files:** 113 files since June 18 (all structurally identical)
- **Watchdog.jsonl:** 4,396 lines / 1.0MB (grew from 4,092 lines yesterday)

---

## 🔴 Issues

### 1. `reflect-on-correction.py` still spamming — fix from 06-20 audit UNIMPLEMENTED
**Evidence:** `/Users/chidionyema/.hermes/logs/reflection/2026-06-20.md` lines 79-285 contain 8 identical "Auto-Reflection" blocks, each with the same text:
```
Root cause: Policy 004 (reflect-on-correction) has 0 hits and confidence 0.3
Fix applied: 1. Added post-correction reflection hook 2. Will promote policy 004...
```
The SKILL.md's own pitfall note (Phase 0.5, marked 2026-06-20) prescribes the fix: *"Replace hardcoded 'Root cause' + 'Fix applied' strings with a diff against the last-run timestamp and the last-seen policy-firings.jsonl cursor; exit silently when no new firings."* This was never implemented. The script still fires every 30 min producing identical output.

**Impact:** Daily reflection file is unusable. 285 lines of which 207 (73%) are duplicate noise.

### 2. 113 near-miss files with identical structure — 280KB of duplicated data
**Evidence:** `near-miss-analyzer.py` generates a file every 30 min. All 113 files from 2026-06-18 to 2026-06-21 have:
- Same 5 keys: `co_firing_contexts`, `domain_coverage_gaps`, `generated_at`, `total_firings`, `untriggered_policies`
- Same 8 untriggered policies (same IDs, same hit counts)
- Same 5 co-firing contexts
- Same 1 domain coverage gap
- Same `total_firings: 20`

Only `generated_at` differs. Zero new information per cycle.

**Impact:** Disk waste, noise in maintenance directory (113 files), zero signal-to-noise improvement over time.

### 3. POPDD chain broken since June 18 — never resolved
**Evidence:** `/Users/chidionyema/.hermes/logs/maintenance/methodology-findings.jsonl` contains a single entry from `2026-06-18T17:00:55Z`:
```
trigger: Most recent POPDD chain failed to load or verify
chain: /Users/chidionyema/.lux/receipts/e2e-proof.jsonl
```
No follow-up resolution. The methodology probe (every 15m) found this once and apparently hasn't re-reported — either it was fixed silently or the probe itself is not re-checking.

### 4. Estate optimization marks actions done but cron jobs still error
**Evidence:** `reports/estate-optimization.md` (2026-06-21 07:13) lists `fix_recurring_cron_error` as `[x]` done (priority: high). But watchdog recorded `estate-inventory-audit` exit-1 at 05:00 UTC and `repo-health-check` timeout at 05:24 UTC — both AFTER the report says fixes are applied. Actions are marked complete on paper but scripts still fail on disk.

### 5. 6 of 10 policies have 0 hits after 3+ days — overdue for demotion
**Evidence:** Policy store at `/Users/chidionyema/.hermes/policies/`:
| Policy | Status | Hits | Created | Days with 0 hits |
|---|---|---|---|---|
| pol-20260618-002 | provisional | 0 | Jun 18 | 3+ |
| pol-20260618-003 | provisional | 0 | Jun 18 | 3+ |
| pol-20260618-006 | provisional | 0 | Jun 18 | 3+ |
| pol-20260618-010 | active | 0 | Jun 18 | 3+ |
| pol-20260618-012 | active | 0 | Jun 18 | 3+ |
| pol-auto-engineering-reliability-20260618 | provisional | 0 | Jun 18 | 3+ |

The meta-improver is supposed to auto-demote policies with 0 hits after 7 days. But all 6 are at 3+ days with 0 confidence increase — they should be flagged now, not wait 4 more days. The idle-learning pipeline's promotion/demotion logic isn't surface-active enough.

---

## 🟡 Warnings

### 1. watchdog.jsonl at 1.0MB (4,396 lines) — still growing
Was 1MB+ / 4,092 lines at 06-20 audit. Now 4,396 (+304 lines in 24h). At this rate: ~9,000 lines/month. No log rotation configured.

### 2. Architecture doc outdated
`00-MASTER.md` line 54: "Every 2h: Idle continuous learning" — actual cron is every 30m (`3fcdc6bd8859`). The doc also references model tiers that drifted (config now says MiniMax-M3 as default, not Claude Sonnet).

### 3. Trend analysis never produced output
`trends/latest.md` doesn't exist. `trend-analyzer.py` runs in Phase 5 of idle pipeline but either silently fails or writes elsewhere. No cross-session trend data available.

### 4. Gap-finding "failure counts" are inflated by auto-generated corpus entries
Gap report claims 171 failures in "testing" domain, 171 in "task-management." These are counting every auto-generated health-bridge corpus entry — not real failures. The metric is misleading. Real human-derived entries: ~12 in direct corpus, ~7 from firing logs. Total meaningful corpus: ~19.

### 5. Corpus at 318 entries but only ~6% are real
318 total: 12 direct + ~7 from firings + 1 from methodology probe = ~20 human-derived. Remaining ~298 are "Would policy now prevent..." health-bridge templates — auto-generated, identical structure, zero information gain after the first generation.

---

## 🟢 Good

1. **Watchdog currently healthy** — 0 alerts since ~06:00 UTC. The 3-alert spike at 05:24 UTC (repo-health-check timeout, estate exit-1, proving-ground exit-1) auto-resolved by 05:53.
2. **All cron jobs "ok" on last run** — 18 active cron jobs, all showing `ok` status. The signal-engine-daemon-watchdog that was broken on 06-18 (wrong script path) is now working.
3. **Idle learning pipeline stable** — last 3 runs all Complete (exit 0), no failed phases. The Phase 0 preflight error that was crashing the pipeline on 06-18 is resolved.
4. **No new user corrections on 06-20** — reflection file shows empty correction table. Either Otto was idle or operated without needing correction. (Cannot distinguish from data alone.)
5. **Estate pipeline running** — estate-inventory-audit, repo-health-check, and proving-ground-audit all executing on schedule despite occasional timeout/exit-1 events.
6. **F1 retrieval layer operational** — embedding cache at `~/.hermes/logs/retrieval/embedding_cache.pkl`, injection log at `~/.hermes/logs/injection-log.jsonl`.

---

## 💡 Improvement Suggestions for Today

### P0 — Fix reflect-on-correction.py spam
The fix is specified in SKILL.md Phase 0.5 pitfall note but never implemented. Patch the script:
```bash
# In reflect-on-correction.py:
# 1. Read last-run timestamp from state file
# 2. Read last-seen cursor from policy-firings.jsonl
# 3. If no new firings since last run → exit 0 silently (no output)
# 4. Only emit "Auto-Reflection" block when new firings exist
```
**Verification:** `grep -c "Auto-Reflection" ~/.hermes/logs/reflection/$(date +%F).md` should be ≤1 by end of day.

### P1 — Deduplicate near-miss output
Two options:
1. **Append-only JSONL log** — write one line per cycle to `near-miss-log.jsonl` instead of one file per run. Easy to implement, natural dedup (identical entries are visible but don't create file clutter).
2. **Hash-before-write** — compute structural hash (exclude `generated_at`), compare to last file, skip write if identical. Keeps file-per-run but eliminates duplicates.

Recommend option 1 (JSONL) — simpler, less state management, naturally deduped by reader.

### P2 — Archive/demote 0-hit policies
The 6 policies with 0 hits after 3+ days should be demoted to `archived/`:
```
pol-20260618-002 (infra/dispatch — blocked conversation)
pol-20260618-003 (decision-making — presented options)
pol-20260618-006 (engineering/research — guessed API signatures)
pol-20260618-010 (engineering/verification — asked about status)
pol-20260618-012 (infra/dispatch — delegated tests to subagent)
pol-auto-engineering-reliability-20260618 (auto-generated, never triggered)
```
These haven't fired because: (a) the structural gates (dispatch-guard.py, policy-enforcer.py) already prevent the violation before the policy fires, or (b) the pattern hasn't recurred. Either way, 3 days of silence = demote. The meta-improver's 7-day threshold is too slow for the early bootstrapping phase.

### P3 — Rebuild POPDD chain
The methodology probe found e2e-proof.jsonl broken. Either:
1. Archive the old chain and start a fresh one
2. Verify if the chain was silently fixed (re-run the probe)
3. If the probe isn't re-checking (only found once), fix the probe logic

### P4 — Update architecture doc
Sync `00-MASTER.md` with reality: idle learning cadence (30m not 2h), model tiers (probe config, don't hardcode), F1 retrieval (not mentioned), F2 eval confidence (not mentioned).

### P5 — Add log rotation for watchdog.jsonl
At 1.0MB and growing ~300 lines/day, add a 30-day rotation or cap at 10,000 lines.

---

## Structural Changes Needed (not more policies)

1. **reflect-on-correction.py must be patched** — structural script fix, not a policy about remembering to fix it
2. **near-miss-analyzer.py should use append-only JSONL** — eliminates 113-file noise pattern
3. **meta-improver demotion threshold should be 3 days for provisional policies** (not 7) during bootstrapping phase — config change in meta-improver, not a new policy
4. **Corpus tag system needed** — add `source_type: human|health-bridge|auto` to corpus entries so coverage metrics can split meaningful from templated
