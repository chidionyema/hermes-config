# Slow Test Suite — Diagnosis & Optimization

A structured approach for when a project's test suite is too slow. Works for pytest, vitest, jest, or any runner with a `--durations` equivalent.

## Diagnosis Phase

### 1. Measure the Baseline

```bash
# Full suite — to confirm it's slow
\time pytest -q --tb=line 2>&1 | tail -5

# With per-test timing
pytest -q --tb=line --durations=0 2>&1 | head -30
```

The `--durations=0` output shows the 20 slowest tests. If the suite times out before producing this output, move to per-file profiling.

### 2. Per-File Profiling (for suites that time out)

Profile the suspected-large files individually:

```bash
for f in tests/test_slow_candidates*.py; do
  echo "=== $f ==="
  \time uv run pytest "$f" -q --tb=line --durations=0 -p no:cacheprovider 2>&1 | tail -10
  echo ""
done
```

### 3. Per-Test Profiling (for files that time out individually)

```bash
# List tests in the file
pytest tests/test_big.py --collect-only -q

# Profile each test
\time pytest tests/test_big.py::test_one -q --tb=line -p no:cacheprovider 2>&1 | tail -3
\time pytest tests/test_big.py::test_two -q --tb=line -p no:cacheprovider 2>&1 | tail -3
```

### 4. Identify Root Causes

| Observation | Likely cause |
|---|---|
| Single test >100s | End-to-end integration with real DB/network/backtest |
| Many tests ~0.2-2s each | Import overhead, fixture setup, data generation |
| Collection alone takes >10s | Large conftest.py, heavy module-level imports |
| xdist doesn't help | Tests share state (DB, files, singletons) |

## Optimization Phase

### Step 1: Mark Structurally Slow Tests

Some tests are slow by design (end-to-end backtests, DB round-trips, integration scenarios). These cannot be made fast — isolate them:

```python
# In the test file
import pytest

@pytest.mark.slow
def test_end_to_end_backtest():
    ...
```

```toml
# In pyproject.toml
[tool.pytest.ini_options]
markers = {"slow": "marks a test as slow (>30s); excluded by default"}
addopts = "-m 'not slow'"
```

```python
# conftest.py or pyproject.toml
# Register markers to avoid warnings
```

### Step 2: Parallelize the Fast Suite

```bash
uv add pytest-xdist

# Run fast tests in parallel
pytest -n auto -m "not slow"

# Verify the slow tests still pass
pytest -m slow -n auto
```

### Step 3: Verify New Baseline

```bash
# Fast suite time
\time pytest -n auto -m "not slow" -q --tb=line 2>&1 | tail -5

# Slow suite time
\time pytest -m slow -n auto -q --tb=line 2>&1 | tail -5
```

## Pitfalls

- **Symlink loop in pytest collection**: If pytest hangs during collection, check for recursive symlinks in test directories (e.g., a symlink to the parent directory). Use `-p no:cacheprovider` to bypass cache issues.
- **VIRTUAL_ENV mismatch**: If uv's warning shows the wrong venv, run explicitly with `uv run` instead of `pytest` directly.
- **xdist `-n auto` on M-series Macs**: Detects all efficiency+performance cores (e.g., 12). This works if tests are independent — but if they share a DuckDB or file, you'll hit contention and test flakiness.
- **`--durations` is truncated by timeout**: If the suite times out, you won't see the duration output. Switch to per-file profiling.
- **Marking tests `@pytest.mark.slow` is NOT changing a test to fix broken code**: It changes *which* tests run by default, not *how* a test verifies behavior. This is the one allowed exception to AGENTS.md Rule #8.

## Real Example

Signal Engine (309 tests, 30+ min):

1. `--durations=0` on individual files found: 1 test at 220s, 1 at 17s, 1 at 10s, 3 at ~100-190s
2. Marked all 6 as `@pytest.mark.slow`
3. Installed `pytest-xdist`, set `-m "not slow"` as default
4. Result: 308 fast tests, target <5 min (down from 30+)
5. Slow tests run separately with `pytest -m slow`
