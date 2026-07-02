# PDD Activity Ledger — Disk-Artifact Data Sources

When a recurring briefing is asked a PDD-shaped question — "what functions were modified today?", "which specs were verified?", "any regressions blocked?", "new specs created?" — the answer lives in **disk artifacts**, not in `git log` queries inside sandboxed project directories. This reference documents the four canonical sources and how to compose them.

## The Four Axes and Their Canonical Disk Sources

| Axis | What it answers | Primary disk source | Secondary / cross-check |
|---|---|---|---|
| **Functions modified** | Which functions did the agent edit today? | `~/.lux/proving-ground/<date>.jsonl` — every `verify` action names a target function | `session_search(query=<fn-name>, sort=newest)` to find the edit tool call |
| **Specs verified** | Which specs were run through the verifier, and what was the verdict? | `~/.lux/receipts/<date>.jsonl` — filter `action: "verify"` | `~/.lux/proving-ground/<date>.jsonl` filter `check: "tests"` |
| **Regressions blocked** | Which verifications FAILED? | `~/.lux/receipts/<date>.jsonl` filter `verdict: "FAIL"` | Proving-ground filter `state: "failed"` |
| **New specs created** | Which specs were authored today? | `~/.lux/specs/*.json` mtime >= today | `~/.lux/receipts/<date>.jsonl` filter `action: "spec_create"` |

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

# 5. Today's sessions
session_search(sort='newest', limit=10)
```

If 2 returns 0 lines, 3 is all-skipped, 4 is empty, and 5 shows only cron/telegram sessions, the report is **"no PDD activity today"** — and that finding is itself genuine, not an artifact of the sandbox.

## Cross-Reference

- **`project-health-audit`** Pitfall #11 — the macOS sandbox CWD symptom this fallback addresses
- **`recurring-briefing`** Pitfall #14 — the recurring-briefing-specific version of the same fallback
- **`lux-proof-driven-development`** — the verifier / spec workflow that produces the receipts and specs being summarized
- **`popdd-inline-attestation`** — the chain-of-custody layer that signs the receipts