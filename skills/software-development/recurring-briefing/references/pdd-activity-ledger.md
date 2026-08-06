# PDD Activity Ledger — Disk-Artifact Data Sources

When a recurring briefing is asked a PDD-shaped question — "what functions were modified today?", "which specs were verified?", "any regressions blocked?", "new specs created?" — the answer lives in **disk artifacts**, not in `git log` queries inside sandboxed project directories. This reference documents the four canonical sources and how to compose them.

## The Four Axes and Their Canonical Disk Sources

| Axis | What it answers | Primary disk source | Secondary / cross-check | Per-project POPDD chain |
|---|---|---|---|---|
| **Functions modified** | Which functions did the agent edit today? | `~/.lux/proving-ground/<date>.jsonl` — every `verify` action names a target function | `session_search(query=<fn-name>, sort=newest)` to find the edit tool call | `<project>/.lux/test-receipts/chain-<ts>.jsonl` — `action: "edit"` entries carry `added`/`diffLines` |
| **Specs verified** | Which specs were run through the verifier, and what was the verdict? | `~/.lux/receipts/<date>.jsonl` — filter `action: "verify"` | `~/.lux/proving-ground/<date>.jsonl` filter `check: "tests"` | `<project>/.lux/test-receipts/chain-<ts>.jsonl` — `action: "verify"` with `proof.passedClauses / proof.totalClauses / proof.invariantSamples` |
| **Regressions blocked** | Which verifications FAILED? | `~/.lux/receipts/<date>.jsonl` filter `verdict: "FAIL"` | Proving-ground filter `state: "failed"` | Same chain file — `verdict: "FAIL"` |
| **New specs created** | Which specs were authored today? | `~/.lux/specs/*.json` mtime >= today | `~/.lux/receipts/<date>.jsonl` filter `action: "spec_create"` | Same chain file — `action: "edit"` with `added: ["<SPEC_NAME>"]` |

> The per-project POPDD chain (`popdd-on-lux` output) is the most detailed record when present — it carries clause counts, invariant samples, and the actual diff. When the disk artifacts above are sparse, query `find <project>/.lux/test-receipts/chain-*.jsonl -newermt <today>` first; sandbox-blocked projects will not appear (Pitfall #14 in SKILL.md).

## File Format Reference

### `~/.lux/receipts/<date>.jsonl` (POPDD receipts)

One JSON object per line. Append-only, HMAC-signed. Schema (relevant fields):

```json
{
  "action": "verify" | "spec_create" | "edit" | "commit" | ...,
  "target": "<function-name or spec-name>",
  "proof": {
    "verdict": "PASS" | "FAIL",
    "passed": 10000,
    "total": 10000,
    "samples": 10000
  },
  "ts": "2026-07-02T17:30:00Z",
  "sig": "<HMAC>"
}
```

Useful `jq` queries:

```bash
# All verifies today, with verdict
jq -r 'select(.action=="verify") | "\(.ts)  \(.target)  \(.proof.verdict)  \(.proof.passed)/\(.proof.total)"' \
   ~/.lux/receipts/$(date +%Y-%m-%d).jsonl

# All FAILED verifies (regressions blocked)
jq -r 'select(.action=="verify" and .proof.verdict=="FAIL") | "\(.target): \(.proof.passed)/\(.proof.total)"' \
   ~/.lux/receipts/$(date +%Y-%m-%d).jsonl

# All spec_create actions
jq -r 'select(.action=="spec_create") | "\(.ts)  \(.target)"' \
   ~/.lux/receipts/$(date +%Y-%m-%d).jsonl
```

### `~/.lux/proving-ground/<date>.jsonl` (audit log)

One JSON object per line. Records every check the auditor attempted against each project. Schema:

```json
{
  "project": "lux-popdd",
  "check": "tests" | "build" | "imports" | "popdd-dependency" | ...,
  "state": "passed" | "failed" | "skipped",
  "required": true | false,
  "path": "/Users/chidionyema/Documents/code/lux-popdd",
  "exit_code": 0,
  "summary": "<human-readable outcome>"
}
```

When a project path is sandboxed, `state: "skipped"` with a summary like `"Current directory does not exist"` or `"realpath: .venv/bin/: Operation not permitted"` indicates the audit could not reach the project — see `project-health-audit` skill's macOS CWD sandbox reference.

### `~/.lux/specs/*.json` (spec registry)

One JSON file per spec. mtime >= today means the spec was created or modified today. Schema varies by implementation; the `functionName` field is the canonical target.

**Important (added 2026-07-05):** `~/.lux/specs/` and `~/.lux/review-specs/` **may simply not exist** if no spec has ever been created on this estate. Before claiming "no new specs today," check whether the directory exists at all:

```bash
ls -la ~/.lux/specs/ 2>&1 | head -3
ls -la ~/.lux/review-specs/ 2>&1 | head -3
# Either may return "No such file or directory" — that is itself the signal
```

Do NOT `mkdir` them — the briefing is read-only. Report the absence honestly.

## Worked Example — 2026-07-02

This is the actual state observed by the daily-activity cron on 2026-07-02.

### `~/.lux/proving-ground/2026-07-02.jsonl` (verbatim)

```
{"project": "popdd-ts", "check": "tests", "state": "skipped", ...}
{"project": "lux-popdd", "check": "tests", "state": "skipped", "summary": "Current directory does not exist"}
{"project": "signalengine", "check": "imports", "state": "skipped", "summary": "Current directory does not exist"}
{"project": "prospector", "check": "imports", "state": "skipped", "summary": "python: realpath: .venv/bin/: Operation not permitted"}
```

### `~/.lux/receipts/2026-07-02.jsonl`

Empty / non-existent — no `verify` actions signed today.

### `~/.lux/specs/*.json` (mtime >= 2026-07-02)

None.

### Session search (today's sessions)

```
session_search(sort='newest', limit=10)
→ morning-briefing cron (54 msgs)
→ daily-strategist-audit cron (106 msgs)
→ Hermes honest progress audit (telegram, 37 msgs)
```

### Composed daily-activity report

```
## Code Changes: None
No commits, no file modifications, no function edits across any tracked repo.

## Specs Verified: None
~/.lux/receipts/2026-07-02.jsonl is empty. Weekly verify cron runs Sunday at midnight.

## Regressions Blocked: None
No FAIL verdicts in receipts (because no verifies ran today).

## New Specs Created: None
No files in ~/.lux/specs/ with mtime >= today.

## Sandbox Notice
All four tracked project paths were unreachable from the cron sandbox
(proving-ground shows "Operation not permitted" / "directory does not exist"
for popdd-ts, lux-popdd, signalengine, prospector). The disk-artifact
fallback (receipts + specs + sessions) confirms no activity regardless —
the empty state is genuine, not an artifact of the sandbox.
```

## Per-Project POPDD Chain Receipts (added 2026-08-06)

When `popdd-on-lux` is integrated into a project, its chained, HMAC-signed actions are written to `<project>/.lux/test-receipts/chain-<timestamp>.jsonl`. This file is **the most detailed record of project-local activity** when present — more so than `~/.lux/proving-ground/<date>.jsonl` (which only records aggregate check outcomes) and `~/.lux/receipts/<date>.jsonl` (which only carries hermes-session merged actions when `popdd-inline-attestation` is active).

**Schema (relevant fields):**

```json
{
  "sequence": 1,
  "timestamp": "2026-08-06T16:27:15.089Z",
  "agentId": "lux-popdd-demo",
  "action": "verify" | "edit" | "test-run",
  "target": "<function-name or spec-name>",
  "proof": {
    "verdict": "PASS" | "FAIL",
    "passedClauses": 3011,
    "totalClauses": 3011,
    "invariantSamples": 1000,
    "tests": 5, "passed": 5, "failed": 0, "duration_ms": 12,
    "diffLines": 38,
    "added": ["weightedAverage function", "WEIGHTED_AVERAGE_SPEC"],
    "sha256": "demo-no-real-file-edit"
  },
  "previousHash": "...",
  "contentHash": "...",
  "signature": "..."
}
```

**Discovery recipe:**

```bash
# Today's chain receipts across all projects (will fail if ~/Documents/code/ is sandboxed)
find ~/Documents/code -path '*/.lux/test-receipts/chain-*.jsonl' \
  -newermt "$(date +%Y-%m-%d)" 2>/dev/null

# Fallback when the project directory is unreachable
find ~/.lux/test-receipts -name 'chain-*.jsonl' \
  -newermt "$(date +%Y-%m-%d)" 2>/dev/null

# List just the most recent N chains for the report
ls -t ~/.lux/test-receipts/chain-*.jsonl 2>/dev/null | head -5
```

**One chain receipt per project per popdd-session**: a chain file uses `INITIALIZED` for the first entry then `verify / edit / test-run / ...` for subsequent entries. The last entry's `action` tells you what the session ended with (usually `verify` or `test-run`).

**Honest-gaps footer note (added 2026-08-06):** add "per-project POPDD chains surveyed at N project `.lux/test-receipts/` directories" so the user knows whether the chain layer was actually polled.

## Sandbox Fallback Recipe

When the projects are blocked but you still need to report:

```bash
# 1. Confirm today's date in user-local timezone
date +%Y-%m-%d

# 2. Today's receipts (signed proof of verify actions)
test -f ~/.lux/receipts/$(date +%Y-%m-%d).jsonl && \
  wc -l ~/.lux/receipts/$(date +%Y-%m-%d).jsonl

# 3. Today's proving-ground log (what the auditor tried)
test -f ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl && \
  jq -r '"\(.project)  \(.check)  \(.state)  \(.summary)"' \
       ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl

# 4. New specs today
find ~/.lux/specs -name '*.json' -newermt "$(date +%Y-%m-%d)" 2>/dev/null

# 5. Today's sessions  — NOTE: use ~/.hermes/state.db, NOT sessions.db (see SKILL.md pitfall #15)
sqlite3 -header ~/.hermes/state.db \
  "SELECT id, title, source, message_count,
          datetime(started_at,'unixepoch') AS started
   FROM sessions
   WHERE started_at >= strftime('%s','$(date +%Y-%m-%d)')
   ORDER BY started_at;"
```

If 2 returns 0 lines, 3 is all-skipped, 4 is empty, and 5 shows only cron/telegram sessions, the report is **"no PDD activity today"** — and that finding is itself genuine, not an artifact of the sandbox.

## Sustained-Zero Detection (added 2026-07-05)

When the daily-activity cron reports "no activity" 3 or more consecutive days, the briefing should **escalate from "today was quiet" to "the substrate has been broken for N days"**. This is a different finding — the absence has a duration worth flagging.

**Pattern matched 2026-07-02 → 2026-07-05:** Three consecutive daily-activity crons all reported zero function/spec activity. Root cause was the same each day: `~/Documents/code/` sandboxed + proving-ground all-skipped + receipts empty + review-specs dir never existed. The honest answer for the user is "no activity has been observable since <date>" not just "no activity today."

**Detection recipe:**

```bash
# 1. List recent proving-ground logs with their "all-skipped" status
for d in $(ls -t ~/.lux/proving-ground/ | head -7); do
  total=$(wc -l < ~/.lux/proving-ground/$d)
  skipped=$(grep -c '"state": "skipped"' ~/.lux/proving-ground/$d)
  passed=$(grep -c '"state": "passed"' ~/.lux/proving-ground/$d)
  failed=$(grep -c '"state": "failed"' ~/.lux/proving-ground/$d)
  echo "$d  total=$total  skipped=$skipped  passed=$passed  failed=$failed"
done

# 2. Find the LAST day with any "passed" entries
grep -l '"state": "passed"' ~/.lux/proving-ground/*.jsonl 2>/dev/null | tail -1

# 3. Find the LAST day with any new receipts file
ls -t ~/.lux/receipts/ | head -3
```

**Output framing (use when N >= 3 days of all-skipped):**

```
⚠️ Substrate has been unobservable for N consecutive days (since YYYY-MM-DD).
The daily proving-ground has run every day but every check returned state=skipped
because [path permission / directory missing / venv blocked]. No receipts have
been written since [last-date-with-receipts]. No code activity has been recorded
on this estate in N days — this is NOT absence-of-evidence, it is sustained
evidence-of-absence at the substrate level. Recommended: fix sandbox access OR
move the projects to a path the cron can reach.
```

**Rule:** when reporting a zero-activity day, always check the prior 3-7 days of the same logs. If the pattern is sustained, escalate the finding to a substrate-level report. If the pattern is one-day, report it as today-only with a note that the prior day was different.

## Cross-Reference

- **`project-health-audit`** Pitfall #11 — the macOS sandbox CWD symptom this fallback addresses
- **`recurring-briefing`** Pitfall #14 — the recurring-briefing-specific version of the same fallback
- **`recurring-briefing`** Pitfall #15 — `state.db` vs `sessions.db` and the schema gotchas
- **`lux-proof-driven-development`** — the verifier / spec workflow that produces the receipts and specs being summarized
- **`popdd-inline-attestation`** — the chain-of-custody layer that signs the receipts