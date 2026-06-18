# Python Project Checks (uv-managed)

For Python projects using `uv` (like signalengine), standard npm checks don't apply. Use uv-native commands instead.

## Lockfile Integrity
```bash
uv lock --check
```
Passes silently if clean. On failure, shows specific resolution conflict.

## Linting
```bash
uv run ruff check <src_dir> --statistics
```
Returns `0` issues if clean. Otherwise shows count by rule category (E/F/I/UP/B).

## Type Checking
```bash
uv run mypy <src_dir>
```

## Running Tests
```bash
uv run pytest tests/ -x -q --ignore=tests/test_slow_integration.py
```
Respect project conventions — some projects exclude certain test files by default.

## Known Project Conventions

### signalengine (`~/Documents/code/signalengine`)
- **Test dir:** `tests/` with conftest.py, sim_news.py, stub_venue.py for fixtures
- **Excluded tests by default:** `test_fitter.py`, `test_paper_loop`, `test_fit_universe.py`
  - `test_fit_universe.py` has **2 hanging tests** (block indefinitely): `test_fit_universe_fits_each_scope_and_persists`, `test_fit_universe_content_addressed_skip`. These need debugging in `fit_universe()` or `write_ohlcv`
- **Lint:** ruff config at `[tool.ruff]` in pyproject.toml — line length 100, target py311
- **Type checking:** mypy configured with `--ignore-missing-imports`
- **Test runner:** `uv run pytest tests/ -x -q` plus specific ignores
- **Lockfile:** uv.lock (109 packages, clean)
- **Project type:** Hatchling-based package, managed by uv

## Reporting for Python Projects

In the health report table, Python projects get:
- **Vulns:** N/A (unless npm deps exist — flag the project as mixed)
- **Outdated:** N/A (check pyproject.toml dependency ranges manually if needed)
- **Tests:** [n passing / m total] with hanging test notes
- **Lockfile:** ✅ uv.lock present or ❌ missing
- **Lint:** [n issues] or ✅ clean
