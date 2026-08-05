# Hermes — the founder's product expectations, made falsifiable

**Status:** report-only. No code changed. Companion to `AGENT_AUDIT_2026-08-05.md` (what is broken)
and `REMEDIATION_PLAN_2026-08-05.md` (how it gets fixed). This file answers a different question:
**what is this product supposed to be, and how would we know it had arrived?**

The founder stated eight expectations. Prose expectations are how projects drift — the estate rule
is *state is a probe, not a paragraph*. So each one below is restated as a **definition of done that
can fail**, given a **probe** (a command with a target number), and measured **today**.

Every "measured today" line carries the command that produced it. Where I could not measure
something in this session it is marked **UNVERIFIED** with the exact command that would settle it —
not filled in from the audit, memory, or estimate.

---

## Summary table

| # | Expectation | Probe exists? | Measured today | Verdict |
|---|---|---|---|---|
| E1 | Personal agent that makes technical life a dream | no — E1 is the sum of E2–E7 | — | composite |
| E2 | Manage all machine work from Telegram | **no** | action surface UNVERIFIED; no workflow-coverage measure exists | **unmeasured** |
| E3 | Proactive, visible, measurable recursive self-improvement | partial (`prove_rsi.py`) | **0 improvements applied, ever** (ledger, 7 weeks) | **not happening** |
| E4 | Telegram UX heavenly, seamless, top notch | **no** | zero UX tests in the cockpit suite | **unmeasured** |
| E5 | Set up seamlessly from scratch | **no** | upstream bootstrap exists; **estate layer has none** | **broken for the product** |
| E6 | Whole SDLC comfortable, local + GitHub | **no** | UNVERIFIED | **unmeasured** |
| E7 | Commercial product that bootstraps easily | **no** | 0 of 399 cockpit functions accept a caller identity (audit A2) | **blocked, structurally** |
| E8 | Deep research into Hermes docs, leverage properly | in progress | two research passes running | **pending** |

The pattern is the finding: **six of eight expectations have no measure at all.** That is not a
detail — it is why the estate can look green and be dead (audit F6/F7/F8). An expectation without a
probe cannot be delivered, only claimed.

---

## E1 — "a personal agent that makes my technical life a dream"

E1 is not independently measurable; it is the conjunction of E2–E7. Its honest proxy is a
**friction ledger**: the tasks you actually do in a week, and for each, whether the agent did it,
you did it by hand, or you did it by hand *after* the agent failed.

**Definition of done:** for one full week, ≥80% of the founder's recurring technical tasks complete
from Telegram without a fallback to the terminal, and zero of them require repairing the agent.

**Probe (does not exist yet — build it):**
```bash
# Every cockpit action taken, with outcome, over 7 days. Requires an action-outcome log
# that records (action_id, actor, started, finished, outcome, fell_back_to_terminal).
sqlite3 ~/.hermes/coordinator.db "SELECT outcome, COUNT(*) FROM action_log
  WHERE started > datetime('now','-7 days') GROUP BY outcome;"
```
**Measured today:** no `action_log` table is specified. UNVERIFIED — and unmeasurable until one
exists. This is the single highest-leverage new artefact in this document: without it, "better and
better user experience" (E2) has no gradient to climb.

---

## E2 — "manage all my work on telegram that i currently do on this machine"

The load-bearing word is **all**. That demands a denominator: the set of things you do on this
machine. No such list exists, so "all" is currently unfalsifiable.

**Definition of done:** a written inventory of your recurring machine workflows, each mapped to a
cockpit action, with a coverage percentage that is tracked over time and only goes up.

**Probe:**
```bash
# Numerator: distinct cockpit actions actually registered.
rg -o "estate:[a-z0-9_:]+" ~/.hermes/hermes-agent/gateway/operator_shell/ --no-filename | sort -u | wc -l
# Denominator: WORKFLOW_INVENTORY.md — does not exist yet. Coverage = numerator ∩ inventory / inventory.
```
**Measured today:** two counting methods disagreed — 170 unique `estate:*` substrings, but only 1
match when restricted to single-quoted literals. Neither is the true registered-action count, so I
am not reporting one. **UNVERIFIED.** Settle it by counting at the registration site (the handler
map), not by grepping strings:
```bash
rg -n "def (register|handle)_.*action|CALLBACK_ROUTES|ACTION_REGISTRY" \
  ~/.hermes/hermes-agent/gateway/operator_shell/ | head -30
```
`AGENT_AUDIT_2026-08-05.md:32` records 77 `estate:*` actions; that is the audit's measure, not one I
reproduced today, and the two grep methods above suggest the counting rule matters. Fix the counting
rule before either number is used as a baseline.

**Gap:** "all my work" cannot be delivered against an undefined denominator. Write
`WORKFLOW_INVENTORY.md` first — it is an hour of your time and it converts E2 from a wish into a
percentage.

---

## E3 — "proactive, self improving, with clear goals, actions, reflections, and visible and measurable recursive self improvement"

**This is the expectation with the hardest evidence, and it is the worst result in this document.**

The machinery is real and quite complete: `scripts/rsi-orchestrator.py`, `scripts/prove_rsi.py`,
`state/rsi-goals.json` (3 goals), eval sets at `meta/rsi_evalsets/{EXECUTE,VERIFY}_PROMPT.jsonl`, a
version ledger at `meta/improver-versions.jsonl`, and a launchd job `meta/launchd/ai.hermes.rsi.plist`.
Someone built the loop properly. It is not running, and it has never changed anything.

**Measured today — three commands, three findings:**

```
$ launchctl list | rg -i 'rsi|hermes|otto'
85713   0   ai.hermes.gateway
46835   0   ai.hermes.coordinator
```
→ `ai.hermes.rsi` **is not loaded**. The plist exists; launchd does not know about it.

```
$ wc -l ~/.hermes/meta/improver-versions.jsonl
       1
$ tail -1 ~/.hermes/meta/improver-versions.jsonl
{"timestamp": "2026-06-18T10:11:25Z", "version": "v1", ...
 "total_changes_applied": 0, "successful_changes": 0, "policy_count": 8, ...}
```
→ **One entry, dated 2026-06-18, recording zero changes applied and zero successful.** In the ~7
weeks since, the improver has not versioned itself once. The "recursive" part of recursive
self-improvement has a measured value of **0**.

```
$ tail -6 ~/.hermes/logs/rsi-autorun.log     # last write: 2026-08-03 04:30
  ❌ Failed to generate prompt variant: route('strategist') exhausted all 3 providers:
     claude-cli: You've hit your weekly limit · resets Aug 6 at 7am
     agy-cli: Individual quota reached ... Resets in 33h17m22s
     deepseek/deepseek-v4-pro: APIConnectionError: no DEEPSEEK_API_KEY
2026-08-03T04:30:40+0100 prompt-tune(EXECUTE_PROMPT) exit=0
```
→ The last run, two days ago, **failed on every provider and still exited 0**. Same failure class as
audit F11 (`quota_honesty` fails open): the loop reports success while doing nothing. `no
DEEPSEEK_API_KEY` is a fixable config gap; the exit-0-on-total-failure is a defect.

**Definition of done:** the improvement ledger grows, each entry is attributable, and a rejected
improvement is as visible as an accepted one.

**Probe (target: strictly increasing, ≥1 applied change per week):**
```bash
# PR-14 — RSI is actually recursing.
python3 - <<'PY'
import json,datetime
rows=[json.loads(l) for l in open('/Users/chidionyema/.hermes/meta/improver-versions.jsonl')]
last=rows[-1]; age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(last['timestamp'].replace('Z','+00:00'))).days
print(f"versions={len(rows)} applied={last['total_changes_applied']} successful={last['successful_changes']} age_days={age}")
assert age < 8, "improver has not versioned in over a week"
assert last['total_changes_applied'] > 0, "zero improvements ever applied"
PY

# PR-15 — the runner is loaded and its last run did real work.
launchctl list | grep -q ai.hermes.rsi || echo "FAIL: rsi job not loaded"

# PR-16 — no more exit-0-on-total-failure.
rg -n "exhausted all .* providers" ~/.hermes/logs/rsi-autorun.log | tail -1
# a run whose providers all failed MUST exit non-zero
```

**Gap → this deserves its own workstream.** The plan's WS2 (cockpit honesty) only stops the RSI
panel *lying* about the loop. It does not make the loop *run*. Add **WS10 — make RSI real**: load
the launchd job, give the strategist a provider that is not quota-starved, make total provider
failure exit non-zero, and gate on PR-14.

**Note on "proactive":** proactivity is the agent starting work you did not ask for. That makes the
E3 workstream depend on **D1 (the safety fence)** being settled first — audit F1 proved fenced
money/identity/contract tasks already auto-closed without approval. A proactive agent behind a
broken fence is the one combination that can cost real money. **Sequence: D1 → WS1 → WS10.**

---

## E4 — "the telegram user interface and experience heavenly and seamless and top notch"

**Definition of done:** every destination reachable in ≤2 taps from the root; no destination
orphaned; no action offered under two different buttons; every long-running action gives feedback
within 1s.

**Probe (does not exist — build it):**
```bash
# PR-17 — reachability BFS over the keyboard graph. Target: max depth ≤2, orphans = 0, dup actions = 0.
.venv/bin/python -m pytest tests/gateway/operator_shell/test_reachability.py -q
```
**Measured today:**
```
$ ls ~/.hermes/hermes-agent/tests/gateway/operator_shell/ | rg -i 'reach|bfs|ia_|nav'
(none)
```
→ **There is no UX test of any kind in the cockpit suite.** The 479 passing cockpit tests
(`AGENT_AUDIT_2026-08-05.md:487`) test behaviour, not experience. "Top notch" currently has zero
instrumentation, which means it can only ever be asserted.

**Prior art worth reusing:** the same BFS-reachability approach was used on this cockpit before and
found 45 of 83 destinations were 3+ taps deep. That is a lead, not a current measurement — the test
does not exist in the tree today, so the number must be re-derived before it is quoted.

---

## E5 — "set this all up seamlessly from scratch"

There are **two** setups here, and they are in very different states.

**Upstream Hermes setup: present.** `hermes-agent/scripts/install.sh`, `install.cmd`,
`hermes-agent/setup-hermes.sh`, `hermes-agent/hermes_bootstrap.py`,
`hermes-agent/apps/bootstrap-installer/`, `hermes-agent/hermes_cli/setup.py`.

**Your estate layer: absent.** A `find` over `~/.hermes` (excluding the fork) for
`*install*|*bootstrap*|*setup*` returns only `scripts/install_keepawake.sh` and
`scripts/setup-embedding-model.py` — nothing that stands up the cockpit, the coordinator, the
launchd jobs, the secrets, or the state stores.

**Why this matters more than it looks:** everything that makes Hermes *yours* — 52 operator_shell
modules, 143 scripts, the launchd jobs, `coordinator.db`, `.env` — has no reproducible install path.
That is simultaneously the E5 blocker, the E7 blocker, and your disaster-recovery exposure. Today,
if this Mac dies, the estate is not recoverable from the repo.

**Definition of done:** a clean machine (or a container) reaches a working cockpit from one command
plus a secrets file, verified by the estate's own probe.

**Probe:**
```bash
# PR-18 — from-scratch bootstrap. Run in a container or a throwaway user account.
git clone <estate-repo> ~/.hermes && cd ~/.hermes && ./bootstrap.sh   # does not exist yet
bash ~/.hermes/scripts/verify_estate.sh                               # target: exit 0
```
**Measured today:** `bootstrap.sh` does not exist; PR-18 cannot run. Note the probe's own dependency
— it terminates in `verify_estate.sh`, which per the audit currently reports **DEGRADED**, so E5's
finish line moves only once WS2/WS6 land.

---

## E6 — "manage the whole sdlc process comfortably for projects on my machine and in github"

**Definition of done:** name the stages, then measure coverage per stage — plan → branch → code →
test → review → CI → merge → deploy → verify → rollback. For each: is there a cockpit action, and
does it work against both a local repo and a GitHub repo?

**Probe:**
```bash
# PR-19 — SDLC stage coverage matrix. Target: 10/10 stages have a working action, both targets.
# Build as a table in SDLC_COVERAGE.md, each row backed by a passing integration test.
```
**Measured today:** `operator_shell/sdlc.py` exists (audit cites `sdlc.py:110` as one of only two
subprocess calls that correctly narrows `env=`, so it is real code, not a stub), but my grep for
`estate:sdlc:*` action ids returned nothing, which means the actions are named some other way.
**UNVERIFIED** — settle with:
```bash
rg -n "sdlc" ~/.hermes/hermes-agent/gateway/operator_shell/*.py | rg -v "^.*sdlc\.py:" | head -40
```
**Known blocker from the audit:** the coding-run fence (`code_remote.py:151`) fires at *task
creation, before a plan exists*, and misses 8 of 8 realistic money tasks (audit F4). SDLC automation
is precisely the surface that fence guards. **E6 cannot safely expand before D1 is decided.**

---

## E7 — "eventually a commercial product that bootstraps easily"

**The structural blocker is already proven:** audit A2 — **0 of 399 public functions in
operator_shell accept a caller identity, and there are 0 authorization checks** (all authz lives
upstream at `authz_mixin.py:176`). Every action implicitly runs as "the founder". A second paying
user cannot exist until an actor is threaded through.

This expectation makes plan decision **D4 no longer optional**. D4 offered a choice: thread `actor`
now while it is 399 mechanical edits, or write down "never a second user". **E7 removes the second
option.** Thread it now — it is mechanical today and becomes a rewrite once behaviour depends on it.

Secondary, from the audit's §6: the fork is MIT (© 2025 Nous Research) — permissive, with attribution
obligations and a **naming/trademark risk** on "Hermes". Commercial launch needs a name that is not
upstream's. That is plan decision D6.

**Definition of done:** a second user account can be created, sees only their own tasks, and cannot
invoke a fenced action against the first user's estate.

**Probe:**
```bash
# PR-20 — tenancy isolation. Target: 0 cross-tenant reads, 0 unauthenticated fenced actions.
.venv/bin/python -m pytest tests/gateway/operator_shell/test_tenancy_isolation.py -q
# PR-21 — no function mutates estate state without an actor argument.
rg -n "def (run|exec|apply|deploy|approve)_" ~/.hermes/hermes-agent/gateway/operator_shell/ \
  | rg -v "actor" | wc -l   # target: 0
```
**Measured today:** neither test exists. PR-21's current value is effectively 399 (audit A2).

---

## E8 — "deep research into hermes docs to ensure we are leveraging properly"

In progress at the time of writing — two research passes running:
1. **Upstream docs leverage table** over `hermes-agent/docs/`, `website/docs/`, README: every
   documented capability marked USED / PARTIALLY USED / UNUSED with grep evidence, focused on
   documented **extension points** that would let in-fork edits to `run.py`, `telegram.py`,
   `slash_commands.py`, `coordinator.py` be deleted.
2. **Estate docs coverage + contradiction map** over the nine `~/.hermes/*.md` docs: which
   expectations are already specified and where the docs contradict the live system.

Pass 1 feeds plan decision **D3** (extension boundary vs. conscious hard fork) directly — if
upstream documents a plugin or MCP surface that covers what the in-fork edits do, D3 answers itself
and the 500-line threshold is not needed.

**Results are appended to this file when both land. Nothing about E8 is concluded yet.**

---

## What the expectations change about the plan's decisions

| Decision | Status before | After these expectations |
|---|---|---|
| **D1** — where the safety gate lives | open, blocks WS1 | **Now blocks E3 and E6 too.** A proactive, self-modifying agent driving SDLC is exactly the workload the fence must survive. Decide first. |
| **D2** — what we owe upstream's tests | open | Unchanged by the expectations. |
| **D3** — fork boundary | decide from a measurement | **Answer may come from E8 pass 1** — if a documented extension point covers the in-fork edits, take it. Measure only if it does not. |
| **D4** — thread `actor` now? | genuine choice | **Resolved by E7.** "Never a second user" is off the table. Thread it while it is mechanical. |
| **D5** — leave this Mac? | defer the port | **E5 pulls this forward.** A from-scratch bootstrap that only ever targets one Mac is not a bootstrap. Build `bootstrap.sh` platform-agnostic even if only macOS is tested. |
| **D6** — naming | open | **Now commercially load-bearing** via E7. "Hermes" carries upstream trademark risk. |

## New workstreams these expectations create (the plan does not have them)

| WS | Name | Serves | First deliverable |
|---|---|---|---|
| **WS10** | Make RSI real | E3 | Load `ai.hermes.rsi`; total-provider-failure exits non-zero; PR-14 green |
| **WS11** | Action-outcome telemetry | E1, E2, E4 | `action_log` table + the weekly friction report |
| **WS12** | Workflow inventory & coverage | E2, E6 | `WORKFLOW_INVENTORY.md`; coverage % becomes a tracked number |
| **WS13** | UX instrumentation | E4 | Reachability BFS test (PR-17); depth ≤2, orphans 0, dups 0 |
| **WS14** | From-scratch bootstrap | E5, E7 | `bootstrap.sh` → `verify_estate.sh` exit 0 on a clean account |

**Ordering note.** WS10–WS14 are *product* work; WS1/WS6 (fence, secrets) are *safety* work. The
safety work is Wave 0 and stays first — not on principle, but because F1 proved the fence has
already been bypassed three times in production, and every one of these expectations increases the
agent's blast radius.

---

## The honest bottom line

The expectations are achievable and the underlying machinery is more complete than the audit's tone
suggests — the RSI loop, the eval sets, the goal store, the SDLC module, upstream's bootstrap
installers all exist and are real work.

What is missing is **the measurement layer**, uniformly. Six of eight expectations have no probe,
and the one place a self-improvement number does exist, it reads `total_changes_applied: 0` and has
not moved in seven weeks. That is the same defect the audit found in the cockpit (F6: hardcoded
numbers displayed as telemetry) and in the estate backup (F8: dead 4.15 days, silently) — a system
that reports on itself from prose rather than from probes will converge on looking healthy while
being dead.

So the first product move is not a feature. It is: **give every expectation a number that can go
down.**
