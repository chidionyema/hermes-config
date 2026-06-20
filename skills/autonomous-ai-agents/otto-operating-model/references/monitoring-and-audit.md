# Monitoring & Audit Architecture

## Health Watchdog

`watchdog.py` runs every 15min via cron `abf69d5df846` (no-agent). Checks:

- **Cron health:** every job's `last_run_at`, `last_status`, `last_error`. Stale = not run in 26h+.
- **Git health:** uncommitted file count from `git status --porcelain` in `~/.hermes`.
- **Gateway health:** process check (`ps aux | grep hermes_cli.main gateway`) + log file mtime.
- **Disk usage:** `df -h /` > 90%.
- **Policy firings:** any policy with 0 hits after 1+ day since creation.
- **Idle-learning errors:** consecutive failures in the improvement pipeline.

All alerts written to `~/.hermes/logs/alerts/watchdog.jsonl`. Each entry: `timestamp`, `alert_count`, `alerts[]`, `healthy`.

**Known alert patterns:**

| Alert type | Meaning | Fix |
|---|---|---|
| `CRON_ERROR: <name> errored: Broken pipe` | No-agent script produced output it shouldn't have | Strip stdout for below-threshold cases |
| `CRON_ERROR: <name> errored: Script exited with code 1` | A sub-phase returned non-zero | Wrap with `|| true` or use `set -eo pipefail` |
| `GATEWAY_IDLE: log not updated in N minutes` | Gateway process running but not processing messages | Normal if the user hasn't messaged — 30min threshold is generous |
| `POLICY_NEVER_FIRED: pol-* has 0 hits after N days` | Policy was created but retrieval layer never selects it | Check scope domain matches corpus domain taxonomy |
| `GIT_DIRTY: N uncommitted files` | Accumulated work not pushed | Check `hermes-config-auto-push` cron (every hour) has been running |
| `CRON_ERROR: idle-continuous-learning errored: Script timed out after 120s` (2026-06-20) | 120s scheduler kill on a designed-preempt pipeline. Run log marks reason=preempted. | Watchdog classifier must check the run log; if reason=preempted, suppress alert. 319× historical false positive on 2026-06-20. |
| `GIT_DIRTY: 295 uncommitted files` from `~/.hermes` (2026-06-20) | Steady-state: untracked `queue/`, `meta/`, `scripts/__pycache__/`. Not actual uncommitted work. | Expand `~/.hermes/.gitignore` to exclude these, or accept as steady-state. Skip in audit. |
| `CRON_ERROR: health-watchdog errored: Script exited with code 1` (2026-06-20) | By-design: watchdog exits 1 when alerts exist. Cron mis-classifies as failure and re-fires the watchdog. | Watchdog should exit 1 only on internal failure (probe timeout, can't write log). Exit 0 when alerts are merely logged. |

**Strategist audit integration:** The daily audit at 8am reads `watchdog.jsonl` and surfaces active alerts. Alerts more than 24h old are shown at reduced priority — repeat alerts across days indicate a structural issue.

**Watchdog contract — the 6-property probe spec (cross-reference `references/probe-contract.md`):**
A probe must be (1) silent when healthy, (2) deterministic, (3) bounded, (4) idempotent, (5) attributable, (6) classify exit codes correctly. The 2026-06-20 audit found that the watchdog's CRON_ERROR classifier violates (6) — it treats `Script timed out` and `exit 1 from internal logic` the same, producing false positives that drown real signal.

## Audit Trail

`audit-trail.py` records every structured decision to `~/.hermes/logs/audit/decision-trail.jsonl`. Append-only JSONL.

**When entries are created:**
1. **Every task completion** — via `mark_task_complete()` in `task_state.py`, which calls `audit-trail.py task_complete "<desc>" "auto-logged"` as a subprocess.
2. **Manual logging** — after structural changes (new cron job, policy addition, config change), call `uv run python3 ~/.hermes/scripts/audit-trail.py <type> <desc> <rationale>`.

**Entry schema:**
```json
{
  "timestamp": "2026-06-18T13:10:09Z",
  "decision_type": "task_complete",
  "description": "Built monitoring layer: watchdog + audit trail + fixes",
  "rationale": "4 active alerts found, fixed broken pipe...",
  "outcome": "pending",
  "state_snapshot": { "policy_count": 11, "active_count": 11 },
  "source": "auto"
}
```

**Replay:** `uv run python3 ~/.hermes/scripts/audit-trail.py --replay [N]` shows last N entries.

## Strategist Audit (8am daily)

Cron `85385abb646d` runs a Claude agent that reads all state files including watchdog alerts and trend analysis. See "Daily strategist audit" in the main SKILL.md.

**Sources read:**
- `logs/reflection/YYYY-MM-DD.md` — yesterday's self-reflection
- `logs/self-regression-corpus.json` — failure corpus
- `logs/regression-report.md` — coverage %
- `logs/maintenance/` — latest gap-finding and near-miss reports
- `logs/alerts/watchdog.jsonl` — active alerts
- `logs/trends/trend-*.json` — cross-session trends
- `policies/` — all policies
- `cron/jobs.json` — cron job status
- `meta/change-outcomes.jsonl` — outcome velocity

**Audit protocol — discovered 2026-06-20 (full version in main SKILL.md):**

1. **Read the source, not just the symptoms.** When something looks broken, open the actual script and confirm. The 2026-06-20 audit found `reflect-on-correction.py` has hardcoded "Root cause" + "Fix applied" strings by reading lines 67–77 — surface symptoms (39 identical entries) alone would have been ambiguous between "bug in script" and "bug in trigger logic."

2. **Distinguish "is running" from "is working."** The idle-learning pipeline reported 49 runs / 47 Complete / 0 failed in the run log, while watchdog.jsonl had 319 `IDLE_ERROR` alerts. Both were true simultaneously. Always check BOTH the run log and the watchdog alerts.

3. **Distinguish "policy exists" from "policy is preventing."** 6 of 10 policies had 0 hits after 2 days. Before recommending "promote or archive," check `policy-firings.jsonl` and the F1 retrieval injection log. Three failure modes are possible: (a) trigger string too narrow, (b) F1 retrieval not returning it, (c) recording path broken.

4. **The 3% regression coverage number is misleading.** As of 2026-06-20, 183/202 corpus entries were auto-generated "Would policy now prevent X" health-bridge prompts — templated, not human-derived. Real coverage of the meaningful subset was 7/19 ≈ 37%. Always separate auto-templated entries from real corrections when reporting coverage. Future improvement: tag corpus entries with `source_type: templated|human` so the metric can split.

5. **Watch for the watchdog's own contract mismatch.** `health-watchdog.py` exits 1 when alerts exist (intentional), but cron's contract treats this as a cron failure. Same pattern in `auto-push.sh` — `|| echo "Push failed"` swallows the real git error, then the cron output claims "Pushed 295 uncommitted files" every hour even when push has been failing for 19h. Always spot-check claimed outputs against the actual downstream effect (commit log, push log).

6. **Output format:** Write the report to `~/.hermes/reports/strategist-audit-YYYY-MM-DD.md` and deliver a concise summary. Report MUST include: headline numbers, 🔴 Issues, 🟡 Warnings, 🟢 Good, 💡 Improvement suggestions. Each issue cites disk evidence (file path + line, command + exit code, or grep output) — never bare claims.

**Common false-positives to skip in the audit (from 2026-06-20):**
- `CRON_ERROR: idle-continuous-learning errored: Script timed out after 120s` — designed preempt, run log reason=preempted.
- `GIT_DIRTY: 295 uncommitted files` from `~/.hermes` — steady-state untracked runtime.
- `CRON_ERROR: health-watchdog errored: Script exited with code 1` — by-design (alerts exist).
- `IDLE_ERROR: idle-learning failed on last run` when run log shows reason=Complete — the watchdog read a stale intermediate state.

## Alert Escalation Hierarchy

Currently: watchdog → alert log → strategist audit (8am) → user sees in daily briefing.

Gap: No mid-day push for critical alerts. If gateway truly goes down, the user won't know until 8am next day. Candidate improvement: wire high-severity alert detection into a Telegram push via a cron job that runs every hour and only delivers if there are new high-severity alerts.

**Open follow-ups from 2026-06-20 audit:**
- [ ] Fix `reflect-on-correction.py` to only fire on new firings (replaces hardcoded templated output). Daily reflection currently unusable.
- [ ] Add watchdog classifier rule: suppress CRON_ERROR when run log shows reason=preempted.
- [ ] Fix watchdog exit contract: exit 1 only on internal failure, not on "alerts exist."
- [ ] Investigate `~/.hermes` auto-push silent failure — `git push origin main` may be failing for 19h+.
- [ ] Tag corpus entries with `source_type: templated|human` so coverage metric splits auto-templated from real corrections.
- [ ] Find why 6 of 10 policies have 0 hits after 2 days. Check F1 retrieval injection log first.
