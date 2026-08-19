# Hermes Utilisation Programme

Published audit (interactive): https://claude.ai/code/artifact/3bb9e971-c5f5-45fc-8a66-f1433e87a11e

**The finding in one line: the agent is not idle. It is fully occupied, and almost none of the
work is the founder's.** Nine of eleven enabled cron jobs watch the agent. Sixty-seven of the last
121 tasks were reactions to its own crashed jobs. Five of its six most-loaded skills are the agent
maintaining the agent. Its output volume tracks its own brokenness, so making it healthier makes
it do less. That is the defect, and everything below is either evidence for it or a fix.

This file is the ledger. Append measurements here; never restate them from memory.

---

## 1. Measured state — 2026-08-19

Every row is a command, not a recollection. The command that produced it is in the third column.

| What | Measured | How to re-measure |
|---|---|---|
| Enabled cron jobs | 11 of 36 | `python3 -c "import json;j=json.load(open('cron/jobs.json'));print(sum(1 for x in j if x.get('enabled')), len(j))"` |
| …pointed at the agent itself | 9 of 11 | read `cron/jobs.json` names: otto-db-cleanup, health-watchdog, otto-dispatch, pytest-orphan-cleanup, queue-curator, telegram-ux-probe-daily, reliability-watchdog, delivery-canary, runaway-reaper |
| …pointed at the founder's business | 2 of 11 | ci-watchdog-daily, morning-briefing |
| Tasks in 14 days with `kind=failure` | 67 of 121 | `sqlite3 state/coordinator.db "select kind, count(*) from tasks group by kind"` |
| Tasks originating from the founder | 5 | same table |
| Skills tracked / ever loaded / never loaded | 95 / 54 / 41 | `skills/.usage.json` — **not** a log grep; log greps count unrelated mentions |
| Top six skills by load | 5 of 6 are self-management | `otto-operating-model` 109, `task-resilience` 54, `dropped-ball-prevention` 35, `estate-management` 31, `project-health-audit` 31, `lux-proof-driven-development` 26 |
| `/goal` invocations, all time | 0 | `rg -c "/goal" logs/agent.log logs/gateway.log` |
| `delegate_task` mentions, all time | 3 | same |
| Memory provider configured | `''` — none of 9 available | `config.yaml` `memory.provider` |
| Kanban board use | orchestrator 3 loads, worker 1 (June) | `skills/.usage.json` |
| Skill hub sources wired / installed from | 9 / 0 | `hermes skills tap` list vs `.hub/lock.json` |
| Curator runs with a machine-readable record | 1, and it failed | `ls logs/curator/*/run.json` |

## 2. The three defects, each with its receipt

### 2.1 The recursive self-improvement loop reviewed nothing and reported success

`logs/curator/20260813-061753/run.json` is the only curator run that ever wrote a machine-readable
record. It says:

    model    = 'standardcompute'      provider = 'custom'
    duration = 2.7s                   tool_calls = []
    llm_error = None
    llm_final = "You've used up your free trial — let's keep going.
                 Continue at a flat monthly price — no per-token billing, no surprise charges.
                 Set up your plan at https://standardcompute.com/dashboard/billing."

The vendor's billing upsell page was recorded as the skill review. `llm_error` is `None`, so
nothing failed as far as the curator was concerned, and `REPORT.md` renders it under the heading
`## LLM final summary`.

Config at that moment (`git show 3ff1da80:config.yaml`) said `model.provider: minimax`,
`model.default: MiniMax-M3`, `providers: {}`. The curator's own resolver
(`hermes-agent/agent/curator.py:1611 _resolve_review_runtime`) would have returned
`("minimax", "MiniMax-M3")`. It ran on something else.

**The class: a provider that answers HTTP 200 with a sales message is indistinguishable from a
working brain.** Anything downstream that treats "no exception" as "the work was done" will record
a dead brain as a successful review. Prospector already carries this rule for verdicts — *an
exception is never evidence; a failed call DEFERS* — and the same rule was missing here.

The sibling instance: `self-improve-runner`, 103 cycles, every one ending
`RULER EXHAUSTED — prompt-tune DECLINED`. Same shape, different loop.

### 2.2 The persona names tools that do not exist on the machine that runs it

`SOUL.md` is slot #1 of the system prompt on every turn. It declares a tool stack of `lux verify`,
`lux spec`, `lux generate-tests`, OMP/pi hashline edits, `~/.lux/review-specs/` and "Honcho
dialectic modeling", and ships response templates pre-filled with invented figures
(`✅ getUserFriendlyErrorMessage: 7/7 edge cases`, `calculateDiscount: 10000/10000 clauses`).

On the deployed host:

    fly ssh console -a prospector-hermes -C "command -v lux || echo NO_LUX; command -v pi || echo NO_PI; ls -d /root/.lux || echo NO_DOT_LUX"
    NO_LUX
    NO_PI
    NO_DOT_LUX

A model told it owns a verifier, handed templates of confident figures, and given no verifier,
produces confident figures. Note the trap in checking this: the laptop *does* have `pi` at
`/usr/local/bin/pi`, so a local probe passes while production fails. Verify on the deployed host.

### 2.3 The capability surface is bought and unopened

`/goal` (persistent standing objective with a judge after every turn), `delegate_task` (child
agents with isolated context), the Kanban board, the skill hub, webhooks, gateway event hooks,
profile distributions, deliverable mode and tool search are all present, all documented in
`~/.hermes/hermes-agent/website/docs/`, and all unused. The 343-page manual is on disk; nothing
needs fetching.

## 3. What changes

Tracked as five pieces of work. Each lands a mechanism, not a note.

1. **Document the audit.** This file. Done.
2. **Fix the self-improvement loops.** Route the curator explicitly, remove the dead
   `providers.standardcompute` block (`config.yaml:6-10`), and land a guard that fails a review
   whose LLM pass produced no structured block — so a dead brain can never again be filed as a
   successful review.
3. **Prune the dead skills.** `hermes curator run --dry-run` first (report before fix). Archive,
   never delete — the curator archives to `skills/.archive/` and snapshots to
   `skills/.curator_backups/`. Fix the three-way alias keying that splits one skill's staleness
   clock across `otto-operating-model`, `autonomous-ai-agents/otto-operating-model` and
   `autonomous-ai-agents:otto-operating-model`.
4. **Install skills from the hub.** Nine sources are wired and nothing has ever been installed.
5. **Rewrite SOUL.md** to name only what exists on the deployed host, move paths and commands to
   AGENTS.md per the Nous guidance, and land a test that fails if SOUL.md names a binary absent
   from the deployed image.

Then: enable `/goal`, invert the cron roster from nine self-checks to three plus outward jobs
drawn from `website/docs/guides/automation-blueprints.md`, and enable a local memory provider.

## 4. Traps found while measuring — do not re-learn these

- **Skill usage lives in `skills/.usage.json`.** Grepping logs for a skill name counts every
  unrelated mention of the phrase.
- **The same skill is keyed three ways** in `.usage.json` (bare, `dir/name`, `dir:name`), which
  splits its staleness clock. A count taken on one key undercounts.
- **The deploy source is `~/.hermes` itself** (`deploy/hermes/Dockerfile` does `COPY . .`), so
  `projects.json`, `cron/jobs.json`, `capabilities.json`, `config.yaml` and every skill are baked
  into the image. Only the SQLite DBs live on `/data`. Editing a file here and not deploying
  changes nothing in production.
- **`~/.hermes/hermes-agent` is a git submodule** with a pre-commit lane guard that also covers the
  parent files `config.yaml` and `scripts/coordinator.py`. Commit with `HERMES_LANE=claude git
  commit`; never `--no-verify`.
- **Never `git add -A` in `~/.hermes`.** `scripts/auto-push.sh:47` does exactly that and once
  committed `.env.bak*` with 26 live keys.
- **System `python3` on this laptop is 3.14 and has neither pytest-asyncio nor pytest-timeout.**
  `@pytest.mark.asyncio` gives a false PASS there; use `asyncio.run`, or the venv at
  `hermes-agent/venv/bin/python` (3.11.15).
