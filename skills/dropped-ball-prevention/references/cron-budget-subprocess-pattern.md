# Cron-Budget Subprocess Pattern (added 2026-06-18, extended 2026-06-19)

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

---

# Third anti-pattern: the probe that is shaped like the workload (added 2026-06-19)

The cron-budget pattern above fixes *timing*. The `hermes_fingerprint.py` reference fixes *dedup*. But there's a third failure mode the 2026-06-19 cron-audit caught that neither pattern addresses: **a probe that re-runs the workload it claims to verify**.

## The case

The dispatcher (`otto-dispatch.py`) ran `repo-health-check.py` — a full 3-repo pytest sweep — as a 2-second "probe" handler. Math: pytest sweep takes 25–120s. 2s probe budget. The handler could never finish, so it always returned non-zero, so the dispatcher could never mark the fingerprint as resolved, so the fingerprint re-fired every cron tick, so the dispatcher re-spawned pytest every 5 min, so load climbed to 95, so 64 pytest orphans piled up, so every other cron job timed out, so the user got alerts that looked like 5 unrelated failures. **One shape-of-probe defect, 5 cascading symptoms.**

## The rule

A probe's job is to *verify state cheaply*, not to re-execute the workload. A probe should:

1. Read existing state files (`~/.hermes/state/<name>.json`, `state/queue/state.json`, `logs/alerts/*.jsonl`).
2. Compare against the last known good baseline.
3. Return pass/fail + a one-line receipt in <500ms.

A probe that **runs the workload** is itself the workload. The cron-budget pattern's `timeout=2` is not a fix — it's a lie that masks the structural defect (probe-as-workload is the same class as `auto_handled = []` then `+= 1` in Python: type confusion between "thing that verifies" and "thing that does").

## Verification of state vs. re-running the work

| Operation | Cost | Use when |
|---|---|---|
| `cat ~/.hermes/state/<name>.json` | <10ms | Probing — the previous run wrote the state |
| `subprocess.run(handler.py, timeout=2)` | 2–120s | Workload execution, not probing |
| `git status --short` | <50ms | Probing — the git tree IS the state |
| `pytest tests/` | 30s+ | Workload execution, not probing |

## The fix pattern

Any handler invoked by the dispatcher's `_run_handler` must be split into two scripts:

- **`<name>-probe.sh`** — reads state, returns pass/fail in <500ms. This is what the dispatcher calls.
- **`<name>-run.sh`** — does the actual work. Scheduled by cron on its own cadence, writes state for the probe to read.

The 6-property probe contract (see `scripts/probe-template.sh` and `references/probe-contract.md`) is what the probe half must conform to. The defect the cron-audit caught was: **the dispatcher's handlers were workload scripts without separate probe scripts**.

**Audit any new dispatcher handler for this shape before wiring it:** does it have a corresponding `<name>-probe.sh`? If not, write one before adding the handler to the dispatcher. The probe should never import or call the workload.

---

# Fourth anti-pattern: uninitialized counter used as list (added 2026-06-19)

The same cron-audit also caught a Python bug in `otto-dispatch.py`:

```python
auto_handled = []    # list
# ...later...
auto_handled += 1    # TypeError: can only concatenate list (not "int") to list
```

This crashed the dispatcher on every self-heal attempt, so no alert was ever auto-resolved, so the queue grew unbounded. The fix is `auto_handled = 0` (or `auto_handled: int = 0` if you have a type checker).

## The structural lesson

Before any dispatcher or self-healing script reports "fixed", it must successfully run end-to-end at least once on real input. A script that crashes silently (exits non-zero with no receipt) is itself a dropped ball — the user sees "alert resolved" but actually the dispatcher crashed before resolving.

**Verification protocol for any new dispatcher:**

```bash
time timeout 30 python3 ~/.hermes/scripts/<dispatcher>.py
# Output must show:
#   - exit 0 with `auto_handled: N` where N > 0 against a real queue (work done)
#   - exit 0 with `auto_handled: 0` (silent-when-healthy, OK)
#   - exit 1 = the bug above or another crash
```

`exit 0` with no auto-handler output = the dispatcher crashed silently. `exit 0` with `auto_handled: 0` = no work to do (correct silent-when-healthy). `exit 1` = crash. Never accept "exit 0" as proof the dispatcher is working without the auto-handler receipt.

## Related: `MAX_RUNTIME` is dead code under a 120s cron cap

Discovered in the same audit: scripts that set `MAX_RUNTIME=300` and check it between phases **never reach 300s** under a 120s cron cap — cron SIGKILLs the script first, and `check_preempt` only runs *between* phases, not during. The fix is to enforce `MAX_RUNTIME` at the **outer** level (the cron config, not the script), and the script's internal `MAX_RUNTIME` should be `< cron cap`. Pattern: `cron timeout = 120`, script `MAX_RUNTIME = 100` (with 20s headroom for cleanup + receipt write). A script that depends on its own `MAX_RUNTIME` to bail out of slow work is broken — the cron cap is the real wall.

---

# Handback protocol for cron-audits (added 2026-06-19)

When delegating a cron-audit to Claude (via the `claude-code` skill, Mode 0), the handback must include:

1. **Commit SHA** (or explicit reason no commit was made — drift in working tree needs scope review)
2. **Push confirmation** if a remote exists
3. **Post-fix verification probes** (read-only, 4 minimum):
   - Cron job status (`hermes cron status` — jobs that were failing, what's their state now)
   - Orphan process count (`ps -axo pid,ppid,command | awk '$2==1 && /pytest|python|hermes|cron/'`)
   - Gateway status (`cat ~/.hermes/gateway_state.json` — running, restart loop state)
   - Watchdog log tail (`tail -5 ~/.hermes/logs/alerts/watchdog.jsonl`)
4. **Audit report path** (e.g. `~/.hermes/reports/cron-failure-rootcause-audit-<date>.md`)

**Format as receipt, not narrative.** Each probe result: command run, exit code, key output line, conclusion. Tables over prose.

If Claude's handback is missing the commit, do not auto-commit. Inspect `git status --short` first. If the diff is exactly Claude's claimed fixes (≤N files, all in scope), commit and push. If the diff includes drift Claude didn't claim, **stop and ask the user** — "Claude fixed 4 files but the working tree has 24 modified + 7 untracked. Commit just the 4, or include drift?" Scope discipline on commits is non-negotiable.
