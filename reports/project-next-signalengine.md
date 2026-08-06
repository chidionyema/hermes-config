# Signal Engine — next ship item (2026-08-06)

## Investigation trail (read-only)

- Repo: `~/Documents/code/signalengine`, branch `salvage/c9-c10-m7-relocate`, HEAD `fddef58`
  (2026-06-20). `git log -30` shows steady work landing determinism/perf/dashboard fixes.
- `git status --short` shows **12 files already staged** (`config.py`, `research/fit_store.py`,
  `research/fitter.py`, `tests/conftest.py`, `obs/bayesian.py`, `obs/health.py`,
  `data/ingest/worldview_state.py`, `api/app.py`, `popdd_agent.py`, `pyproject.toml`, `uv.lock`)
  — a substantial, well-documented DB-contention/test-isolation hardening pass (see
  `tests/conftest.py`'s new docstring explaining the module-vs-function fixture-scope bug it
  fixes) that reads as essentially finished and ready to commit.
- Sitting **unstaged on top of that**, two small diffs in the numeric core:
  - `signal_engine/validation/cpcv.py`: `test_end = (i + 1) * split_size if i < n_splits - 1 else
    n_samples` was changed to `if i <= n_splits - 1`. Since the loop is `for i in
    range(n_splits)`, `i <= n_splits - 1` is **always true** — the `else n_samples` branch is now
    dead code.
  - `signal_engine/features/numeric.py`: the docstring for `calculate_momentum` was tightened from
    "`timestamp_utc <= as_of`" to "`timestamp_utc < as_of` to prevent lookahead", but the actual
    filter line was **not** changed — it still reads `df.filter(pl.col("timestamp_utc") <=
    as_of)`.

## Root cause, proven live

1. **CPCV silently drops the most recent out-of-sample bars whenever `n_samples % n_splits !=
   0`.** Reproduced live:
   ```
   n_samples=23, n_splits=5 → total test-set coverage = 20 (should be 23); 3 samples dropped
   ```
   (`.venv/bin/python3 -c "from signal_engine.validation.cpcv import generate_cpcv_splits; ..."`,
   run 2026-08-06.) Existing tests never catch this because both `tests/test_validation.py:45`
   (`test_cpcv_purge_embargo`) and `tests/test_m2_validation.py:175` use sample counts that divide
   evenly by `n_splits` — a real coverage gap, not just a code bug. This directly undermines the
   project's own stated #1 risk in `PLAN.md` §5 ("Multiple-testing illusion... every config goes
   in the trial log; scoring uses Deflated Sharpe") — the OOS scoring this bug feeds is the gate
   that promotes a strategy toward the capital ramp in M7.

2. **`calculate_momentum` still admits a not-yet-closed bar** — a real, not cosmetic,
   no-lookahead violation. Per the project's own documented convention (`as_of = timestamp_utc +
   bar_duration`, i.e. `as_of` is a bar's **close** time — see
   `signal_engine/data/ingest/ccxt_crypto.py:61` and `docs/HANDOVER_AIDER_REMAINING.md:88`), a row
   whose `timestamp_utc` (bar **start**) equals the caller's `as_of` decision boundary is the
   **next** bar, which has not closed yet. `<=` lets it through; the docstring edit correctly
   diagnosed this but the code line was never updated to `<`. `tests/test_determinism.py` doesn't
   catch it because it sets `as_of = df["timestamp_utc"].max()` (the last bar's own start, not a
   boundary that lands on the next bar).

Both bugs are currently **uncommitted and untested** — exactly the state where they're cheapest to
catch and most dangerous to ship silently on top of an otherwise-ready staged commit. Confirmed
still green elsewhere: `.venv/bin/pytest tests/test_determinism.py tests/test_validation.py
tests/test_features.py tests/test_m2_validation.py -q` → 13 passed (2026-08-06) — the suite is
healthy, it just has a coverage gap around exactly these two edge cases.

## The one objective

Fix both regressions in the numeric/validation core, add regression tests that would have caught
each, confirm the full non-slow suite is still green, then commit the fix together with the
already-staged hardening pass (or as an immediate follow-up commit) — before anything from this
worktree lands on `main`/`m1-vertical-slice`.

## Files to touch

- `signal_engine/validation/cpcv.py` — revert `if i <= n_splits - 1` to `if i < n_splits - 1`
  (restores the "last fold absorbs the remainder" behavior).
- `signal_engine/features/numeric.py` — change the filter to `pl.col("timestamp_utc") < as_of`
  so code matches its own docstring and the project's close-time `as_of` convention.
- `tests/test_validation.py` (or a new `tests/test_cpcv_edge_cases.py`) — add a case with
  `n_samples % n_splits != 0` asserting `sum(len(test) for _, test in splits) == n_samples`.
- `tests/test_features.py` — add a case where a row's `timestamp_utc == as_of` and assert it is
  excluded from `calculate_momentum`'s output.
- No changes needed to the already-staged 12 files — they're in scope only for the "run full
  suite before commit" step, not for editing.

## Acceptance test

Read-only, live-derived, exits 0 only once both regressions are actually fixed (currently exits 1
— verified 2026-08-06):

```bash
cd /Users/chidionyema/Documents/code/signalengine && .venv/bin/python3 -c "
from signal_engine.validation.cpcv import generate_cpcv_splits
n, k = 23, 5
total = sum(len(t) for _, t in generate_cpcv_splits(n, k, 0, 0))
assert total == n, f'CPCV drops {n-total} of {n} OOS samples (off-by-one regression)'
src = open('signal_engine/features/numeric.py').read()
body = src.split('def calculate_momentum')[1].split('def ')[0]
assert 'timestamp_utc < as_of' in body, 'calculate_momentum still uses <= as_of, contradicting its own no-lookahead docstring'
print('OK: CPCV coverage + no-lookahead filter both correct')
"
```

## Risks

- **Money-adjacent, not money-live**: the system only trades paper (Binance testnet); no real
  capital is at risk today. But CPCV/OOS scoring is the exact mechanism `PLAN.md` names as the
  gate for the eventual live capital ramp (M7) — a silent OOS-shrinkage or lookahead bug here is
  the class of bug that "fakes most great backtests" per the project's own risk list, so it should
  be treated with money-adjacent care even pre-capital.
- **Scope creep risk**: the 12 already-staged files are a large, unrelated (DB-contention/test
  isolation) change sitting in the same working tree. Don't get pulled into reviewing/expanding
  that work under this ticket — the ask here is narrowly the two regressions plus their tests. Do
  run the full non-slow suite once before committing anything, since the staged changes and the
  fix could interact (e.g. `tests/conftest.py`'s new session-scoped DB isolation could mask or
  interact with the new CPCV/momentum tests).
- **Fix direction on `numeric.py` is a judgment call made from evidence, not a coin flip**: I
  resolved "align code to docstring (`<`)" rather than "align docstring to code (`<=`)" using the
  documented `as_of = timestamp_utc + bar_duration` convention (close-time semantics). If that
  convention is wrong or changes, the correct fix flips — worth a second pair of eyes on
  `docs/HANDOVER_AIDER_REMAINING.md:88` and `ccxt_crypto.py:61` before landing.
