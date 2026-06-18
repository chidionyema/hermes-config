# Prospector Pipeline Health Record (2026-06-18)

## State at Last Full Audit

- Test suite: **380 pass, 3 skip (golden set), 0 fail** — 36s full suite
- Catalogue: **16 PASS, 174 KILL, 8 DEFER**
- Coverage: **68%** (11,291 stmts)
  - Strengths: 36 test files at 100% (unit, behavioural, invariants, integration)
  - Gaps: operator.py (40%), retrieval.py (38%), run.py (30%), dedup.py (24%)
- Live pipeline: ✅ confirmed working with Gemini operator
- Deferred re-vet: 8 candidates (from retrieval outage era)

## Diagnostics Alerts (from `prospector run diagnose`)

1. **quality_decay** — rolling avg PASS score dropped to 2.69
2. **zero_yield (growth lane)** — 0 PASS across 30 ruled
3. **zero_yield (venture lane)** — 0 PASS across 31 ruled
4. **5 dead gates** — legality, pain_reality, payer_solvency, distribution never fire (behind kill-fast)

## API Key Inventory

All keys live in `~/.hermes/.env` and `~/Documents/code/prospector/.env`:

| Key | Status | Source |
|---|---|---|
| GEMINI_API_KEY | ✅ 53 chars | google-genai client |
| DEEPSEEK_API_KEY | ✅ 35 chars | DeepSeek API |
| ANTHROPIC_API_KEY | ✅ 108 chars | Anthropic API |
| MINIMAX_API_KEY | ✅ 125 chars | MiniMax API |
| EXA_API_KEY | ✅ 36 chars (UUID) | Exa search API |
| BRAVE_API_KEY | ❌ not present | User confirmed not needed |
| MINIMAX_GROUP_ID | ❌ not present | Optional — MiniMaxSearchProvider degrades gracefully |

## Cron Configuration

Single hourly job: `prospector-daily-generation` (job_id: df1c49144256)
- Schedule: `0 * * * *` (hourly at :00)
- Workdir: `~/Documents/code/prospector`
- Config: `candidates_per_signal: 20`
- Tests: golden set discriminations 1/1 PASS

## Known Limitations

1. CI gate (`scripts/ci-gate.sh`) will fail in automation because `.env` isn't sourced by the test runner. Need to wire auto-source into `conftest.py` or test runner.
2. `vet --resume` requires dummy `--title` flag due to argparse ordering — `--title` is required at parse time but handler checks `--resume` before `--title` in code.
3. Coverage on operator.py/retrieval.py is low (40%/38%) — the most critical modules (moat and grounding) have the least unit test coverage. End-to-end runs cover them partially.
