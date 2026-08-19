# Hermes agent audit — 2026-08-19

**Verdict: the agent is not idle. It is fully occupied, and none of the work is yours.**

In the last 14 days its coordinator ran 121 tasks. 67 were reactions to its own breakage.
54 were tasks it filed against itself, and 5 of those 54 originated from you in Telegram.
Zero produced anything the business could use.

---

## 1. The proof

Every number below came from `~/.hermes/coordinator.db` and `~/.hermes/cron/jobs.json` on
2026-08-19. The queries are in §6 so you can re-run them.

### What the work queue is made of

| Task kind, last 14 days | Count | What it is |
|---|---:|---|
| `failure` | 67 | The agent reacting to its own crashed jobs |
| `injected` | 54 | Filed work — of which 5 (`source=telegram`) came from you |
| anything else | 0 | — |

121 in total, and there is no third kind. Nothing in the queue came from the product, the customers, the
store, or the money rail.

### Two thirds of the synthetic work targeted repos that do not exist

`projects.json` listed 15 projects. **13 of them had no `repo` path and no directory on
this machine.** The agent filed work against them anyway:

| Project | Tasks filed, 14 days | On disk? |
|---|---:|---|
| portfolio-site | 15 | no |
| prospector | 14 | yes |
| tie | 6 | no |
| haworks-platform | 5 | no |
| ritualworks | 5 | no |
| signalengine | 4 | no |

35 of 54 injected tasks (65%) were unrunnable the moment they were created. They failed
with titles like `repo-health: lux: not found` and `prospector repo missing at
/Users/chidionyema/Documents/code/prospector`. **And each failure filed another task.**
That is the engine of the 67 `failure` rows.

Root cause in code: `scripts/coordinator.py::_project_repo` falls back to
`~/Documents/code/<key>` for any row with no `repo` key. A missing path never failed
loudly — it invented a plausible one.

### Half of everything it has ever run, failed

| Status, all time | Count |
|---|---:|
| done | 266 |
| **failed** | **236** |
| blocked | 13 |
| escalated | 11 |
| awaiting approval | 2 |
| cancelled | 1 |

**45% of 529 tasks did not complete.** 198 of the 236 failures recorded nothing in
`last_failure_error`; the cause was written to `result` instead, and it is the same cause
over and over: `claude failed (exit 1) and agy fallback failed`, and
`executor-narrative-fallback (claude: timeout after 30s)`.

### 16 of 27 cron jobs exist to talk about the agent

Enabled jobs, grouped by who the output is for:

| Group | Jobs | Count |
|---|---|---:|
| **The agent, about itself** | reflection-pulse-30m, reflection-digest-midday, reflection-digest-prebrief, daily-self-reflection, mentor-reflect, self-improve-runner, improvement-probe, idle-curiosity, idle-continuous-learning, daily-strategist-audit, weekly-progress-digest, Otto daily digest, complaint ledger, open-loop-aging-probe, estate-inventory-audit, "Summarize today's activity" | **16** |
| Keeping itself alive | health-watchdog, reliability-watchdog, runaway-reaper, queue-curator, pytest-orphan-cleanup, Otto DB cleanup, otto-dispatch, delivery-canary, telegram-ux-probe-daily | 9 |
| Pointed at anything outside itself | ci-watchdog-daily, morning-briefing | **2** |

Two of twenty-seven jobs look outward.

### The learning loops produce nothing

The self-improvement runner has completed 103 cycles. Every one ends
`RULER EXHAUSTED — prompt-tune DECLINED; no LLM spend`. The memory embedding layer is
off (`onnxruntime` is not installed, so retrieval falls back to tag matching). The
submodule backup fails on every run (`tar (child): xz: Cannot exec`).

---

## 2. The class of failure

> **The agent's work queue is fed by its own health monitors over a project list nobody
> curated. Its output volume is proportional to its own brokenness, not to your goals.**

The more it breaks, the busier it looks. A watchdog fires, files a task, the task fails
because the repo is not there, that failure fires the watchdog. Sixteen cron jobs then
write reflections about the resulting activity. From the outside it looks like a working
team member. From the inside, nothing leaves the building.

This is why "strip it down" and "make it useful" are the same instruction. You cannot make
this loop useful by improving the loop. You have to cut its input and give it a different
one.

---

## 3. Proposal — five changes, in order

### P1. Cut the phantom projects (done in the working tree, not yet deployed)

`projects.json`: 13 rows moved to `status: archived`, objectives stripped. Active is now
exactly `prospector` and `hermes-agent`, both real git checkouts.

- Guard: `tests/test_projects.py::test_the_estate_is_prospector_and_hermes` pins the roster.
- Guard: `tests/test_projects.py::test_an_active_project_points_at_a_real_checkout` fails if
  an active row names a path that is not a git checkout. Mutation-proven: pointing
  `hermes-agent` at a missing directory turns it red.
- Expected effect: the 35 unrunnable tasks per fortnight go to zero, and with them most of
  the 67 failure-reaction tasks.

### P2. Turn off the jobs whose only reader is the agent (done in the working tree)

**27 enabled → 11.** Every one of the 16 carries a `paused_reason` in `cron/jobs.json`
naming what it actually produced, so re-enabling any of them is one edit and the reason
travels with the data rather than living in this document:

| Disabled | Why |
|---|---|
| reflection-pulse-30m | one of four reflection jobs; read by the next reflection job only |
| reflection-digest-midday | second of four, same script |
| reflection-digest-prebrief | third of four, same script |
| daily-self-reflection | fourth. Four writers, zero readers outside the agent |
| mentor-reflect | filed lessons that became tasks about the agent; own failures say "no usable lesson" |
| self-improve-runner | **103 cycles, all ending `RULER EXHAUSTED — prompt-tune DECLINED`. Zero tunes applied** |
| improvement-probe | probes the improvement loop, which produces nothing |
| idle-curiosity | generated the "next move" tasks; 65% targeted repos not on disk |
| idle-continuous-learning | its own failures dominate the queue (`Phase 0a/0b` failed, repeatedly) |
| daily-strategist-audit | an LLM audit of the agent, by the agent; fails on "ran out of tool iterations" |
| weekly-progress-digest | a digest of the above |
| Otto daily digest (9am) | same content as morning-briefing plus Otto internals |
| complaint ledger | a ledger of the agent's own complaints; nothing acts on the rows |
| open-loop-aging-probe | ages the loops the job above opened |
| estate-inventory-audit | runs `estate-full-run.sh`, which has never written an output file |
| "Summarize today's activity…" | an LLM summary of the 15 above; last failure was a Gemini read timeout |

**Kept (11):** morning-briefing and ci-watchdog-daily (the two that look outward);
health-watchdog, reliability-watchdog, runaway-reaper, queue-curator, otto-dispatch,
pytest-orphan-cleanup, Otto DB cleanup, delivery-canary, telegram-ux-probe-daily (keeping
it alive and proving delivery works).

If you want any learning loop back, say which and it comes back with an acceptance test
that fails when it produces nothing — that is what none of them had.

- `tests/test_cron_jobs_are_runnable.py`: 38 tests green.
- One of its own guards had to be fixed to allow this: `test_the_scan_is_not_vacuous`
  asserted `>= 20` enabled jobs, which pinned the roster size rather than proving the scan
  had something to grade. It now asserts the list is non-empty and that it matches
  `jobs.json` exactly. Mutation-proven: emptying the helper turns it red.

### P3. Give it a real input queue: your PRs and issues

This is the change that makes it a team member rather than a mirror. The agent has no
source of business work — so give it the one queue that is unambiguously business work and
that you have asked about three times this week: **the prospector GitHub queue.**

One job, every morning and every four hours:

1. List open PRs. For each: is CI green, is it mergeable, is it claimed by a session?
2. Merge the ones that are green and unclaimed.
3. For the ones that are red, open the failing job log, extract the first failing
   assertion, and post ONE message naming the PR, the test, and the assertion.
4. Never merge a PR whose CI is currently running (that cancels another agent's run).

Right now there are 30 open PRs. That job would have told you, this morning, that #451
carries 8 failures and that all 8 are the same store-path pollution bug — instead of you
asking.

- Acceptance: the job posts a message containing a PR number and a test name, and the open
  PR count falls.

### P4. Make the summary card reachable (done, not yet deployed)

You asked for it as a menu option and a permanent link. Both are built and guarded:

- `summary` added to `OPERATOR_TELEGRAM_MENU` — it was a registered command with **no menu
  slot**, so the operator profile filtered it out of Telegram's command list entirely and
  it could only be reached by typing it from memory.
- Permanent link: `https://t.me/<bot>?start=summary`. Hermes has no public HTTP surface
  (`fly.toml` declares no `[http_service]`), so a web URL would mean new infrastructure; a
  Telegram deep link needs none. `?start=summary_Chidi_Onyema` renders the card directly.
- 19 tests in `tests/gateway/operator_shell/test_summary_is_reachable.py`, mutation-proven
  at 7 failures and 3 failures across two rounds. One of them round-trips the printed link
  through the handler, so a link the handler would reject cannot ship.
- The card itself was rebuilt around a layout function (`_CARD_WIDTH`, `_rule`, `_band`)
  instead of hand-typed box art, pinned by 24 geometry tests.

### P5. Fix the executor timeout that manufactures the failures

`claude: timeout after 30s` is the single most common cause behind the 236 failures. A
30-second cap on an agentic call guarantees a fallback narrative rather than an answer. It
needs to be a config key with a realistic value, not a constant.

- Acceptance: a task whose executor call takes 90s completes instead of falling back.

---

## 4. What this does not change

Nothing above touches the money rail, the store, or the prospector engine. It changes what
the agent is pointed at, not what it is.

## 5. Status of the work

| Change | State |
|---|---|
| P1 phantom projects archived + 2 guards | written, tested, **uncommitted** |
| P4 summary menu + deep link + 19 tests | written, tested, **uncommitted** |
| P2 cron trim: 27 enabled → 11, reasons recorded | written, tested, **uncommitted** |

| P3 PR/issue input queue | not started |
| P5 executor timeout | not started |

Nothing is live. `~/.hermes` is a git repo (`chidionyema/hermes-config`) and the deploy
copies the working tree into the image, so none of this reaches the bot on Fly until it is
committed and `deploy/hermes/deploy.sh` runs.

## 6. Re-run the numbers

```bash
cd ~/.hermes
# task kinds and sources, last 14 days
python3 -c "
import sqlite3, datetime as dt
from collections import Counter
c = sqlite3.connect('coordinator.db')
cut = (dt.datetime.now() - dt.timedelta(days=14)).timestamp()
print(Counter(r[0] for r in c.execute('select kind from tasks where created_at>?', (cut,))))
print(Counter(r[0] for r in c.execute('select status from tasks')))
"
# active projects, and whether they exist
python3 -c "
import json, os
for p in json.load(open('projects.json'))['projects']:
    if p.get('status') == 'active':
        r = os.path.expanduser(p.get('repo') or '')
        print(p['key'], r, os.path.isdir(os.path.join(r, '.git')))
"
# enabled cron jobs
python3 -c "
import json
j = json.load(open('cron/jobs.json'))['jobs']
print(sum(1 for x in j if x.get('enabled')), 'of', len(j))
"
```
