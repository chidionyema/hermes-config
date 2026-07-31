# Hermes agent — deep audit, 2026-07-31

Scope: `~/.hermes/hermes-agent` (the agent) and `~/.hermes` estate wiring. Product repos
(prospector / signalengine / TIE) were explicitly out of scope.

Every finding below carries a `file:line`, a command transcript, or a runnable repro. Where a
claim is not proven it is labelled `UNPROVEN` with the exact check that would settle it. Live
state is the probe, not this document — run:

```bash
bash ~/.claude/projects/-Users-chidionyema/.state-probe   # AGENT_SHELL line
cd ~/.hermes/hermes-agent && HERMES_LANE=claude venv/bin/python -m pytest tests/gateway/operator_shell/ -q
```

---

## Summary

The operator shell is 3,167 LOC of remote process control reachable from a phone. It was not the
code that was weak — it was that **nothing could tell you when it broke**. The estate has a probe,
a watchdog and a lane guard; the agent that runs them had none of that pointed at itself. Every
red finding below is a consequence of that one asymmetry.

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | Untracked, unreviewed code with `launchctl bootout` powers, importable by the live gateway | 🔴 | Fenced (3 layers); tree still dirty — **open** |
| F2 | Committed test suite was RED; no gate before commit, none after push | 🔴 | Fixed + gated |
| F3 | `dict.fromkeys(paths)[:4]` crashed the task-status card on 12% of real tasks | 🟠 | Fixed both copies + regression test |
| F7 | `sqlite3.Row.get()` crash-looped the executor on every coding run | 🔴 | Fixed — **not live until coordinator restart** |
| F4 | Tests imported 5 of 16 modules; 2,550 LOC untested, incl. everything that shells out | 🟠 | Partly fixed (11 → 58 tests) |
| F5 | 74 broad `except` in 3,167 LOC; 20 swallow silently | 🟡 | One instance fixed; 73 remain |
| F6 | 3,167 LOC live in a 1.6 GB third-party monorepo with no push rights | 🟡 | Open — needs a decision |

---

## F1 — Unreviewed code, one restart from live 🔴

Caught mid-audit by watching `git status` change under me:

```
08:23:44  ?? gateway/operator_shell/daemons.py                            (1 file)
08:25:57   M estate.py  M fleet.py  M mission.py  M natural_ops.py
           ?? daemons.py  ?? prospector_daemon.py                         (6 files)
           estate.py: committed 723 LOC -> working 845 LOC
```

`daemons.py` (8,857 bytes, untracked) shells out to `launchctl kickstart / bootout / bootstrap`
(`daemons.py:240,242,249,251`) against `ai.hermes.gateway` and `ai.hermes.coordinator` — the
agent's own life support. `estate.py:333` imports it. The committed tree does not:

```bash
$ git show 5aa5788607:gateway/operator_shell/estate.py | grep operator_shell.daemons
(empty)
```

**Correction to my first reading.** I initially attributed the writes to coordinator task
`3b326b72` ("when was the prospector daemon last run"). That was wrong — the founder confirmed a
second agent was working, and the settling query showed `3b326b72` never wrote anything; it
crash-looped instead (see F7). The lesson stands regardless of author: git had never seen this
code, no test covered it, and the gateway would import it on restart.

**Status.** The gateway has restarted twice since these modules appeared (PID 57012 at 08:26:05,
PID 83135 at 08:49:13), so the live process is running a tree that contains them. The imports are
function-local inside `handle_estate_action` (`estate.py:333, 351, 532`), so they load on button
press, not at start.

> `UNPROVEN`: that anything has actually *pressed* those buttons.
> `__pycache__/daemons.cpython-311.pyc` (08:25:49) and `prospector_daemon.cpython-311.pyc`
> (08:37:32) prove some Python 3.11 process imported both, but mtimes cannot distinguish the
> gateway from my own test runs. Settling check:
> `grep -i "render_daemons\|estate:daemons" ~/.hermes/logs/agent.log`.

The runtime fence, however, is proven live — not in a test, in the production gateway log:

```
2026-07-31 08:49:16,417 ERROR gateway.operator_shell.integrity: integrity: operator_shell is
running UNREVIEWED code: daemons.py, prospector_daemon.py present in
/Users/chidionyema/.hermes/hermes-agent/gateway/operator_shell but untracked by git.
```

Three seconds after the 08:49:13 restart. Before today, that restart would have been silent.

**Fix — three independent layers**, because one gate you can forget is not a fence:

1. **Commit time** — `.git/hooks/pre-commit` gate 4 (UNTRACKED-IMPORT GATE). Walks the AST of every
   staged `operator_shell` file and blocks the commit if it imports a sibling module git has never
   seen. Verified against the live tree:
   ```
   X pre-commit UNTRACKED-IMPORT GATE:
       gateway/operator_shell/estate.py imports gateway.operator_shell.daemons
         -> daemons.py is not tracked and not staged
   ```
   Written with a regex first; the regex invented a module name because `[\w,\s]+` spans newlines
   and misses `as` aliases. My own gate caught it. Now uses `ast.walk` over `Import`/`ImportFrom`.
2. **Run time** — `gateway/operator_shell/integrity.py`. Logs `ERROR ... running UNREVIEWED code`
   naming each untracked module. **Warns by default, deliberately**: denying at import would turn a
   hygiene problem into a gateway outage for any work-in-progress module. `HERMES_STRICT_TRACKED_IMPORTS=1`
   makes it fatal — flip that once the tree is clean. 8 tests in `test_integrity.py`.
3. **Session start** — the `AGENT_SHELL` probe line reports `ghost_imports=` every session.

Currently reporting, correctly:

```
AGENT_SHELL     PASS:58t  ghost_imports=prospector_daemon,daemons  operator_shell_tree=DIRTY:6f
```

**Still open:** the six dirty files are the other agent's. They need review and a commit (or
removal) before `ghost_imports` reads `none`.

> ⚠️ That work is **still in flight** as of writing: `prospector_daemon.py` mtime moved to
> `08:49:00` and the gateway restarted at `08:49:13`, i.e. within a minute of this audit being
> written and after the second agent was reported finished. Re-check before acting:
> `git status --short gateway/operator_shell/`.

---

## F2 — The suite shipped red, invisibly 🔴

```
$ HERMES_LANE=claude venv/bin/python -m pytest tests/gateway/operator_shell/ -q
1 failed, 10 passed in 1.16s
FAILED test_operator_shell.py::test_filter_operator_menu_preserves_order
```

Shipped that way in `5aa5788607`. The **test** was wrong, not the code: it expected input order
(`['help','new','panel','cron']`) while `menu.py:49` documents "in `OPERATOR_TELEGRAM_MENU` order"
and `new` is correctly not Tier-0 (`menu.py:9-22`). Actual: `['panel','cron','help']`.

Why nothing caught it — **two independent gaps**:

- `.git/hooks/pre-commit` compiled staged Python and enforced the lane guard, but ran no tests
  (`pre-commit:4,44,46`).
- CI never ran the branch. `gh run list --repo chidionyema/hermes-agent` returns runs only on
  `backup-2026-06-20`, all `schedule`, all **skipped**. Zero runs on `operator-shell-20260731`.
  The repo reports `.fork == false` with **5 workflows enabled** against upstream's 17 —
  `tests.yml` is not among them.

**Fixed.** Assertion corrected (and renamed to say what it actually pins:
`test_filter_operator_menu_uses_tier0_order_not_input_order`), plus a second test for the drop
behaviour. New `pre-commit` gate 3 (TEST GATE) runs the suite whenever `operator_shell` or its
tests are staged, ~2s. Verified by staging a deliberately-red test:

```
X pre-commit TEST GATE: tests/gateway/operator_shell/ is RED
COMMIT BLOCKED: you touched operator_shell and its suite fails.
```

**Still open:** CI. See "Decisions needed".

---

## F3 — The status button crashed on every successful run 🟠

`code_remote.py:260` — `", ".join(dict.fromkeys(paths)[:4])`. `dict.fromkeys` returns a dict, and
a dict is not sliceable. Replayed against the real `coordinator.db`:

```
tasks sampled: 200   would-render-fine: 176   WOULD CRASH: 24
first crasher: ('524eade0', TypeError, ['../../executor-settings.js'])
```

Reachable from the 👁 status button via `estate.py:662-664 -> render_task_card`. The trigger is a
result naming a source file — i.e. **every coding run that did its job**. Raises `TypeError` or
`KeyError` depending on interpreter; both crash.

**Fixed** in both copies (`code_remote.py:260`, and the twin at `coordinator.py:1773` found by
sweeping for the pattern). Coverage proven by mutation, not asserted:

```
fix reverted   -> 5 failed, 43 passed
fix restored   -> 48 passed
```

---

## F7 — The executor crash-looped on every coding run 🔴 (new, found while settling F1)

`conn.row_factory = sqlite3.Row` (`coordinator.py:385`), and `sqlite3.Row` has no `.get()`. Five
calls used it anyway — `1696, 1704, 1706, 1765, 1769` — all on the executing/done path of tasks
whose `source` starts with `code:`. Task `3b326b72` logged 12 identical failures in 68 seconds:

```
08:23:59 error  AttributeError: 'sqlite3.Row' object has no attribute 'get'
08:24:04 error  ...  (x10 more, ~5s apart)
```

Behavioural proof:

```
OLD  r.get('source')  -> AttributeError 'sqlite3.Row' object has no attribute 'get'
NEW  r['source']      -> 'code:telegram'
```

Bracket access is the idiom everywhere else in the file (40 uses) and works on both `Row` and
`dict`, so it is safer in either case. All five columns exist in the `tasks` schema, so no
`IndexError` is being traded for the `AttributeError`.

> **NOT LIVE.** Coordinator PID 83464 started 07:27:56; `coordinator.py` mtime is 08:35:36. Python
> binds at import, so the running daemon still executes the crashing code. It picks the fix up on
> restart — a founder decision, not taken here.

---

## F4 — Tests covered the safe 19% 🟠

`test_operator_shell.py:5-19` imported 5 of 16 modules (`cron_ops, menu, natural_ops, proof,
voice_brief` = 617 LOC). **2,550 LOC (81%) untested**, including everything that executes:

| Untested | LOC | Powers |
|---|---|---|
| `estate.py` | 723 | `subprocess.run` (`:535`), all panel dispatch |
| `code_remote.py` | 460 | drives Claude Code runs; held F3 |
| `mission.py` | 289 | 13 broad `except` |
| `builds.py` | 244 | 5× `subprocess.run` |
| `rsi_panel.py` | 242 | self-improvement surface |

**Partly fixed: 11 → 58 tests.** New `test_code_remote.py` (fake coordinator over in-memory sqlite
with real `sqlite3.Row` rows — no estate/daemon dependency) covers the F3 regression, command
parsing, the money/identity fence, and natural-language assignment. New `test_integrity.py` covers
the F1 fence.

One test deliberately pins a **known gap** rather than hiding it —
`test_detect_fence_is_keyword_only_and_misses_paths`: `detect_fence` reads words, not blast radius,
so `"fix the buy button in store_platform"` is **not** fenced as money. That is a real hole in the
money fence, documented as a failing-by-design expectation so it surfaces if anyone tightens it.

**Still open:** `estate.py` (723 LOC), `builds.py`, `rsi_panel.py`, `mission.py` remain untested.

---

## F5 — Silent failure is designed in 🟡

74 broad `except` across 3,167 LOC (one per 43 lines); 20 followed by bare `pass`.

Concrete instance fixed — `code_remote.py:79-82`. The circuit-breaker probe was wrapped in
`except Exception: pass`, leaving the optimistic default `claude_ok = True`, so the tool reported
**"Claude Code CLI ready"** when it had no idea. It now reports `⚠️ Breaker state unknown
(probe failed: ...)` and logs the exception. This is the prose-drift failure mode, implemented in
code: a component asserting health it never verified.

**Still open:** 73 handlers. Not a mechanical sweep — each needs a judgement about whether the
swallow is deliberate.

---

## F6 — The monorepo tax 🟡

`origin` = `NousResearch/hermes-agent` → **403 denied**. 11,868 commits (4 authored here),
539 MiB pack, **1.6 GB `.git`**, 204,851 LOC upstream. Your work is 3,167 LOC — **0.15%** of the
tree — parked on a branch of a personal `backup` remote whose default branch
(`backup-2026-06-20`) does not contain it.

This is the root of F2's CI gap: workflows, branch protection and test config all belong to
upstream, tuned for a 204k-LOC project, and none of it points at your directory.

> Note on a recon claim I did not accept: a subagent reported the repo as "1,562 test files /
> 30,398 tests / risk LOW". Those are **upstream's** numbers. Measured directly, the operator
> shell had 11 tests over 99 lines.

---

## What is healthy

Worth stating plainly, since the above is all defect:

- `estate_watchdog.py` is load-immune — `os.kill(pid, 0)` (`:62`), not `ps | grep` — with heartbeat
  freshness (`:92`), wake/catch-up grace (`:193-213`, from a real 2026-06-21 false page), debounced
  alerts (`:179`) and debounced restarts (`:227`). It alerts on a wedged loop; it never kills.
- `coordinator.py:1613` refuses to escalate without a prior `diagnosis` event — "ping the human
  without investigating" is structurally impossible.
- Dependencies are exact-pinned, no ranges, with the supply-chain rationale written down.
- The pre-commit hook's existing gates carry *why* they exist, citing the incidents that caused
  them. That habit is the reason this audit had anywhere to start.

The estate layer is well built. The agent repo is where the discipline stopped.

---

## Changes landed

| Repo | Commit | Contents |
|---|---|---|
| `hermes-agent` | `77fe5fa616` | F3 fix + regression, F2 test fix, `integrity.py` + tests, F5 instance. 11 → 58 tests |
| `hermes-config` | `90911e5` | F7 `Row.get()` ×5, F3 twin at `coordinator.py:1773` |
| untracked | `.git/hooks/pre-commit` | gates 3 (TEST) + 4 (UNTRACKED-IMPORT) |
| untracked | `.state-probe` | `AGENT_SHELL` line |

⚠️ **`.git/hooks/` is not version-controlled.** Gates 3 and 4 exist on this machine only and vanish
on a fresh clone — the same weakness the lane guard already had. Fixing that properly means a
tracked `hooks/` directory plus `core.hooksPath`, which is part of the Tier-2 extraction below.

---

## How to 100x this

Not by writing more agent code. The constraint is the feedback loop, and it is now partly built.

**Tier 1 — make red visible.** Mostly done: F2/F3/F5-instance/F7 fixed, TEST GATE and
UNTRACKED-IMPORT GATE in place, `AGENT_SHELL` in the probe. Remaining: enable `tests.yml` on the
fork so red is caught off this laptop too.

**Tier 2 — extract, and the tax disappears.** Move `gateway/operator_shell/` + tests to
`chidionyema/hermes-operator`: 3.2k LOC, own history, push rights, CI in seconds, tracked hooks via
`core.hooksPath`, no 403. Consume upstream Hermes as a dependency. This is the step that changes
the *rate* rather than the state — every future fix stops paying the 1.6 GB / 204k-LOC tax.

**Tier 3 — extend the probe.** `AGENT_SHELL` now covers suite + ghost imports + tree cleanliness.
Next: assert every `estate:*` callback rendered by `mission.py` has a handler in `estate.py`
(dead-button detection), and that no daemon is running stale code — exactly the F7 condition, which
went unnoticed for over an hour.

**Tier 4 — fence the self-authoring loop.** Layers built (commit / runtime / probe). Flip
`HERMES_STRICT_TRACKED_IMPORTS=1` once the tree is clean, so unreviewed code cannot start at all.

**Sequencing:** clear the dirty tree before Tier 2 (don't carry unreviewed modules into a new repo);
restart the coordinator to activate F7 before trusting any coding run's status.

---

## Decisions needed

1. **Restart the coordinator** — F7's fix is on disk, not in the running process (PID 83464, 07:27:56).
2. **The six dirty files** — the other agent's work needs review + commit, or removal. Until then
   `ghost_imports` stays non-empty and strict mode cannot be enabled.
3. **Enable `tests.yml`** on `chidionyema/hermes-agent` and trigger on push.
4. **Tier 2 extraction** — creates a new GitHub repo; not started.
5. **Push `77fe5fa616`** — committed locally, not pushed (`origin` 403s; `backup` remote works).
