# Signal Engine — Next Ship Item (2026-08-09)

## Diagnosis method (read-only, reproducible)
```
cd ~/Documents/code/signalengine
git log --oneline -30            # recent work: CI gate, POPDD signing, salvage merge, @slow markers
git status --short                # large uncommitted WIP already staged/unstaged (12 files)
uv run pytest -q -m "not slow"    # full non-slow suite
```

## (1) The one objective
Fix the no-lookahead boundary inconsistency in `calculate_momentum()`
(`signal_engine/features/numeric.py:30`), which an **uncommitted, currently-staged** change
switched from `timestamp_utc <= as_of` to `timestamp_utc < as_of` — while every other feature
primitive in the same file (`calculate_realized_volatility` line 53, `_filtered_sorted` line 77
used by z-score/others) still filters with `<= as_of`.

This one-line inconsistency breaks the row-count/row-index alignment contract that
`simulate_segment()` (`signal_engine/validation/walkforward.py:75`,
`computed_features.row(global_idx, named=True)`) and `run_m1.py:275` rely on: the feature frame
is assumed to have exactly as many rows, at the same indices, as the input history slice. When
momentum's filter drops one extra trailing row relative to the other primitives, the loop walks
off the end of the (now shorter) frame.

Confirmed as root cause of 4 of 4 non-slow test failures, live on this branch right now
(`uv run pytest -q -m "not slow"`, exit code non-zero):

- `tests/test_m1_acceptance.py::test_walkforward_reports_oos_only` — `polars.exceptions.OutOfBoundsError: index 454 is out of bounds for sequence of length 454`
- `tests/test_m1_acceptance.py::test_e2e_pipeline_emits_signal_metrics_logs_heartbeat` — same error class, index 408/length 408
- `tests/test_m2_validation.py::test_cpcv_integration` — same error class, index 78/length 78
- `tests/test_paper_loop.py::test_precomputed_features_match_bar_at_a_time` — `momentum_30d` row-count mismatch (20 vs 18) between the pre-computed-panel path and the bar-at-a-time path — the *same* `<` vs `<=` divergence, caught from the other direction (this is literally the test that exists to guard the Determinism Boundary/no-lookahead invariant the README calls "foundational").

This is the highest-leverage next ship item because: (a) it is a regression already sitting
uncommitted in the working tree — not speculative backlog, it is blocking the very tests that
gate M1/M2 acceptance and CI (README's "Engineering Standards: Always Test, Verify, and Prove",
`docs/HANDOVER_M1.md`, `PLAN.md` D9 determinism CI guard); (b) it breaks the walk-forward + CPCV
+ E2E harness — the harness is called out in the README/PLAN.md as "the spine", built before any
strategy work is trusted; (c) the fix is small and mechanical (pick one boundary convention and
make `calculate_momentum` consistent with the rest of the file), so it can ship today and unblock
everything queued behind the red CI gate (`5bd5ea4 feat: CI pipeline with golden-set gate`).

## (2) Acceptance test
```bash
cd ~/Documents/code/signalengine && uv run pytest -q -m "not slow" \
  tests/test_m1_acceptance.py::test_walkforward_reports_oos_only \
  tests/test_m1_acceptance.py::test_e2e_pipeline_emits_signal_metrics_logs_heartbeat \
  tests/test_m2_validation.py::test_cpcv_integration \
  tests/test_paper_loop.py::test_precomputed_features_match_bar_at_a_time
```
Exit code 0 with all 4 passing = fixed. (Full-suite `uv run pytest -q -m "not slow"` should also
be green afterward — these were the only 4 non-slow failures observed.)

## (3) Files to touch
- `signal_engine/features/numeric.py` — `calculate_momentum()` (line ~30): change the filter back
  to `timestamp_utc <= as_of` to match `calculate_realized_volatility` and `_filtered_sorted`, **or**
  (if `<` was an intentional stricter no-lookahead tightening) instead change the *other* two
  primitives to `<` and re-verify — but pick ONE convention for the whole file. Given the
  docstring/comment in every other function still says "filters to timestamp_utc <= as_of to
  prevent lookahead" and only this one function's comment+code were edited, `<=` is almost
  certainly the intended, unedited convention and `<` is the regression.
- `signal_engine/validation/walkforward.py` (`simulate_segment`, line ~75) — no change expected if
  the above restores row-count parity, but re-run after the fix to confirm the
  `computed_features.row(global_idx, ...)` indexing assumption is genuinely restored, not just
  coincidentally passing.
- `tests/test_features.py`, `tests/test_m7_execution.py`, `tests/test_validation.py` — already
  modified uncommitted in this working tree (part of the same in-flight change); review whether
  they were updated to *expect* the `<` behavior (in which case they need reverting alongside
  `numeric.py`) or are unrelated — `git diff -- tests/test_features.py` before touching anything.

## (4) Risks
- **Two divergent intents may both be "correct" in isolation.** If the `<` change to
  `calculate_momentum` was a deliberate tightening (not a slip) tied to the other uncommitted
  changes in `signal_engine/research/fitter.py` / `fit_store.py` / `obs/bayesian.py` (also
  modified, unreviewed in this pass), flipping it back could silently reintroduce whatever
  lookahead edge case motivated the change. Read `git diff -- signal_engine/features/numeric.py
  tests/test_features.py` in full before editing — this report only confirms the *symptom and
  most likely direction*, not full intent.
- **Uncommitted working tree is large (12 files, incl. `config.py`, `worldview_state.py`,
  `fitter.py`, `fit_store.py`) and partially staged (`MM`).** The fix must not get bundled into an
  unrelated commit; isolate it.
- **Money-adjacent surface**: `walkforward.py`/`cpcv` feed the OOS Sharpe/cost numbers that gate
  strategy promotion (PLAN.md M2 "promotion gate"). A wrong boundary choice here changes reported
  edge, not just test pass/fail — verify with `tests/test_determinism.py` (lookahead guard) too,
  not only the 4 tests listed above.
- Working tree also has stray non-source artifacts (`daemon.log`, `daemon.err.log`,
  `test.duckdb`, `.lux/receipts/...`, `data/antigravity.db-shm/-wal`) mixed into `git status` —
  not part of this objective, but flag before any commit so they aren't swept in.
