# Otto Audit — 2026-06-22

**Generated:** 2026-06-22 08:00 UTC
**Auditor:** Hermes strategist (cron `85385abb646d`)

---

## Headline Numbers

- **Policy health:** 5 active, 5 provisional, 0 retired (10 total — unchanged from yesterday)
- **Regression coverage:** 2% (7/453 entries) — DOWN from 7/318 yesterday (denominator grew 42%, numerator flat)
- **Meaningful regression coverage:** ~37% (7 of ~19 human-derived entries — unchanged)
- **Corpus size:** 453 entries — UP from 318 (+135 auto-generated health-bridge templates in 24h)
- **Active watchdog alerts:** 2 unique errors, 131 open CRON_ERROR entries in last 24h
- **Idle learning runs:** Last 5 all Complete (exit 0), no failed phases
- **Near-miss files:** 155+ since June 18 — UP from 113 yesterday (+42 files, all structurally identical)
- **Trend files:** 140+ JSON files in `logs/trends/` — no `latest.md` exists
- **Watchdog.jsonl:** 4,613 lines — UP from 4,396 yesterday (+217 lines)
- **Cron jobs:** 18 total, 2 errored continuously for 5+ hours, 16 ok

---

## 🔴 Issues

### 1. ALL FIVE recommendations from 06-21 audit unimplemented — zero progress in 24h

**Evidence:** The 2026-06-21 audit (`reports/strategist-audit-2026-06-21.md`) prescribed 5 P0-P5 improvements and 4 structural changes. Verification today shows NONE were applied:

| Recommendation | Status | Evidence |
|---|---|---|
| P0: Fix reflect-on-correction.py spam | ❌ NOT DONE | 06-21 reflection still has 12 identical Auto-Reflection blocks across 317 lines |
| P1: Deduplicate near-miss output | ❌ NOT DONE | 42 new structurally-identical files since yesterday (155+ total) |
| P2: Archive/demote 6 zero-hit policies | ❌ NOT DONE | Same 6 policies at 0 hits, now 4+ days stale |
| P3: Rebuild POPDD chain | ❌ NOT DONE | Same single methodology finding from June 18, no follow-up |
| P4: Update architecture doc | ❌ NOT DONE | `00-MASTER.md` still references 2h cadence (actual: 30m) |
| P5: Add log rotation for watchdog | ❌ NOT DONE | watchdog.jsonl now 4,613 lines, still growing |

**Impact:** The daily strategist audit is producing recommendations that are filed but never actioned. The audit itself is becoming a documentation artifact rather than a change driver.

### 2. Two cron jobs errored continuously for 5+ hours overnight

**Evidence:** `watchdog.jsonl` shows these errors repeating every 15-min watchdog cycle from ~03:48 UTC to present (07:09 UTC last check):

- **`daily-self-reflection` (4fb05d17267d):** `Script exited with code 1 — Reflection failed: [Errno 1] Operation not permitted: '/Users/chidionyema/Documents/code/.hermes/OBJECTIVES.md'`
  - **Root cause:** `daily_reflection.py` line 19 has `OBJECTIVES_FILE = Path.home() / "Documents" / "code" / ".hermes" / "OBJECTIVES.md"` — this path does not exist. The actual OBJECTIVES.md is at `~/.hermes/OBJECTIVES.md` (and the script has a backup path for it at line 181, but error is on line 19's path).
  - **Fix:** Change line 19 to `OBJECTIVES_FILE = Path.home() / ".hermes" / "OBJECTIVES.md"` or remove the non-existent `Documents/code/.hermes/` path.

- **`proving-ground-audit` (3c5a966ee24e):** `Script exited with code 1` — 3 failures:
  - `signalengine/imports`: "Current directory does not exist" — the working directory in the script doesn't resolve
  - `prospector/imports`: "python: realpath: .venv/bin/: Operation not permitted" — venv path issue
  - `npm/popdd-ts published`: npm publish failure

**Impact:** 131 CRON_ERROR entries in 5h. These are drowning real signal. The watchdog is re-firing on the same errors every 15 minutes with no resolution.

### 3. `reflect-on-correction.py` spam persists — 48h+ known bug, prescribed fix ignored

**Evidence:** The 06-21 reflection file (`logs/reflection/2026-06-21.md`) is 317 lines. Of these, approximately 250 lines (79%) are 12 duplicate Auto-Reflection blocks, each with identical text, generated every 30 min from 19:24 to 23:57.

The fix was prescribed in the 06-20 audit and reiterated in the 06-21 audit: "Replace hardcoded 'Root cause' + 'Fix applied' strings with a diff against the last-run timestamp and the last-seen policy-firings.jsonl cursor; exit silently when no new firings."

**This has not been implemented.** The file `reflect-on-correction.py` needs to be patched.

### 4. Corpus ballooning — 135 auto-generated entries added in 24h, coverage metric degrading

**Evidence:** Corpus went from 318 → 453 entries in 24h. Breakdown:
- 12 direct (human-derived) — unchanged
- ~7 from firings — unchanged
- 1 from methodology probe — unchanged
- **~433 health-bridge auto-generated templates** — UP from ~298

All 135 new entries are "Would the new policy prevent [project] tests from failing unnoticed?" — auto-generated health-bridge templates. Zero information gain. Coverage dropped from 2.2% to 1.5% solely because the denominator is inflating.

**Domain breakdown of 453 entries:**
| Source | Count | Real? |
|---|---|---|
| health-bridge/signalengine | 145 | ❌ auto |
| health-bridge/prospector | 145 | ❌ auto |
| health-bridge/lux | 144 | ❌ auto |
| direct | 8 | ✅ human |
| self-audit | 5 | ✅ human |
| firing | 4 | ✅ human |
| reflection | 2 | ✅ human |

### 5. F1 retrieval layer degraded — ONNX not available, tag-only fallback

**Evidence:** Injection log at `logs/injection-log.jsonl` shows `mode: tag-only-fallback` on all recent retrievals. `python3 -c "import onnxruntime"` returns "ONNX NOT AVAILABLE." The embedding cache exists at `logs/retrieval/embedding_cache.pkl` but the runtime to use it isn't installed.

**Impact:** Semantic similarity search is disabled. All policy retrieval is keyword-only, which means policies with non-obvious trigger strings may not be injected.

### 6. 6 of 10 policies at 0 hits after 4+ days

**Evidence:** Policy store unchanged from yesterday:
| Policy | Status | Hits | Days stale |
|---|---|---|---|
| pol-20260618-002 | provisional | 0 | 4 |
| pol-20260618-003 | provisional | 0 | 4 |
| pol-20260618-006 | provisional | 0 | 4 |
| pol-20260618-010 | active | 0 | 4 |
| pol-20260618-012 | active | 0 | 4 |
| pol-auto-engineering-reliability-20260618 | provisional | 0 | 4 |

The meta-improver's 7-day demotion threshold means these won't be touched for 3 more days. Meanwhile, they occupy space in the retrieval index with zero benefit.

### 7. POPDD chain broken — 4 days, no resolution

**Evidence:** Single methodology finding from `2026-06-18T17:00:55Z`: "Most recent POPDD chain failed to load or verify — chain: /Users/chidionyema/.lux/receipts/e2e-proof.jsonl." No follow-up in 4 days. The methodology probe either isn't re-checking or found it once and dedup'd subsequent findings.

---

## 🟡 Warnings

### 1. watchdog.jsonl growing — now 4,613 lines, no rotation
+217 lines in 24h. At current rate: ~6,500 lines/week. Last 24h: 216 new entries, 131 of which were CRON_ERROR (61% error rate). The two overnight cron errors account for most of the growth.

### 2. Trend analyzer produces 140+ JSON files, zero consolidated output
`logs/trends/` has 140+ timestamped JSON files, each ~500 bytes. No `latest.md`, no consolidated view. Each file only differs by `generated_at` timestamp. Another case of structurally-identical output from a 30-min cycle script.

### 3. Proving ground audit has hardcoded paths that don't resolve on this machine
`signalengine/imports` says "Current directory does not exist" and `prospector/imports` has a `.venv/bin/` realpath error. These paths may be correct on another machine but don't resolve here.

### 4. Architecture doc still outdated
`00-MASTER.md` references 2h idle learning (actual: 30m), doesn't mention F1 retrieval or F2 eval confidence, and references model tiers that have drifted.

### 5. Gap-finding "failure counts" grossly inflated by auto-generated corpus
Gap report claims 171 failures in "testing" domain — these are auto-generated health-bridge templates counted as real failures. The metric is misleading without source-type tagging.

---

## 🟢 Good

1. **Idle learning pipeline stable** — last 5 runs all Complete (exit 0), no failed phases. The Phase 0 preflight errors that crashed the pipeline on 06-18 are resolved.
2. **14 of 18 cron jobs running clean** — gateway, watchdog, improvement-probe, idle-curiosity, idle-learning, repo-health-check, estate-inventory, prospector-generation, signal-engine-watchdog, queue-curator, pytest-orphan-cleanup, morning-briefing, hermes-config-auto-push, uncommitted-watch all showing `ok`.
3. **Gateway/daemon up** — `coordinator.py daemon` running, gateway process alive. No restart loops.
4. **Signal-engine-daemon-watchdog working** — was broken on 06-18 (wrong script path), now runs clean every 5 minutes.
5. **Policy firings log active** — 20 policy firings logged to `policy-firings.jsonl`. Policy-007 (ask-instead-of-do) dominates as expected — it's the catch-all for the most common failure mode.
6. **F1 injection log operational** — 3,229 bytes, tracking all retrieval injections even in tag-only-fallback mode.

---

## 💡 Improvement Suggestions for Today

### P0 — Fix the two overnight cron errors (breaking changes, silent for 5h+)
1. **`daily_reflection.py`:** Change line 19 from `Path.home() / "Documents" / "code" / ".hermes" / "OBJECTIVES.md"` to `Path.home() / ".hermes" / "OBJECTIVES.md"`. The path doesn't exist, and the script already has a backup path to the correct location at line 181.
2. **`proving-ground.py`:** Fix the working directories for `signalengine/imports` and `prospector/imports` — they don't resolve on this machine. Either add existence checks before running imports or correct the paths.

### P1 — Implement the `reflect-on-correction.py` diff-before-write fix (48h stale)
The fix is prescribed in SKILL.md Phase 0.5 pitfall note and both the 06-20 and 06-21 audits. Patch the script:
- Read last-run timestamp from state file
- Read last-seen cursor from policy-firings.jsonl
- If no new firings since last run → exit 0 silently
- Only emit "Auto-Reflection" block when new firings exist

Verification: `grep -c "Auto-Reflection" ~/.hermes/logs/reflection/$(date +%F).md` ≤ 1.

### P2 — Install ONNX runtime to restore semantic retrieval
```bash
pip install onnxruntime
```
The embedding cache exists at `logs/retrieval/embedding_cache.pkl`. The model is present. Only the runtime is missing.

### P3 — Stop or cap health-bridge auto-generation
The corpus grew 42% in 24h with zero-information auto-generated entries. Either:
1. Cap health-bridge generation at one pass per project (3 total entries, not 145 each), OR
2. Add `source_type: health-bridge` tags and exclude templated entries from coverage metrics

### P4 — Archive/demote the 6 zero-hit policies (now 4 days stale)
Same recommendation as yesterday. Move to `archived/` or set status to `demoted`. The 7-day threshold is too slow.

### P5 — Fix trend analyzer to produce `latest.md`
140+ JSON files with no consolidated output. Either add a post-processing step that generates `latest.md` or consolidate to append-only JSONL.

---

## Structural Changes Needed (not more policies)

1. **`daily_reflection.py` path fix** — hardcoded path to non-existent directory. Structural script fix.
2. **`reflect-on-correction.py` diff-before-write** — prescribed 48h ago, never implemented. Structural script fix.
3. **`near-miss-analyzer.py` switch to JSONL** — eliminates 155+ file noise pattern. Recommended yesterday, not done.
4. **Install ONNX runtime** — one `pip install`, restores semantic retrieval.
5. **Corpus tag system** — add `source_type: human|health-bridge|auto` to corpus entries so metrics can split meaningful from templated.
6. **The audit→action gap** — the 06-21 audit produced 9 recommendations (5 P0-P5 + 4 structural). Zero were implemented. The audit is producing recommendations faster than anyone (or any process) is actioning them. Either: (a) auto-execute the structural fixes during the audit itself, or (b) dispatch each recommendation as a cron task immediately after the audit completes. The current "file and forget" pattern means every audit re-discovers the same issues.
