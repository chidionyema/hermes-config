# Sentinel-Hermes Integration — CORRECTED Spec (proof-tagged)
_2026-06-22. Every line is [PROVEN] / [CONCEDED] / [DEFECT→fix] / [HYPOTHESIS: test=…] / [process risk]._
_Tags reference proofs run this session against this host (~/.hermes, /usr/local Intel, Python 3.14.6 + 3.11)._

## Legend
- **[PROVEN: …]** verified on disk or by a runnable test this session.
- **[CONCEDED]** Gemini's blueprint is correct, and I proved it.
- **[DEFECT→fix]** as-written it breaks on this host; the fix is given.
- **[HYPOTHESIS: test=…]** not yet verified — do NOT act until the named test passes.
- **[process risk]** transition/operational risk; not a correctness claim.

---

## §1 Topology — single brain, daemons under launchd
- **[CONCEDED]** Consolidating task-state onto one store is right in direction.
  Proof: `coordinator.db.tasks=55`, `kanban.db.tasks=0` — coordinator.db is already the de-facto
  single source; kanban holds no live task rows.
- **[DEFECT→fix]** Diagram puts `ai.hermes.watchdog` as the *parent supervisor* of gateway/coord/rsi.
  launchd already owns process lifecycle (KeepAlive). Two restart authorities = restart races.
  Fix: **single actuator** — launchd restarts on PID death; watchdog only *detects semantic death*
  (stale heartbeat / wedged) and signals the process to self-exit so launchd restarts it, or pings
  the founder. Watchdog never calls launchctl.
  - **[HYPOTHESIS: test=`cat ~/Library/LaunchAgents/ai.hermes.*.plist | grep -A1 KeepAlive`]** that
    KeepAlive is set on each daemon. Not verified this session.
- **[DEFECT→fix]** `ai.hermes.rsi` shown as a persistent "Flywheel Core" daemon. RSI is a *fenced,
  staged, scheduled* job (stages candidates, never auto-merges), not an always-on loop.
  Proof: wrapper `rsi-autorun.sh` exists alongside the script (not a long-running daemon entry).
  - **[HYPOTHESIS: test=`cat ~/Library/LaunchAgents/ai.hermes.rsi.plist`]** confirms StartCalendarInterval
    (scheduled), OFF_SWITCH gating, and that it invokes `rsi-autorun.sh`. Keep scheduled, do NOT
    promote to a persistent daemon.

## §2 Database harmonization
- **[DEFECT→fix]** SQL does not compile. `task_id TEXT FOREIGN KEY REFERENCES loop_tasks(task_id)`
  → `Error: near "FOREIGN": syntax error` (sqlite3 exit 1). Fix: inline `task_id TEXT REFERENCES
  loop_tasks(task_id)` (exit 0) or a table-level `FOREIGN KEY(task_id) REFERENCES …`.
  Proof: ran both forms in `sqlite3 :memory:`.
- **[DEFECT→fix]** Paths `~/.hermes/data/coordinator.db` / `~/.hermes/data/state.db` are wrong —
  there is no `data/` subdir. Actual: `~/.hermes/coordinator.db`, `~/.hermes/kanban.db`,
  `~/.hermes/state.db`. Proof: `find ~/.hermes -maxdepth 2 -name '*.db'`.
- **[DEFECT→fix]** `state.db` is described as holding skills / error-classes / perf arrays. Actual
  tables: `messages`, `messages_fts`, `compression_locks` — it is a conversation/FTS store. Proof:
  `.tables` on state.db. Do not target state.db for skill/eval data.
- **[PROVEN]** A `loop_tasks`-style schema with CHECK constraints + strike cap compiles fine
  (ran it; exit 0). The *replacement* schema itself is valid SQL once the FK line is fixed.
- **[process risk]** coordinator.db already has a populated `tasks` table (55 rows) with its own
  columns (`status, spec, risk_class, consecutive_failures, …`, proof: `.schema tasks`). Adopting
  Gemini's `current_stage`/`terminal_state` schema is a **live migration**, not a fresh create. Do
  it expand→backfill→contract (add columns, dual-write, cut reads, drop old), never a big-bang
  rewrite. This is a risk note, not a claim that either schema is "better".
- **[HYPOTHESIS: test=`grep -rn "kanban.db\|kanban_db" ~/.hermes/scripts ~/.hermes/gateway`]** that no
  live code path still *writes* kanban.db. Only deprecate kanban once this returns no active writers.

## §3 Daemon supervision table
- **[CONCEDED]** Interpreter path `/usr/local/opt/python@3.14/bin/python3` is correct for this host.
  Proof: it exists; `uname -m=x86_64` (Intel Homebrew lives under /usr/local, not /opt/homebrew).
- **[DEFECT→fix]** Script target `~/.hermes/scripts/rsi_orchestrator.py` (underscore) does not exist;
  the real file is `rsi-orchestrator.py` (hyphen). A launchd ProgramArguments to the underscore path
  fails "no such file". Proof: `ls ~/.hermes/scripts/ | grep rsi`. (And RSI likely launches via
  `rsi-autorun.sh` — see §1.)
- **[HYPOTHESIS: test=`ls ~/.hermes/gateway/.venv/bin/python3`]** that the gateway venv interpreter
  path is exactly as written. Not verified this session.

## §4 Cron fleet realignment
- **[DEFECT→fix]** Count: spec says "23 legacy items"; actual `jobs.json` has **22**. Proof: parsed
  jobs.json. Minor, but a hard contract should state the real number.
- **daily_reflection.py — [CONCEDED on the fix, DEFECT on the codesign step]:**
  - **[CONCEDED]** The error class is EPERM, not a missing file, and relocating off `~/Documents`
    fixes it. Proof: `~/Documents/code/.hermes/OBJECTIVES.md` **exists** (mode `0600`) inside the
    macOS TCC-protected `~/Documents`; estate logs show `Operation not permitted`. Relocating to
    `~/.hermes/OBJECTIVES.md` (not TCC-gated) is the right fix. (This also retracts my own earlier
    "the path doesn't exist" claim — it was false.)
  - **[DEFECT→drop]** "sign the `.py` via `codesign -s -` to bypass TCC" does nothing. TCC keys
    access off the *interpreter binary*, which is already ad-hoc signed. Proof: `codesign -dv`
    on python3.14 → `Signature=adhoc`. Drop the codesign step; the relocate alone suffices.
  - **[HYPOTHESIS: test=`grep -A20 daily_reflection ~/.hermes/logs/maintenance/2026-06-22.md`]** that
    daily_reflection's *own* traceback is the OBJECTIVES read (I matched the error class in gateway
    logs, not the script's stack). Confirm before declaring fixed.
- **proving-ground.py — [HYPOTHESIS: test=read the file + run it once]** the import-path defect is
  real and the fix is env-wrapper routing. Not verified this session; do not write the fix blind.
- **[process risk]** Merging cron jobs into watchdog.py / consolidating logs to `.jsonl` is fine in
  principle; each merge must keep its own teeth-test (the merged block must still fire on the
  trigger the standalone job fired on).

## §5 Skill library routing (read-only MCP gate)
- **[HYPOTHESIS: test=`ls -d ~/.hermes/skills/*/ | wc -l`]** the "~100 skills" count. Not verified.
- **[DEFECT→fix]** "skill matrix array stored inside state.db" — state.db is a messages/FTS store
  (§2 proof), so this premise is unsupported. The skill→task association must read from the skills
  dir / a real registry, not state.db.
- **[CONCEDED in intent]** Treating skills as a read-only registry to the executor sandbox is sound.
- **[HYPOTHESIS: test=is there an MCP server wired today?]** The "managed MCP server" is described as
  if it exists. I have not verified any MCP gate is live. Treat as net-new work, not a wiring task,
  until proven.

## §6 Grounded RSI / held-out flywheel
- **[PROVEN — already exists and works; §6 is redundant]:** rsi-orchestrator.py implements a real
  train/test split with an anti-tautology gate. Proofs this session:
  - Partitions are disjoint: `EXECUTE_PROMPT.jsonl` & `VERIFY_PROMPT.jsonl` are each **3 train / 3
    test / 0 shared** (no `None`-tagged leak cases); test carries keywords absent from train
    (EXECUTE: `concrete/factual/report`).
  - Teeth-test (mirror of `score_prompt`): a train-overfit candidate is **REJECTED** on the held-out
    gate (EXECUTE: train 67.6→87.52 PASS, held-out test 57.14→57.05 FAIL); a generalizing candidate
    is **ACCEPTED**. Same for VERIFY_PROMPT.
  - Integrity controls present: `evalset_hash` detects a post-hoc test-set swap (line 111);
    `evidence_verify.py` re-scores independently (line 102 comment + its own `_rsi_score`).
- **[DEFECT→drop]** `/var/estate/sentinel-held-out/` + `chmod 700`. `/var` is not writable without
  sudo (executor cage denies sudo), and `chmod 700` does NOT isolate the grader — a same-user
  process read the file and listed the dir under 0700. Proof: `ls -ld /var/estate`=absent,
  `[ -w /var ]`=false; chmod-700 read/ls test both succeeded. The existing mechanism
  (`meta/rsi_evalsets/` + hash + independent verifier) already provides the integrity `/var/estate`
  was meant to. Drop §6's storage design.
- **[PROVEN — the real open work §6 does NOT address]:**
  1. Fitness is a keyword/brevity **heuristic proxy**, not live task success (`score_prompt` lines
     144-158). Generalizing on the ruler ≠ better real-world outcomes.
  2. Coverage is **2 prompt vars / 6 cases each** (`ls meta/rsi_evalsets/`).
  3. Minor scalar leak: the held-out test score is fed into regeneration feedback across up to 3
     attempts (lines 466-467).

## §7 Phase execution & sabotage tests
- **[CONCEDED]** The teeth/sabotage-per-phase discipline (introduce a bug, confirm RED before
  declaring active) is correct and should govern every delta. Kept.
- **Phase 0 (socket IPC) — [DEFECT→fix]:** a raw `/tmp/hermes-gateway.sock` loses escalations when
  the gateway is down (the R4 failure that paused otto-dispatch). Proof: harness — socket delivered
  0/5, replayed 0/5, lost 5/5 on consumer-down; a coordinator.db **outbox** delivered 5/5 after
  restart, exactly-once. Fix: escalation delivery = transactional outbox table the gateway tails;
  socket optional as a low-latency nudge only.
  - **[PROVEN]** otto-inbound already bridges Telegram→coordinator (plugin dir exists), so the socket
    is a *second* transport, not the only option.
- **Phase 1 (process reaping) — [HYPOTHESIS: test=does watchdog.py already wrap spawns in killpg?]**
  The sentinel `fiscal_sentry` killpg reaper is proven in sentinel-loop; whether watchdog.py already
  has equivalent bounded-subprocess logic is unverified. Reuse the proven pattern; don't duplicate.
- **Phase 2 (escalated→push) — [PROVEN need, see Phase 0 fix]:** wire on the outbox, not a bypass
  socket. This is the highest founder-visible payoff (R4 — "estate never speaks first").
- **Phase 3 (bounded recovery / worktree, strike soft/soft/hard) — [PROVEN pattern exists]:** matches
  sentinel `state_machine_engine.execute_rollback`. **[DEFECT→fix]** spec says "write split-task into
  kanban.db" while §2 deprecates kanban — pick coordinator.db.
- **Phase 4 (RSI arm) — [PROVEN gate works]:** arm only after the leakage/overfit teeth-test passes
  on this host (it did, above). Keep it scheduled+OFF_SWITCH-gated, not a persistent daemon (§1).

---

## Bottom line (proven only)
- **Redundant:** §6 — the held-out flywheel already exists and works; drop its `/var/estate`+`chmod 700` design.
- **Fix the mechanism, keep the intent:** §0/§2 socket → coordinator.db outbox (R4).
- **7 as-written defects** that break on this host: §2 SQL FK, §2 `data/` path, §2 state.db role,
  §3 `rsi_orchestrator.py` filename, §4 codesign step, §6 `/var/estate`+chmod700, §7 Phase3 kanban.
- **3 concessions to Gemini (proven):** single-source direction, §3 interpreter path, §4
  daily_reflection EPERM+relocate.
- **Open work the blueprint misses:** RSI fitness realism (proxy→outcome) and coverage (2 prompts).
- **Highest-payoff first delta:** the escalation outbox (Phase 2 on a coordinator.db table).
