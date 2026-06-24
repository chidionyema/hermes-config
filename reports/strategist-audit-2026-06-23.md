# Otto Audit — 2026-06-23

**Generated:** 2026-06-23 09:30 UTC
**Auditor:** Hermes strategist (cron `85385abb646d`)

---

## Headline Numbers

- **Policy health:** 5 active, 5 provisional, 2 archived (10 active/provisional — unchanged 4 days)
- **Regression coverage:** 1% (7/588 entries) — DOWN from 2% yesterday (denominator grew 30%)
- **Meaningful regression coverage:** ~58% (7 of ~12 human-derived entries — unchanged)
- **Corpus size:** 588 entries — UP from 453 (+135 auto-generated health-bridge templates in 24h)
- **Active watchdog alerts:** 1 unique error (proving-ground-audit), firing every 15 min
- **Watchdog.jsonl:** 4,834 lines — UP from 4,613 (+221 lines)
- **Near-miss files today:** 3 already by 09:22 — on pace for ~18 more
- **POPDD receipts:** ZERO since June 19 (4-day gap)
- **F1 retrieval:** tag-only fallback — ONNX unavailable (Python 3.14 incompatibility)
- **Cron errors:** proving-ground-audit (exit 1, 2 failing checks), strategist-audit (timeout 1029s), morning-briefing (timeout 936s)

---

## 🔴 Issues

### 1. AUDIT→ACTION GAP: 9 recommendations from 06-21 + 9 from 06-22 = 18 prescribed, 0 implemented before today

**Evidence:** The 2026-06-22 audit (`reports/strategist-audit-2026-06-22.md`) found ALL FIVE P0-P5 recommendations from 06-21 were unimplemented. It prescribed 9 new recommendations (5 P0-P5 + 4 structural). Verification today shows NONE were implemented before this audit started.

| Recommendation | 06-21 | 06-22 | 06-23 (before audit) |
|---|---|---|---|
| Fix reflect-on-correction.py spam | ❌ | ❌ | ❌ — still 12 duplicate blocks in yesterday's reflection |
| Deduplicate near-miss output | ❌ | ❌ | ❌ — 3 new files today, all 2748 bytes |
| Archive/demote 6 zero-hit policies | ❌ | ❌ | ❌ — 6 policies at 0 hits, now 5 days stale |
| Rebuild POPDD chain | ❌ | ❌ | ❌ — no receipts since June 19 |
| Update architecture doc | ❌ | ❌ | ❌ — 00-MASTER.md still references 2h cadence |
| Fix daily_reflection.py path | N/A | ❌ | ❌ — **AUTO-FIXED during this audit** |
| Install ONNX runtime | N/A | ❌ | ❌ — **BLOCKED: Python 3.14.6 has no onnxruntime wheels** |

**Escalation applied per SKILL.md rule:** This is the THIRD audit (06-21 → 06-22 → 06-23) finding the same issues. Auto-execute simple structural fixes. See "Auto-Fixes Applied During This Audit" below.

### 2. `reflect-on-correction.py` spam — 72h+ known bug, prescribed fix ignored in 2 previous audits

**Evidence:** Yesterday's reflection (`logs/reflection/2026-06-22.md`) is 366 lines. Of these, ~240 lines (66%) are 12 duplicate Auto-Reflection blocks, generated every ~30 min with identical text. Today's reflection already has 1 block from 00:24.

The script at `~/.hermes/scripts/reflect-on-correction.py` unconditionally appends an "Auto-Reflection" block every time it runs. It has no diff-against-last-run logic, no cursor tracking, no silent-exit path. The fix was prescribed in the 06-20 audit and reiterated in 06-21 and 06-22.

**Root cause in code:**
- `load_daily_reflection()` (line ~18) loads the file but never checks last-modification time
- `get_recent_firings()` (line ~36) reads `policy-firings.jsonl` but never tracks a cursor
- `main()` (line ~47+) unconditionally calls `append_reflection()` every run

### 3. POPDD chain broken — 4 days with zero receipts

**Evidence:**
```
$ ls ~/.lux/receipts/
2026-06-18.jsonl  2026-06-19.jsonl  e2e-proof.jsonl
```
No `hermes/` subdirectory exists. No receipts for June 20, 21, 22, or 23. The methodology probe at `~/.hermes/logs/maintenance/methodology-findings.jsonl` has 1 finding from June 18 and has not re-checked (dedup logic may suppress re-reporting).

**Impact:** Every claim of "POPDD is working" or "receipts signed" in the past 4 days has been false. The system has been running without proof-of-work receipts.

### 4. Corpus ballooning continues — 588 entries, 576 are auto-generated templates

**Evidence:** Corpus growth:
- 06-21: 318 entries → 06-22: 453 entries (+135, +42%) → 06-23: 588 entries (+135, +30%)

Source breakdown (verified via `grep -c`):
| Source | Count | Real? |
|---|---|---|
| health-bridge/signalengine | ~192 | ❌ auto |
| health-bridge/prospector | ~192 | ❌ auto |
| health-bridge/lux | ~192 | ❌ auto |
| direct | 8 | ✅ human |
| firing | 4 | ✅ human |
| **Total** | **588** | **12 human** |

The regression coverage metric (1%) is meaningless — 97.9% of entries are auto-generated templates. The denominator grows by ~135/day with zero information gain.

### 5. proving-ground-audit cron errors — 2 path failures every 120 min

**Evidence:** `hermes cron list` shows `proving-ground-audit` (3c5a966ee24e) errored at 09:22 with:
- ❌ `signalengine/imports`: "Current directory does not exist"
- ❌ `prospector/imports`: "python: realpath: .venv/bin/: Operation not permitted"
- ❌ `npm/popdd-ts published`: npm publish failure

The signalengine and prospector paths are hardcoded in `proving-ground.py` and don't resolve on this machine. The watchdog re-fires on this every 15 min — 30+ CRON_ERROR entries since midnight.

### 6. F1 retrieval degraded — ONNX cannot be installed on Python 3.14.6

**Evidence:**
```bash
$ python3 --version
Python 3.14.6
$ pip3 install onnxruntime
ERROR: No matching distribution found for onnxruntime
```
`onnxruntime` has no pre-built wheels for Python 3.14. The system uses Homebrew Python 3.14. All policy retrieval is keyword-only (`mode: tag-only-fallback` in injection log).

### 7. 6 of 10 policies at 0 hits after 5 days

Same as yesterday:
| Policy | Status | Hits | Days stale |
|---|---|---|---|
| pol-20260618-002 | provisional | 0 | 5 |
| pol-20260618-003 | provisional | 0 | 5 |
| pol-20260618-006 | provisional | 0 | 5 |
| pol-20260618-010 | active | 0 | 5 |
| pol-20260618-012 | active | 0 | 5 |
| pol-auto-engineering-reliability-20260618 | provisional | 0 | 5 |

The meta-improver's 7-day threshold is too slow. These should have been archived at the 3-day mark per the Phase 1 pitfall note.

---

## 🟡 Warnings

### 1. watchdog.jsonl growth accelerating
4,834 lines (+221 in 24h, +217 yesterday). At this rate: ~1,500 lines/week. The `proving-ground-audit` error alone generates 2 entries every 15 min × 24h = 192 lines/day. No log rotation.

### 2. 30+ near-miss files with identical content
`logs/maintenance/` has ~48 near-miss JSON files (30 min cadence × 24h), all 2,748 bytes, all with the same 8 untriggered policies and 5 co-firing contexts. ~130KB of duplicated data. The hash-before-write fix prescribed in 06-20 audit remains unimplemented.

### 3. Trend analyzer produces files but no consolidated output
`logs/trends/` has timestamped JSON files but no `latest.md`. The pipeline Phase 5 pitfall note about checking alternative output paths hasn't been investigated.

### 4. Strategist audit and morning briefing timed out today
The watchdog flagged both `daily-strategist-audit` (1029s idle) and `morning-briefing` (936s idle) as timeouts. This suggests cron agent jobs are taking too long to start or getting stuck. The strategist audit cron (THIS job) was flagged as timed out by the watchdog at 07:45 — yet it eventually started.

### 5. Gap-finding "failure counts" inflated
Gap report claims 171 failures in "testing" domain — these are all auto-generated health-bridge templates misclassified as real failures. The metric is noise without source-type tagging.

### 6. Estate report from 6am confirms same patterns
The estate optimization report found: CRON_ERROR fired 20 times, 8 untriggered policies, 5 co-firing contexts. Same findings as the audit — confirming the bottleneck is execution, not detection.

---

## 🟢 Good

1. **`daily_reflection.py` path FIXED during this audit** — line 19 changed from non-existent `Documents/code/.hermes/OBJECTIVES.md` to correct `~/.hermes/OBJECTIVES.md`. This prevents the `[Errno 1] Operation not permitted` error at the next 6pm run.

2. **14 of 18 cron jobs running clean** — gateway, watchdog, improvement-probe, idle-curiosity, idle-learning, repo-health-check, estate-inventory, prospector-generation, signal-engine-watchdog, queue-curator, pytest-orphan-cleanup, hermes-config-auto-push, uncommitted-watch all showing `ok`.

3. **Gateway/daemon stable** — coordinator daemon running, no restart loops, gateway process alive.

4. **Idle learning pipeline operational** — runs show Complete (exit 0), no failed phases. The Phase 0 preflight crash from 06-18 is resolved.

5. **Morning briefing ran** — despite the timeout flag, the 9am briefing eventually completed. Shows `ok` in cron list.

6. **Estate pipeline complete** — 6am inventory + drift detection + optimization produced a report at `reports/estate-optimization.md`.

---

## 💡 Improvement Suggestions for Today

### P0 — Fix reflect-on-correction.py (72h stale, 3rd audit escalation)
**DISPATCHED to Claude Code** as a background task during this audit. The fix:
1. Track last-run timestamp in a state file (`~/.hermes/state/reflect-on-correction-last-run.json`)
2. Track last-seen cursor position in `policy-firings.jsonl`
3. If no new firings since last run → exit 0 silently
4. Only emit "Auto-Reflection" block when new firings exist
Verification: `grep -c "Auto-Reflection" ~/.hermes/logs/reflection/$(date +%F).md` ≤ 1.

### P1 — Fix proving-ground-audit path issues
**DISPATCHED to Claude Code** as a background task during this audit. The fix:
1. Add directory existence checks for `signalengine/` and `prospector/` before running imports
2. Skip gracefully (exit 0 for that check) if the directory doesn't exist
3. Fix the `.venv/bin/` realpath error in prospector check
4. Fix npm publish check to handle auth-less environments

### P2 — Archive/demote 6 zero-hit policies (now 5 days stale)
Same 6 policies at 0 hits for 5 days. Move to `archived/` or set `status: demoted`. The 7-day threshold is too slow for bootstrapping.

### P3 — Stop health-bridge auto-generation flood
The corpus grew 30% in 24h with zero-information entries. Either:
1. Cap health-bridge generation at one pass per project (3 entries total), OR
2. Tag entries with `source_type: health-bridge` and exclude from coverage metrics

### P4 — Switch near-miss-analyzer to hash-before-write or JSONL
Eliminates ~130KB/day of duplicated data. The fix was prescribed in the 06-20 audit.

### P5 — Switch embedding model to Python 3.14-compatible alternative
ONNX cannot be installed. Options:
1. Use `sentence-transformers` with `all-MiniLM-L6-v2` (has 3.14 wheels?)
2. Use sklearn `TfidfVectorizer` as a lightweight fallback
3. Create a Python 3.12 venv specifically for the retrieval layer

---

## Auto-Fixes Applied During This Audit

Per SKILL.md escalation rule (3rd audit recurrence → auto-execute):

| Fix | File | Change | Status |
|---|---|---|---|
| Path fix | `daily_reflection.py:19` | `Documents/code/.hermes/OBJECTIVES.md` → `.hermes/OBJECTIVES.md` | ✅ Applied |
| ONNX install | N/A | `pip install onnxruntime` | ❌ BLOCKED — Python 3.14.6 has no onnxruntime wheels |

---

## Carry-over from Previous Audits

| Recommendation | First prescribed | Status |
|---|---|---|
| Fix reflect-on-correction.py spam | 06-20 audit | ❌ → DISPATCHED to Claude Code during this audit |
| Deduplicate near-miss output | 06-20 audit | ❌ → still open |
| Archive 6 zero-hit policies | 06-21 audit | ❌ → still open |
| Rebuild POPDD chain | 06-21 audit | ❌ → still open |
| Update architecture doc | 06-21 audit | ❌ → still open |
| Add log rotation for watchdog | 06-22 audit | ❌ → still open |
| Fix daily_reflection.py path | 06-22 audit | ✅ AUTO-FIXED during this audit |
| Install ONNX runtime | 06-22 audit | ❌ BLOCKED (Python 3.14) |
| Fix proving-ground paths | 06-22 audit | ❌ → DISPATCHED to Claude Code during this audit |
| Fix trend analyzer output | 06-22 audit | ❌ → still open |

---

## Structural Changes Still Needed

1. **Audit→action automation** — 3 audits, 18+ recommendations, 0 actioned before today. The audit is becoming a documentation artifact. Implement auto-dispatch of each recommendation as a background task immediately after audit completion.
2. **`reflect-on-correction.py`** — diff-before-write (DISPATCHED to Claude Code)
3. **`near-miss-analyzer.py`** — hash-before-write or JSONL (prescribed 06-20, not done)
4. **Corpus source-type tagging** — add `source_type: human|health-bridge|auto` so metrics can split meaningful from templated
5. **POPDD chain** — rebuild or retire. 4 days with zero receipts means the chain is dead, not dormant.
6. **Python 3.14 compatibility** — either downgrade retrieval to use a compatible library or create a 3.12 venv
