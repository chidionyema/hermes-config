# Checkpoint — Sentinel-Hermes LAUNCHED (TCC cleared) (2026-06-22 15:03)

## >>> STATUS UPDATE — TCC BLOCKER IS GONE (proven 2026-06-22 15:01) <<<
The previous "only blocker" (macOS Full Disk Access for the launchd daemon) is RESOLVED.
PROVEN this session by running the staged probe in launchd context:
  ~/.hermes/logs/tcc-probe.out → "EXIT: 0   CREATED: True"
i.e. the daemon CAN now `git worktree add` into ~/Documents/code/prospector. The FDA grant
on .../python@3.14/.../Python.app is in effect (or path was granted).

Post-grant runbook executed unattended this session:
  1. staged probe → EXIT:0 CREATED:True ✅
  2. probe worktree cleaned (git worktree remove) ✅
  3. coordinator restarted: `launchctl kickstart -k gui/$UID/ai.hermes.coordinator` →
     pid 3728, coordinator.error.log = 0 bytes (clean import), coordinator.db-wal writing
     post-restart (alive/ticking) ✅
  4. probe plist booted out + removed (~/Library/LaunchAgents/ai.hermes.tcc-probe.plist) ✅
=> SUBSTRATE LAUNCHED. What is NOT yet proven: a real "hermes-estate" code commit landing,
   because the seed objectives are READ-ONLY reports (see "REAL AUTONOMY GAP" below).

## REAL AUTONOMY GAP — the actual remaining work (founder decision)
Substrate is live but the agent still makes no CODE changes, by design:
  - projects.json: all 4 objectives are "read-only status report... make NO code changes".
  - config.yaml: project task throttle min_interval_hours: 24 (once/day).
  - risk classes: signalengine=money, tie=identity, prospector/haworks=low.
To get advanced>0 with real commits, founder must decide: (a) give writable objectives,
(b) lower the 24h throttle, (c) which repos may be edited autonomously (money/identity fence).
This is a founder call, NOT yet made.

## Task / goal
Implement the Sentinel-Hermes production spec into the live ~/.hermes estate and SHIP it
(founder: "stop the phases crap, get it done and ship"). Earned-trust proof discipline.

## DONE + PROVEN + LIVE this session
All on the running daemon (launchd ai.hermes.coordinator), every claim test-backed.
Interpreter: /usr/local/bin/python3. Full suite = 15 tests green (3+3+2+2+5).

### Phase 1 — reaper (LIVE)
- `run_bounded()` (coordinator.py:678) puts the executor in its own process group
  (start_new_session) and SIGKILLs the whole group on timeout. Wired at all 3 spawn sites
  (claude ~786, agy ~812, acceptance /bin/zsh ~803). Proof: test_reaper.py (2).

### Phase 2 — escalation outbox (LIVE)
- `escalate()` persists the founder message to `transactional_outbox` BEFORE the volatile
  Telegram send; `drain_outbox()` runs every tick (coordinator.py:1168) and redelivers
  pending escalations after a gateway/Telegram outage. Proof: test_outbox.py (3,
  atomicity+durability+teeth), test_escalation_outbox.py (3, live escalate path).

### Phase 3 — worktree isolation + MERGE-BACK (LIVE, the new work this session)
- sandbox.py: added `commit_all()`, `worktree_head()`, `merge_back()` (ff-only). Also fixed a
  late-binding-default bug: `make_worktree`/`remove_worktree` now resolve `base or WORKTREE_BASE`
  at CALL time so WORKTREE_BASE is overridable (test had caught a trivial false-pass).
- coordinator.py: `_task_repo(task)` resolves the single repo for PROJECT tasks only
  (source 'project:<key>' → load_projects()[key].repo); plumbing/failure tasks → None → direct.
- `agentic_execute()` REWRITTEN: project tasks run the executor with cwd=worktree under
  ~/.hermes/worktrees; on success it commits ALL worktree work (captures base SHA so the
  executor's OWN commits merge too, not just leftover edits) and ff-only merges back onto the
  live repo BEFORE verify() runs. GUARDED both ways:
    * make_worktree raises (TCC EPERM / not-a-repo) ⇒ fall back to DIRECT execution (today's
      proven path). Prints `[sandbox] worktree unavailable ... running direct` to coordinator.log.
    * merge-back refused (live branch moved) ⇒ worktree PRESERVED + RuntimeError (work never
      shredded). Crash path ⇒ worktree discarded, live repo HEAD untouched.
- Proof: test_cutover.py (5) on a real temp git repo: merge-back round-trip; ff-only REFUSES
  on moved branch (no clobber); success lands on LIVE repo + worktree cleaned; crash leaves
  live HEAD untouched + worktree gone; read-only task = no merge.

### Ship verification
- DB backed up: backups/coordinator.db.{prereload,phase3}-*.bak (schema unchanged).
- `launchctl kickstart -k` reloaded twice; final pid 19556, state=running, heartbeat
  `last_tick|19556|advanced=0 reaped=0`, coordinator.error.log = 0 bytes (clean import, no crash).

## TCC — ROOT CAUSE PROVEN (2026-06-22), blocked on ONE founder action
Launchd-context probes (label ai.hermes.tcc-probe, headless = no terminal FDA) proved:
- `git -C ~/Documents/code/prospector worktree add` → getcwd EPERM (EXIT 128); from an
  FDA terminal the same cmd → EXIT 0. So it's the TCC context, not the repo.
- `--git-dir` (cwd stays in ~/.hermes, no chdir into Documents) → "not a git repository":
  daemon can't even READ ~/Documents/code. In-code escape (`-C`, `--git-dir`) EXHAUSTED.
- sign-interpreters.sh run; /usr/local/bin/python3 already adhoc-signed → STILL denied.
  Signing ≠ grant. ⇒ a Full Disk Access GRANT is provably required (tccutil can't add it).
CONSEQUENCE: today the cutover guard falls back to DIRECT exec (no regression) AND the
executor (claude, cwd=~/Documents/code, coordinator.py:721) almost certainly hits the same
denial → the real cause of advanced=0 (project work silently degrades to chat).

FOUNDER ACTION (only thing left): System Settings ▸ Privacy & Security ▸ Full Disk Access ▸
  + ▸ ⌘⇧G ▸ paste:
  /usr/local/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/Resources/Python.app
  ▸ toggle ON. (/usr/local/bin/python3 → 3.14.6; git+claude inherit the grant as its children.)

POST-GRANT (Claude runs unattended, no asking): kickstart staged probe
  (~/Library/LaunchAgents/ai.hermes.tcc-probe.plist, now python→git) → expect EXIT:0 CREATED:True
  → `launchctl kickstart -k gui/$UID/ai.hermes.coordinator` → trigger one prospector task →
  prove `advanced` increments + a hermes-estate commit lands → remove probe plist.
Permanent alt if grant fragility recurs on brew upgrades: move repos ~/Documents/code → ~/code
  (non-TCC) + update projects.json — founder's call, not done.

## (old) TCC question — superseded by the PROVEN block above
make_worktree writes to ~/Documents/code/<repo>/.git/worktrees/ — whether the launchd daemon
can do that under macOS TCC is still unproven IN THE DAEMON CONTEXT (my Bash probe runs under a
different responsible process, so it isn't representative). It no longer BLOCKS anything: the
guard degrades to direct execution on EPERM. To OBSERVE which path it took, on the first real
project task run: `grep "\[sandbox\]" ~/.hermes/logs/coordinator.log` — a hit = it fell back
(TCC blocked); no hit + a new commit on the project repo authored "hermes-estate" = isolation
engaged. If it falls back and isolation is wanted, run scripts/sign-interpreters.sh (memory
project_macos_tcc_python) and re-observe.

## NOT done (separate problems, NOT this spec)
- advanced=0 / autonomy: project tasks are throttled (PROJECT_MIN_INTERVAL_S=6h) and the seed
  objectives are read-only reports. The cutover changes the SUBSTRATE, it does not by itself
  raise autonomy. Did NOT force a task run (side effects > proof value; guard makes it safe).
- decide_action/soft_reset strike-reuse: built+tested in sandbox.py but the cutover currently
  removes-on-fail (always-fresh worktree) — simpler and correct, slightly less efficient.

## Spec/host corrections still binding (do NOT implement as written)
- live DB has `tasks` table (not loop_tasks); kanban.db is the gateway dispatcher store (live).
- daemon: /bin/zsh coordinator-daemon.sh daemon (plist); COORD_EXEC_DIRS=~/Documents/code:~/.hermes:~/.claude.
- Canonical spec: ~/.hermes/reports/SENTINEL-HERMES-PRODUCTION-SPEC.md (Ledger binding).
