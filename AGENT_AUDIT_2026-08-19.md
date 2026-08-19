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

### P3. Give it a real input queue: your PR log, in words (done)

This is the change that makes it a team member rather than a mirror, and it did not
need a new job. It needed the one outward-looking job it already had to be fixed.

`scripts/ci-watchdog.py` ran this morning at 07:02 and reported `last_status: ok`. Run by
hand, here is what it actually said:

```
⚠️ *Prospector* · CI `skipped`
🔴 *Signal Engine* · CI `failure` · 23h ago
```

Three defects, all measured:

1. **Its repo list was a hardcoded dict of four** — prospector, signalengine,
   haworks-platform, introduction-exchange. Two have no directory on this machine and two
   are projects you archived today. Archiving a project did not reach it. It now reads the
   active rows of `projects.json`, so P1 governs it.
2. **It asked `gh run list --limit 1`**, which returns the newest run of any workflow on any
   branch. On prospector that is the auto-merge workflow, whose conclusion is `skipped` —
   which is why it called a red main "skipped" while 27 pull requests sat open. "Is main
   green" is now asked of the check runs on main's head commit.
3. **It printed a URL.** A URL is a pointer to the evidence. It now opens the failing job
   and prints the cause.

And one thing it did dangerously: with every repo missing it printed
`CI watchdog: 4 repos healthy`. A blind probe now exits 1 and says it is blind.

Same job, same schedule, same script name. This is what it says now:

```
🔴 *prospector* · main is RED
   `lighthouse` — failed
   `smoke` — failed
⏳ *prospector* · 2 PR(s) still running — do not push to these, it cancels the run
🔴 *prospector* · 18 PR(s) red:
   #450 feat(guard): refuse a push that lands directly on — no test failed;
        python cancelled — a push cancelled this run
   #424 fix(ci): a stopped machine must not keep GitHub's — infrastructure, not
        tests — no step failed. The self-hosted runner lost communication with
        the server.
   …and 13 more not opened (cap is 5 log reads per repo)
```

**Not one of the eighteen red pull requests is a failing test.** They are cancelled runs and
dead runners. That is the answer you had to ask three sessions for, and it now arrives at
07:00 without anyone asking.

Deliberately NOT built: automatic merging. Report mode ships first. Merging a pull request is
outward-facing and hard to undo, and a merge fired at a run that is still going cancels
another session's work — the rule the ⏳ line exists to state. Say the word and it becomes a
second switch, default off.

- 17 tests in `tests/test_ci_watchdog.py`, mutation-proven on four separate breaks: a blind
  probe returning green, a cancelled check going unnamed, silent truncation, and archived
  projects being watched. Each one turns the suite red on its own.
- The logic is in `scripts/ci_watchdog_core.py` so it can be tested without GitHub; the
  script is the part that talks to `gh`.

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

### P5. The executor timeout — already fixed, and the number that said otherwise is stale

I proposed this on the strength of "236 failed, and `claude: timeout after 30s` is the most
common cause". Both halves are true and the conclusion was wrong, so here is the correction
rather than the fix.

The 236 failures are historical. By month: June 109, July 99, August 28. **The most recent
task with `status=failed` is 2026-08-02.** Nothing has failed in seventeen days.
`scripts/rsi-orchestrator.py:113` records the cap as 900s, not 30s — it was raised, and the
all-time 45% figure is dominated by two months that are already over.

What that changes: the live problem is not that its work fails. It is that its work is
worthless, which P1, P2 and P3 address. Quoting 45% as a current number would have sent the
next session tuning a timeout that is already correct.

## 4. What this does not change

Nothing above touches the money rail, the store, or the prospector engine. It changes what
the agent is pointed at, not what it is.

## 5. Status of the work

| Change | State |
|---|---|
| P1 phantom projects archived + 2 guards | committed, pushed, **deploying** |
| P2 cron trim: 27 enabled → 11, reasons recorded | committed, pushed, **deploying** |
| P4 summary menu + deep link + 19 tests | committed, pushed, **deploying** |
| P3 CI watchdog rewritten + 17 tests | committed, pushed |
| P5 executor timeout | **withdrawn — already fixed, see above** |

Suite: `~/.hermes/tests/` 267 passed, 1 xfailed. `hermes-agent/tests/gateway/operator_shell/`
952 passed, 8 skipped.

One thing the deploy taught us on the way: `channel_directory.json` was tracked in git, the
gateway rewrites its `updated_at` at every boot, and `deploy/hermes/deploy.sh` refuses to
ship a dirty tree. A file carrying no information was blocking every release. It is
untracked and ignored now.

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
