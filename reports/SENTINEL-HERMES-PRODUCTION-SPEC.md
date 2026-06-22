# Production Systems Engineering Specification: The Unified Sentinel-Hermes Architecture

> **Status: DRAFT CONTRACT — verified against the host 2026-06-22 (macOS Intel, Python 3.14.6 / 3.11.15, /usr/local Homebrew).**
> The **§0 Verification Ledger is BINDING and overrides the prose below wherever they conflict.** The prose was authored as a target; the Ledger records what is actually true on disk, with the proof. Items marked `DANGER` or `DEFECT` must be resolved before that section is implemented. Nothing here is "verified" unless the Ledger says so.

---

## §0 Verification Ledger (binding — every row proven on disk 2026-06-22)

### 0.1 DANGER — do not implement as written
- **§2.1 "kanban.db is deprecated; all write-paths removed" — REJECTED.** `kanban.db` is **not** a redundant dual-store; it is the **gateway's own dispatcher queue** (`config kanban.dispatch_in_gateway=true`, dispatches every 60s). coordinator.py:13-17 states the separation is **deliberate**: *"Writing our tasks into kanban.db would let that dispatcher double-claim them. A separate DB keeps the same 'source of truth survives restart' property without fighting the gateway."* Removing kanban write-paths would break the live gateway dispatcher. **coordinator.db is already the single source for the coordinator; kanban.db belongs to a different subsystem and must stay.** (This also corrects an earlier hasty "consolidation is right" concession — proof: coordinator.py:13-17; kanban.db.tasks currently 0 ≠ unused.)
- **§1.1 "watchdog is prohibited from calling launchctl; signals self-exit only" — CONTRADICTS LIVE.** The real watchdog daemon is `estate_watchdog.py`, and it **actively calls `launchctl kickstart -k`** to restart gateway/coordinator (lines 11-12, 141-155, 209). With `KeepAlive=True` on those two daemons (proof 0.2), launchd *already* restarts them — so the live system **has the double-actuator the spec warns against**. The spec's single-actuator design is a sound *target* but is a **behavioral change + reconciliation**, not a description of reality. There was a prior incident here (estate_watchdog.py:202 references the 2026-06-21 kickstart failure). Treat as careful rework, not a one-liner.

### 0.2 DEFECT — corrected values (proof: launchd plists parsed 2026-06-22)
The §3 daemon table is wrong on 4 of 5 rows. **Real launchd configuration:**

| Label | argv0 (interpreter) | Target | KeepAlive | Schedule |
|---|---|---|---|---|
| `ai.hermes.coordinator` | `/bin/zsh` | `scripts/coordinator-daemon.sh` | **True** | persistent |
| `ai.hermes.gateway` | `~/.hermes/hermes-agent/venv/bin/python` | `scripts/gateway_preflight.py` | **True** | persistent |
| `ai.hermes.watchdog` | `/usr/local/bin/python3` | `scripts/estate_watchdog.py` | None | `StartInterval` 300s |
| `ai.hermes.progress` | `/bin/bash` | `scripts/progress-snapshot.sh` | None | `StartInterval` 3600s |
| `ai.hermes.rsi` | `/bin/bash` | `scripts/rsi-autorun.sh` | None | `StartCalendarInterval` |

- coordinator runs via a **zsh wrapper** (`coordinator-daemon.sh`), not python→coordinator.py directly.
- gateway interpreter is **`~/.hermes/hermes-agent/venv/bin/python`** — the spec's `~/.hermes/gateway/.venv/bin/python3` **does not exist** (proof: `ls` absent; `find` no match), and it runs `gateway_preflight.py`, not `gateway_core.py`.
- watchdog/progress are **interval relaunch jobs (no KeepAlive)**, not persistent supervisory daemons; watchdog is `estate_watchdog.py`, not `watchdog.py`.
- **Only `ai.hermes.rsi` matches the spec** (scheduled via `rsi-autorun.sh`). ✓

### 0.3 DEFECT — other corrected facts
- **§5 "~100 skills" → actually 25** (`ls -d ~/.hermes/skills/*/ | wc -l` = 25).
- **§5 MCP read-only gate — largely UNBUILT.** `mcp` is referenced in config.yaml but there is **no MCP server directory** (`ls ~/.hermes/*mcp*` → none). Treat the skill-exposure MCP gate as net-new work, not wiring.
- **§7 Phase 1 targets the wrong component.** The bounded-subprocess (killpg) reaper belongs where subprocesses are **spawned** (the coordinator/executor path), not in the watchdog — `estate_watchdog.py` is a daemon-kickstarter, and has **no** `start_new_session`/`killpg`/`setsid` (proof: grep). A `run_bounded` mechanism may already exist in coordinator.py (verify before porting).

### 0.4 PROVEN — these spec claims are correct (keep)
- **§2.2 revised schema compiles** — `loop_tasks` + `transactional_outbox` with table-level `FOREIGN KEY(task_id) REFERENCES loop_tasks(task_id)` run clean (`sqlite3` exit 0).
- **§3 interpreter for python daemons** `/usr/local/opt/python@3.14/bin/python3` exists (Intel; `which python3.14`=`/usr/local/bin/python3.14`).
- **§1.2 RSI is scheduled/gated via `rsi-autorun.sh`** — matches the plist (Calendar interval, no KeepAlive).
- **coordinator & gateway are persistent (`KeepAlive=True`)** — §1.2 "persistent core" is correct for those two.
- **§4.1 daily_reflection fix** — `~/Documents/code/.hermes/OBJECTIVES.md` exists (0600) inside TCC-protected `~/Documents`; logs show `Operation not permitted`; **relocate to `~/.hermes/OBJECTIVES.md` is correct**, and **dropping `codesign -s -` is correct** (TCC keys off the interpreter, already ad-hoc signed).
- **§6 held-out RSI is real** — `EXECUTE_PROMPT.jsonl`/`VERIFY_PROMPT.jsonl` are 3-train/3-test/0-shared; a teeth-test showed a train-overfit candidate REJECTED on the held-out gate, a generalizing one ACCEPTED; `evalset_hash` + independent `evidence_verify.py` present.
- **§6 dropping `/var/estate`+`chmod 700` is correct** — `/var` needs sudo (cage denies); chmod-700 did not block same-user read/ls (tested).
- **§7 Phase 2 (transactional outbox) is the right mechanism** — harness proved a raw socket loses 5/5 escalations on gateway-down while a sqlite outbox delivers 5/5 exactly-once.

### 0.5 HYPOTHESIS — still unverified (test before relying)
- **§3/§7P3 worktrees under `~/Documents/code` — TCC risk.** coordinator.py already references `~/Documents/code` as a sandbox base (line 655) and the real project repos (lines 1230-1233: prospector/signalengine/tie/haworks). Since `~/Documents` is TCC-protected (the class of the daily_reflection EPERM), confirm the launchd-spawned coordinator can actually read/write there. `[test: have the coordinator daemon `touch ~/Documents/code/.hermes_tcc_probe` and check exit]`
- **§6 honest limits (visible, not yet closed):** fitness is a keyword/brevity proxy (not live task success); coverage is 2 prompt vars / 6 cases; minor scalar leak feeding the held-out score back into regeneration (rsi-orchestrator.py:466-467).

---

## §1 System Topology & Process Supervision
The estate operates as a single-brain state machine where process lifecycles are owned exclusively by `launchd`; subsystem tracking is decoupled from process lifecycle to prevent races.

> ⚠ **Ledger 0.1/0.2:** the *target* below (launchd owns lifecycle; watchdog does semantic-death only and signals self-exit) is sound, but the LIVE watchdog (`estate_watchdog.py`) currently calls `launchctl kickstart -k` and gateway/coordinator already have `KeepAlive=True`. Implementing §1.1 means **removing watchdog's kickstart and proving KeepAlive alone is reliable** (mind the 2026-06-21 incident).

### 1.1 Process Lifecycle Management (launchd)
All core services run under user-level launchd agents; each plist enforces `KeepAlive` (verified True for coordinator+gateway; watchdog/progress use `StartInterval`, rsi uses `StartCalendarInterval`). **Target:** watchdog restricted to Semantic Death Detection (stale heartbeats, freezes); on a wedge it signals self-exit to the process group and lets launchd recycle — **it must stop calling launchctl directly (current deviation, Ledger 0.1).**

### 1.2 Subsystem Execution Profiles
- **ai.hermes.coordinator (Persistent, KeepAlive=True):** single-writer state engine; runs via `coordinator-daemon.sh`.
- **ai.hermes.gateway (Persistent, KeepAlive=True):** Python 3.11 venv at `~/.hermes/hermes-agent/venv`; runs `gateway_preflight.py`; tails the transactional outbox; bidirectional external traffic.
- **ai.hermes.rsi (Scheduled/Gated):** calendar-interval via `rsi-autorun.sh`; never an always-on loop; gated by `OFF_SWITCH`. ✓ matches live.

## §2 Database Harmonization & Live Migration Protocol
State consolidates onto `coordinator.db`. **Ledger 0.1: `kanban.db` is the gateway dispatcher's store and is NOT deprecated.**

### 2.1 File Space Allocations
- `~/.hermes/coordinator.db`: unified coordinator state machine, pipeline tracking, **transactional outbox**.
- `~/.hermes/state.db`: conversation / FTS store only (`messages`, `messages_fts`, `compression_locks`) — not skills/eval data.
- `~/.hermes/kanban.db`: **gateway dispatcher queue — RETAINED** (see Ledger 0.1).

### 2.2 Relational Production Schema (coordinator.db) — COMPILES (Ledger 0.4)
```sql
CREATE TABLE IF NOT EXISTS loop_tasks (
    task_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    current_stage TEXT NOT NULL CHECK(current_stage IN ('INTAKE','TRIAGE','DIAGNOSE','EXECUTE','VERIFY','REPORT','LEARN')),
    terminal_state TEXT CHECK(terminal_state IN ('DONE','REJECTED','ESCALATED','BLOCKED','ABANDONED','LEARNED')),
    strike_count INTEGER DEFAULT 0 CHECK(strike_count <= 3),
    execution_time_seconds REAL DEFAULT 0.0,
    token_cost_accumulated REAL DEFAULT 0.0,
    error_signature TEXT,
    last_tick_timestamp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transactional_outbox (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('DONE','REJECTED','ESCALATED','BLOCKED','ABANDONED')),
    payload_message TEXT NOT NULL,
    dispatch_status INTEGER DEFAULT 0 CHECK(dispatch_status IN (0,1)),  -- 0=Pending,1=Dispatched
    created_at INTEGER NOT NULL,
    FOREIGN KEY(task_id) REFERENCES loop_tasks(task_id)
);
```

### 2.3 Live Migration (Expand ➔ Backfill ➔ Contract)
coordinator.db.tasks is populated (55 rows). No big-bang drop. **Expand:** add new state columns as nullable. **Backfill:** map legacy rows to the new stage/terminal vocabulary in the background. **Contract:** retire old readers, then tighten CHECK constraints. (process risk, not a correctness claim.)

## §3 Core Daemon Configuration Profile
**Use the corrected table in Ledger 0.2 — the original prose table was wrong on 4 of 5 rows.**

## §4 Maintenance & Cron Fleet Realignment
22 jobs in `jobs.json` (verified count).
### 4.1 TCC File Isolation Fix (daily_reflection.py) — VERIFIED (Ledger 0.4)
Relocate `OBJECTIVES.md` to `~/.hermes/OBJECTIVES.md` (0600), out of TCC-protected `~/Documents`. **Drop** all `codesign -s -` steps.
### 4.2 Fleet Consolidation
Merge `health-watchdog`+`improvement-probe` into one 15-min loop; route `near-miss-analyzer.py` to `~/.hermes/logs/near_miss.jsonl`; cap `health-bridge` at 10 templates. Each merge keeps its own teeth-test (must still fire on the original trigger).

## §5 Write-Protected Skill Isolation
Skills registry at `~/.hermes/skills/` (**25 dirs**, Ledger 0.3) is read-only to executor sandboxes. Sandboxes may not `git add`/write into skill dirs. **§5 MCP server is unbuilt (Ledger 0.3)** — treat as net-new. TRIAGE associates tasks→skills by reading the skills dir/playbooks on disk (not state.db).

## §6 Grounded RSI Framework — ALREADY IMPLEMENTED & PROVEN (Ledger 0.4)
Disjoint train/test evalsets in `meta/rsi_evalsets/`; tuner optimizes `train`, gate+verifier require generalization on held-out `test`; `evalset_hash` tamper-check; independent `evidence_verify.py`. `/var/estate`+`chmod 700` dropped. Open work: fitness realism + coverage (Ledger 0.5).

## §7 Operational Deployment Sequence & Test Protocols
No change is active until a sabotage test turns the suite RED under failure.
- **Phase 1 (subprocess reaper):** **target the coordinator/executor spawn path, NOT watchdog (Ledger 0.3)**; a `run_bounded` may already exist — verify first. Sabotage: spawn `sleep 600` with a 1s bound → RED if it escapes the group/1s, GREEN when the process-group leader is killed and children reaped.
- **Phase 2 (transactional outbox):** VERIFIED mechanism (Ledger 0.4). Coordinator writes events to `transactional_outbox`; gateway tails+dispatches. Sabotage: stop the gateway, force an `ESCALATED` state change → the row must persist on disk and dispatch on gateway recovery (never a volatile raw socket).
- **Phase 3 (sandbox isolation + strike matrix):** worktrees under `~/Documents/code` — **verify TCC access first (Ledger 0.5)**. Strikes 1-2 soft-reset; strike 3 drops the worktree, writes a split into **coordinator.db** (not kanban), and enqueues an urgent outbox event. Sabotage: inject a filesystem fault → soft-reset twice, hard-clean on the third, split parent into two records, log a critical event.
