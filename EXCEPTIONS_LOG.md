# Hermes — Exceptions Register

Every exception found while making the estate actually functional. Each entry carries the
receipt that proved it, not an assertion. Newest section first.

---

## 2026-08-13 — CRON_SILENT_STRETCH: the 9am digest was skipped by a 46h host sleep

`otto-daily-digest` had `last_run_at` frozen at `2026-08-11T09:01:07+01:00` and missed two
consecutive 09:00 schedules. Neither the job nor delivery was at fault.

### Trigger — the host slept across the window, keepawake did not stop it
```
$ pmset -g log | rg 'Entering Sleep state|Wake from' | rg '2026-08-1[123]'
2026-08-11 09:06:04 +0100 Sleep  Entering Sleep state due to 'Low Power Sleep':TCPKeepAlive=inactive Using Batt (Charge:0%) 165936 secs
2026-08-13 07:11:40 +0100 Wake   Wake from Standby [CDNVA] : due to EC.ACAttach/Notification Using AC (Charge:0%)
```
165,936s ≈ 46.1h asleep, straight over both 09:00 windows. `ai.hermes.keepawake` was loaded and
its process alive the whole time — `ps -eo pid,ppid,command` shows `1713 1 /usr/bin/caffeinate
-dims`. **`caffeinate -dims` does not hold off Low Power / clamshell sleep at 0% battery**, so
this gap class will recur and keepawake is not the fence that prevents it.

### Mechanism — the drop was correct code doing the wrong thing for this job
On wake the scheduler found the run ~165,700s late. Grace for `0 9 * * *` is
`min(period/2, 7200)` = 7200s (`hermes-agent/cron/jobs.py:_compute_grace_seconds`), and the job
carried no `catch_up`, so it took the fast-forward path: `next_run_at` jumped to 2026-08-13T09:00
and `missed_runs` became 1, without running. Census over `cron/jobs.json` at the time: every job
with `catch_up=true` had `last_run_at` at 2026-08-13T07:11–07:20 (caught up on wake); every job
without it was frozen at 08-10/08-11.

### Fix — bounded catch-up, not unbounded catch-up
Unbounded `catch_up: true` is the wrong fix on its own: a "yesterday's stats" briefing delivered
46h late is misinformation, which is exactly why `jobs.py` made catch-up opt-in. Added
`catch_up_window_s` (`hermes-agent/cron/jobs.py:1187-1202`): run the job late while it is still
useful, drop and record it beyond the window. Jobs with `catch_up` and no window are unchanged.

Receipts:
- `~/.hermes/hermes-agent/venv/bin/python -m pytest ~/.hermes/scripts/test_reliability_alarm.py -q`
  → `35 passed`, including three new cases: 46h-late + 6h window is NOT due and increments
  `missed_runs`; 3h-late + 6h window IS due; 46h-late with no window is still due (back-compat).
- Teeth check against an unpatched copy of the module, same 46h-late input:
  `OLD (pre-patch): due=['digest-under-test'] missed_runs=0` /
  `NEW (patched): due=[] missed_runs=1`.
- `otto-daily-digest` now carries `catch_up: true` and a bounded window, and ran at
  `2026-08-13T07:35:25+01:00` (`last_status: ok`, `last_error: null`), clearing the stretch.

**The bounded window, not keepawake, is what keeps this job honest across the next sleep.**

---

## 2026-08-06 — "Layer 0 is live but nothing executes"

Layer 0 (anti-fabrication) was shipped earlier today and immediately made the estate honest:
tasks stopped reporting work they had not done. What it exposed is that **the executor behind
that door had been unreachable since 2026-08-04**. Five separate defects, all proven:

### E1 — The installed LaunchAgent plist had drifted from the repo copy (ROOT CAUSE)
`~/Library/LaunchAgents/ai.hermes.coordinator.plist` (mtime **2026-08-04 17:49**) was a
hand-written 894-byte file. The intended one, `~/.hermes/ai.hermes.coordinator.plist`, is
2290 bytes. The installed copy invoked `/usr/local/bin/python3 coordinator.py` **directly**,
bypassing `scripts/coordinator-daemon.sh`, and dropped every `COORD_*` variable.

Lost by the drift:
- `COORD_AGENTIC_EXEC=1` — **the gate at `coordinator.py:1302`**. Without it `execute()`
  never calls `agentic_execute()` at all; it returns a pure-LLM narrative. The tool-capable
  executor was switched off entirely, not by decision but by a config regression.
- `COORD_EXEC_DIRS`, `COORD_MAX_INGEST`, `COORD_MAX_INFLIGHT`, `COORD_EXEC_TIMEOUT`
- log destination (`/tmp/coordinator.log` instead of `~/.hermes/logs/coordinator.log`, which
  is why `logs/coordinator.error.log` had been frozen at 31 Jul 18:48)

Receipt: `diff -u` of the two plists; `ps eww <pid>` on the running daemon showed only
`HERMES_CRON_TIMEOUT` and `PATH=/usr/bin:/bin:/usr/sbin:/sbin`.

### E2 — launchd's bare PATH cannot see `claude` or `agy`
Both CLIs live in `~/.local/bin`, which is absent from launchd's default PATH. This is exactly
what `coordinator-daemon.sh:5` exists to fix — and E1 bypassed that wrapper.

Receipt (decisive, not inferred):
```
env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": ...}
subprocess.run(["claude","--version"], env=env)
  → FileNotFoundError: [Errno 2] No such file or directory: 'claude'
  → same for 'agy'
```
8 rows in `coordinator.db` already recorded `No such file or directory`.

### E3 — The 30s circuit-breaker timeout was the fabrication factory
`CIRCUIT_BREAKER_TIMEOUT_S=30` capped the **real** executor call, not just a liveness check.
MEASURED: the most trivial possible tool turn (one Bash + one Read, `rc=0`) took **27s**. Any
genuine remediation therefore timed out and fell through to the narrative tier — i.e. the cap
manufactured precisely the fabricated-progress narration Layer 0 now rejects. Closing the
fabrication door without fixing this converts fake successes into honest failures and nothing
more.

Fix: liveness and work no longer share one budget. A `claude --version` probe (MEASURED <1s)
decides whether the endpoint is dead; only a CLI proven live is then given `EXEC_TIMEOUT_S`
(600s). The original intent — a dead endpoint must never freeze the daemon for 10 minutes —
is preserved exactly.

### E4 — 8 deny rules in the executor cage were silently NOT APPLIED
`claude` rejects `Write(<path>)` permission rules: *"Write(**/.env) is not matched by file
permission checks — only Edit(path) rules are."* All 8 `Write(**/…)` entries in
`executor-settings.json` were therefore inert — the cage had 8 holes covering `.env`, `.ssh`,
`LaunchAgents`, `.claude/hooks`, and the cage file itself.

Verified before removing: **every** dropped `Write(...)` rule already had an `Edit(...)` twin
(asserted in the fix script, which refuses to run otherwise), and Edit rules cover all
file-editing tools. Net effect on blast radius: **none**. 66 → 58 rules, same coverage.

### E5 — The stored failure evidence named the wrong cause
`claude_err` truncates stderr to 150 chars, and the E4 warnings are printed **first**. So every
failed task in `coordinator.db` recorded
`Permission deny rule (executor-settings.json): Write(**/.env) is not matched by...`
as its cause — a benign warning — while the operative error (quota wall, dead endpoint) was cut
off unread. A diagnosis that reports the first line rather than the operative one is worse than
none: it sends the operator to fix the wrong file. Fixed by `_meaningful_stderr()`, which drops
warning lines before truncation.

### E6 — A timeout was being reported as "no real work performed" (FIXED)
Two repo-inspection tasks were killed by the 600s wall clock **after** doing the work and
**before** narrating it. Proven: `~/.hermes/reports/project-next-ritualworks.md` (8450 bytes,
mtime 19:47) and `project-next-portfolio-site.md` (5507 bytes, mtime 19:50) — both fresh,
both substantive, one containing a real `npx vitest run` result (8 of 11 test files failing).
Tier 2 then stamped `[executor-narrative-fallback` on them, which `verify()`'s hard gate reads
as "the executor could not act". Real work must never be labelled a chat fallback.

`run_bounded` already carries partial stdout on `TimeoutExpired`; it was discarded. Now
salvaged under `[executor-timeout-partial`, deliberately NOT a member of `FALLBACK_MARKERS`
so ground truth still decides. The worktree is still discarded — a process killed mid-edit
must not merge half-written state into a live repo; only the EVIDENCE is salvaged.
`COORD_EXEC_TIMEOUT` raised 600 → 900 on the same measurement.

### E7 — `pgrep -f 'coordinator.py'` matches your own monitoring shell
It reported pid 23712 (a diagnostic shell) as the daemon. The authoritative source is
`launchctl print gui/$(id -u)/ai.hermes.coordinator | awk '/^\tpid = /{print $3}'` → 25445.
A probe that matches on a command-line substring will match the probe.

### Standing exceptions NOT yet fixed (carried forward)
- **`agy` is quota-dead** — *"Individual quota reached. Resets in 67h23m21s"* (2026-08-06).
  Tier already removed from the chain by design; nothing to do until it resets.
- **`agy` is also a shell alias** (`agy --dangerously-skip-permissions`), so any `subprocess`
  call gets the bare binary without that flag. Latent trap if the tier is ever restored.
- **`memory_retrieval` embedding layer is down** — `No module named 'numpy'` / `'onnxruntime'`
  under `/usr/local/bin/python3`. Degrades to tag-only retrieval. Non-fatal, silenced after 10
  lines, but it means learned-policy recall is keyword-only.
- **`verify_estate.sh` does not check the executor gate.** `grep` for `COORD_`/`AGENTIC` in it
  returns nothing — which is why a 2-day-old total executor outage never tripped a probe. The
  probe asserts presence, not capability. This is the Layer 4 work item.
- **Layer 1 pre-registration is still unbuilt** — run the acceptance test AT TASK CREATION and
  reject on exit 0 as vacuous.
