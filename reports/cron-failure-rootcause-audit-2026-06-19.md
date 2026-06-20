# Cron-Failure Root-Cause Audit — 2026-06-19 (auditor: Claude, coordinator: Otto)

## TL;DR
A single root bug — `subprocess` timeouts that kill only the `/bin/sh` parent and
orphan the `pytest` grandchildren — produced a 64-process orphan pile-up that drove
**load average to 95**. At load 95 *everything else* timed out (idle-learning, git
status, the gateway), which is why the failures looked unrelated. Reaping the
orphans dropped load 95 → 6.5. The bug existed in **two** test-spawning scripts and
was *amplified* by the dispatcher re-running the full pytest suite as a 2s "probe"
every 5 minutes. Plus one genuine crash bug Otto introduced in the dispatcher.

## Root cause per failure
1. **idle-continuous-learning timeout >120s** — symptom of CPU starvation (load 95
   from orphans); every phase ran 10–20× slower → 14 phases blew the 120s cron cap.
   Compounded by a config bug: `MAX_RUNTIME=300` is *dead code* under a 120s cron cap
   (cron SIGKILLs first) and `check_preempt` only runs *between* phases.
2. **goal-of-the-moment blocking the gateway** — `hermes send` has no internal
   deadline; on an overloaded gateway it blocks forever holding the single IPC
   socket, so a concurrent `hermes cron list` hangs. Not send-serializing-on-itself —
   gateway socket contention + no timeout, fired every 1 min.
3. **repo-health TIMEOUT re-fires** — the dispatcher ran the FULL 3-repo pytest suite
   (`repo-health-check.py`) as a 2s probe handler. It can never finish in 2s → always
   non-zero → never resolves → re-fires every tick, AND orphaned pytest each time.
4. **alert-resolver "no verifier for GIT_ERROR"** — `VERIFIERS` had no `GIT_ERROR`
   key. `GIT_ERROR: git status failed code -1` = git status TIMED OUT (-1) under load
   — transient, not repo corruption. With no verifier it sat as "unverifiable, kept
   open" forever and leaked the `· no verifier` line.
5. **otto-dispatch crash (Otto's regression)** — `auto_handled` initialized as `[]`
   but used as an int counter (`auto_handled += 1`) → `TypeError` that crashed the
   dispatcher (exit 1) on every self-heal. This is the "made it worse" part.

## Highest-leverage structural fix
**Probes must VERIFY state, never RE-RUN the workload — and every subprocess timeout
must kill the process GROUP.** Every script reimplements its own `run()`/`sh()` with
the same latent orphan bug. The single highest-leverage next step: extract one
shared `hermes_subprocess.run_bounded()` (start_new_session + os.killpg on timeout)
and route every script through it, so the next orphan factory can't be written.

## Fixes shipped (all tested with real runs)
- `repo-health-check.py` — `run()` → Popen+start_new_session, killpg on timeout;
  fixed `futures.TimeoutError` NameError (was `futures_TimeoutError`).
- `proving-ground.py` — `sh()` → same process-group kill (2nd orphan factory).
- `otto-dispatch.py` — `_run_handler` → process-group kill; fixed `auto_handled`
  int-vs-list crash (init + budget-log `len()`).
- `repo-health-probe.py` (NEW) — read-only verifier; reads last repo-health.jsonl,
  exits 0 iff no repo failing. Spawns nothing.
- `known_classes.py` — repo-health probe handler repointed to `repo-health-probe.py`.
- `alert-resolver.py` — added `_v_git_error` verifier (re-probes git status; transient).
- `idle-learning-run.sh` — `MAX_RUNTIME` 300→100 (below cron cap); per-phase `timeout
  --kill-after` (skips shell-function phases); env-overridable.
- `goal-of-the-moment.sh` — wrapped `hermes send` in `timeout 15`.

## Verification (load 95 → 6.5, orphan pytest 64 → 0)
- `ps aux | grep pytest | grep -v grep | wc -l` → 0
- `uptime` → load ~6 (was 95)
- `HERMES_REPO_TIMEOUT=3 python3 scripts/repo-health-check.py; ps aux|grep "uv run pytest"|grep -v grep|wc -l` → forces timeout, 0 survivors
- `python3 scripts/otto-dispatch.py` (×2) → exit 0 both, run #2 deduped, 0 pytest spawned
- `python3 scripts/alert-resolver.py --verbose` → GIT_ERROR `resolved probe_verified _v_git_error`, 0 unverifiable
- `python3 scripts/alert-resolver.py --self-test` → PASS
