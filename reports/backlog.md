# Hermes Estate — Backlog

## BL-001 — signalengine pytest full suite hangs indefinitely (2026-06-20)
- **Symptom:** `uv run pytest -q` in `~/Documents/code/signalengine` never completes (confirmed live: >3min, no exit). Killed by repo-health probe's 20s cap every cron tick.
- **Likely cause:** a test spawns the popdd daemon (or similar long-lived process) and blocks on it without a timeout.
- **Impact:** the full test suite cannot be run unattended; only `pytest --collect-only` (imports/collection, ~6s, exit 0) is currently safe.
- **Done so far:** repo-health-check.py's signalengine `test_cmd` switched from the full suite to `pytest --collect-only -q` so the probe stops false-failing (the probe only needs a bounded importable/uncorrupted signal). The hang itself is NOT fixed.
- **Fix needed:** find the blocking test (bisect via `pytest --collect-only` works → run subsets), add a per-test timeout (`pytest-timeout`) or fix the daemon-spawning fixture to tear down / use a fake. Restore a real (bounded) test execution as the health signal once green.
- **Class:** test infra defect — unbounded workload under no timeout. Not a money/identity/contract item.
- **Owner:** signalengine (Aider territory per founder-fence override); verify hard on return.
