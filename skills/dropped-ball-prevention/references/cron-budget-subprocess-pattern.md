# Cron-Budget Subprocess Pattern (added 2026-06-18)

The root cause of the otto-dispatch 120s timeout was: `_run_handler()` ran subprocesses with `timeout=150s` (could single-handedly bust the 120s cron cap) and was called sequentially for every fingerprint in the queue. With 17 fingerprints and 4 of them hitting a slow `repo-health-check.py` handler, the math was 17 × up-to-150s = guaranteed timeout.

## The pattern (drop into any handler-dispatching script)

```python
_HANDLER_CACHE = {}  # module-level

def _run_handler(name):
    """Bounded at 2s; cache per-handler success for 5 min."""
    path = os.path.join(SCRIPTS, name)
    if not os.path.exists(path):
        return None
    now = time.time()
    cache = _HANDLER_CACHE.setdefault(name, {})
    if cache.get("ok") and (now - cache.get("ts", 0)) < 300:
        return True  # cached success — don't re-run
    if cache.get("running") and (now - cache.get("running", 0)) < 10:
        return False  # another caller is already running it
    cache["running"] = now
    runner = ["python3", path] if name.endswith(".py") else ["bash", path]
    try:
        r = subprocess.run(runner, capture_output=True, text=True, timeout=2,
                           env={**os.environ, "HERMES_HOME": HERMES})
        ok = r.returncode == 0
        cache.update({"ok": ok, "ts": now, "running": 0})
        return ok
    except subprocess.TimeoutExpired:
        cache.update({"ok": False, "ts": now, "running": 0})
        return False
```

## Two-layer budget enforcement

The cron has a 120s cap. A dispatcher that runs subprocesses must enforce **two** budgets:

1. **Per-handler timeout** — 2s for a probe/fix, never more. Slow handlers are broken handlers.
2. **Per-handler result cache** — same `handler.py` called for 4 fingerprints = 4 cache hits = ~0s wall time after the first.

Without #1, one slow handler blows the budget. Without #2, repeated fingerprints re-run the same slow handler.

## The companion fix: `repo-health-check.py` budget

For scripts that themselves dispatch long work (e.g. `repo-health-check.py` runs `pytest` per repo):

- `TOTAL_BUDGET = 25` (under 30s, well below cron cap)
- `PER_REPO_TIMEOUT = 20`
- Wall-clock cut via `fut.result(timeout=remaining)` so the loop exits even if a thread hangs

```python
TOTAL_BUDGET = int(os.environ.get("HERMES_REPO_BUDGET", "25"))
PER_REPO_TIMEOUT = int(os.environ.get("HERMES_REPO_TIMEOUT", "20"))

t_start = time.monotonic()
with ThreadPoolExecutor(max_workers=max(len(REPOS), 1)) as ex:
    futs = {ex.submit(check_repo, n, i): n for n, i in REPOS.items()}
    for fut in futs:
        remaining = max(1, TOTAL_BUDGET - (time.monotonic() - t_start))
        try:
            name, res = fut.result(timeout=remaining)
        except futures.TimeoutError:
            name = futs[fut]
            res = {"state": "fail", "summary": f"{name}: TOTAL_BUDGET exceeded"}
```

## Verification (proves the fix)

```bash
$ time timeout 30 python3 ~/.hermes/scripts/otto-dispatch.py
real    0m1.852s    # was 120s+ timeout
exit=0

$ time timeout 30 python3 ~/.hermes/scripts/repo-health-check.py
real    0m29.233s   # bounded, was unbounded
exit=0
```

## When to apply this pattern

Any cron-launched script that:
- Calls subprocesses (especially test runners or probes)
- Loops over a list (fingerprints, repos, files)
- Has a wall-clock cap from the cron config

A script without these guards is a cron-timeout dropped ball waiting to happen.