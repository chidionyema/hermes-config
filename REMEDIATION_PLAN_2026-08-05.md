# Hermes — remediation plan for `AGENT_AUDIT_2026-08-05.md`

Companion to the audit. The audit says what is wrong; this says what we do about it, in what
order, who has to decide what, and — for every one of the 18 findings — **the command that proves
it fixed**.

Framing convention, per the estate's own rule *"state is a probe, not a paragraph"*: no item in
this plan is "done" because someone says so. Each has an acceptance probe that exits 0/1. The
plan's own definition of done is: **`bash ~/.hermes/scripts/verify_estate.sh` exits 0 and its
output includes every new probe line added below.**

Ownership levels used throughout:

| | Meaning |
|---|---|
| **P — principal** | The call is expensive or impossible to reverse. One person decides, in writing, before work starts. Six of these (D1–D6) gate everything else. |
| **S — staff** | Owns a workstream end to end: design, implementation, and authoring its acceptance probe. Sign-off from P on the design, not the diff. |
| **D — delegable** | Mechanical, spec-able, reviewable by probe. Per `~/.claude/CLAUDE.md` model-routing ladder, goes out to Gemini/DeepSeek against a written spec. **Exception, and it is absolute: WS1 and WS6 touch the money/identity fence and secret handling and never leave Claude (founder fence).** |

Effort figures are **estimates, not measurements** — each is labelled with the check that would
replace the estimate with a number.

---

## 0. New evidence since the audit shipped (four hours ago)

Three things changed the picture. Two make the plan more concrete; one makes a finding worse.

**(a) The fence violation count is 3, not 2.** The audit queried for the specific bypass payload.
The correct query is the *invariant* — "a fenced task reached `done` with no approval event" —
and it finds one more:

```sql
SELECT substr(t.id,1,12), t.risk_class, t.source, datetime(t.completed_at,'unixepoch')
FROM tasks t
WHERE lower(COALESCE(t.risk_class,'')) IN ('money','identity','contract')
  AND t.status='done'
  AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='approved');
```
```
06eadbc7ea90  contract  telegram              2026-07-31 02:46:03   ← NOT found by the audit's query
8fb949064732  identity  project:tie           2026-07-31 02:46:03
1582bddd1a8b  money     project:signalengine  2026-07-31 02:46:03
```

The lesson is a design instruction, not a correction: **detect on the invariant, not on the known
bypass.** The invariant catches routes nobody has thought of. It becomes probe **PR-1** below, and
its target value is `0`. (`approved` is the right event kind — `coordinator.py:1975`.)

**(b) The CI failure is narrower than "CI is red".** The audit left this undiagnosed. Established
today:

- Both failing test files are **100% upstream-authored** — `git log --format='%an' --
  tests/gateway/test_session_hygiene.py` → Teknium ×9, teknium1 ×2, three others ×1; zero founder
  commits. Same for `tests/e2e/test_platform_commands.py`.
- `tests/gateway/test_session_hygiene.py` **passes locally: 23 passed in 1.87s.**
- It is not the blanked API keys — reran with `OPENROUTER_API_KEY="" OPENAI_API_KEY=""
  NOUS_API_KEY=""` exactly as `tests.yml:114-118` sets them: **23 passed**.
- It is not dependency drift — reran under CI's exact resolution,
  `uv sync --locked --python 3.11 --extra all --extra dev` into `.venv` (149 site-packages entries
  vs the live `venv/`'s 293): **23 passed in 1.71s**.

So: **the founder's own code is not what is red.** What remains is Linux-vs-macOS or contention
inside CI's per-file parallel runner. That reframes WS5 from "fix our broken tests" to "decide what
we owe upstream's tests", which is a **principal** decision (D2), not staff toil.
**HYPOTHESIS** — remaining cause is platform or runner concurrency. Settling check: the same
`python scripts/run_tests_parallel.py --slice 3/6` invocation locally, then in a Linux container.

**(c) `.venv` has no pytest at all** (`.venv/bin/python -m pytest` → `No module named pytest`)
while `venv/` is the live gateway's interpreter (`ps -o command= -p 85713`). Two venvs, one live,
one CI-shaped, and the fat one is what everybody types. This is the same class as the estate's
recorded `ddgs split-brain` trap. Folded into WS5.

---

## 1. Principal decisions — D1–D6

These are the calls that cannot be delegated and that everything else hangs off. Each states the
options, a recommendation with the failure mode that distinguishes it, and the cost of deferring.

### D1 — Where does the safety gate live, and what does it read? **(blocks WS1)**

*The problem in one line:* `code_remote.py:151` calls `detect_fence(body)` **at task creation**,
before any plan or diff exists — so a blast-radius classifier physically cannot run there. Fixing
the vocabulary at that call site cannot fix the class of bug.

| Option | What it is | Failure mode that kills it |
|---|---|---|
| **A. Widen the keyword lists** | Merge the three regexes into one, add the missing words | The audit's own F4 table: 8 of 8 realistic money tasks used none of the words. Adding words does not fix "words". `test_code_remote.py:197` already asserts this. |
| **B. Blast-radius gate in the executor** | After the plan/diff exists, before mutation, classify by touched paths + target repo | The agent can edit its own classifier. `prospector/self_modify.py` exists; self-modification is in scope for this estate. A control in the process it governs is not a control. |
| **C. Enforcement in the repo, not the agent** | Managed money-rail repos get branch protection; the agent may only open PRs, never push to protected branches | Requires a GitHub token per repo and breaks any flow that pushes directly. Slower loop. |

**Recommendation: C as the enforcement layer, B as the detection layer, A retained only as a cheap
trip-wire.** The distinguishing scenario, stated concretely: a task whose body is *"tidy up the
coordinator's auto-close logic"* is not money-classed by any vocabulary, is executed by an agent
that can rewrite its own fence, and under B alone would land. Under C it cannot land in a protected
repo without a human approving a PR — and the agent's token does not carry `admin` rights to remove
the protection. That is a difference that survives the agent being wrong about itself.

*Cost of deferring:* every day the autopilot runs is another draw against a control that has
already failed 3 times.

### D2 — What do we owe upstream's test suite? **(blocks WS5)**

Given §0(b) — the red is entirely in upstream-authored tests — the options are:

| Option | Consequence |
|---|---|
| **A. Fix upstream's tests on our fork** | Unbounded. We inherit 17k tests we did not write and cannot upstream fixes to without a PR relationship. |
| **B. Gate CI on our own surface only** | Add a `hermes-cockpit` job running `tests/gateway/operator_shell/` + `tests/e2e` we authored; make **that** required. Leave the upstream matrix advisory (`continue-on-error`). |
| **C. Turn CI off** | Loses the only mechanism that could have caught F1 before production. |

**Recommendation: B.** Named failure mode for A: upstream moved `aec331899e..fb402106f8` during the
audit alone; fixing their tests on our fork is work that is invalidated on every fetch. Named
failure mode for C: F1 shipped and ran in production for five days undetected; a required check on
the fence invariant is the specific thing that would have blocked it.

*Note this decision is entangled with D3 — if we take the extension-boundary route, "our surface"
becomes a clean, small, permanently-stable test target.*

### D3 — Fork: extension boundary, or conscious hard fork? **(blocks WS7)**

Do not decide this from the audit's estimate. **Decide it from a measurement**, which is one
command:

```bash
cd ~/.hermes/hermes-agent && git diff 21d80ca683..HEAD --stat -- \
  gateway/run.py gateway/platforms/telegram.py gateway/slash_commands.py hermes_cli/commands.py
```

**Decision rule, set in advance so the number decides and not the mood:**
- **< ~500 changed lines across those four files → extension boundary.** Extract to
  `operator_shell/`, leave one registration hook, target zero upstream diffs, `git pull` becomes
  routine.
- **> ~500 → conscious hard fork.** Vendor upstream at a pinned SHA, delete the `origin` remote,
  write down that we will never take upstream changes, and own the security-patch burden
  explicitly.

Either answer is defensible. **Drifting is the only indefensible one, and drifting is the current
state.** The decision is required this month; the measurement takes 30 seconds.

### D4 — Do we thread `actor` now? **(blocks WS8)**

A2 measured 399 public functions, **0** taking a caller identity. Threading an unused `actor`
parameter now is 399 mechanical edits. Threading it after there is live per-tenant state is 399
edits *plus* a data migration of `state.db` (102MB) and `coordinator.db` (29MB).

**Recommendation: yes, now, unused.** This is cheap insurance and it is reversible (an unused
parameter can be deleted). Deferring is the irreversible move. **If the answer is "we will never
have a second user", say so in writing and close A2 as accepted risk** — that is a legitimate
outcome and it saves the 399 edits.

### D5 — Platform: do we ever leave this Mac? **(scopes A3)**

`daemons.py:21-110` hardcodes launchctl labels, `Path.home()` paths, and one specific project
(`com.tie.ai-review`). **Recommendation: defer the port, but stop deepening the hole today** —
introduce a `Supervisor` interface with a single `LaunchdSupervisor` implementation, and make it a
review rule that no new `launchctl` string appears outside it. Cost now: hours. Cost of the same
decision in six months: proportional to how much new daemon code we write in between.

### D6 — Naming, and what the hourly auto-commit is for.

Two unrelated calls, both cheap now and expensive later.

1. **Name.** Selling a fork of NousResearch's "Hermes" under the name "Hermes" is a trademark
   question that MIT does not answer. **HYPOTHESIS — I am not qualified to rule on this and have not
   searched the registers.** Settling check: UKIPO/EUIPO/USPTO search in software classes, plus 20
   minutes of solicitor time. Budget for a rename; the cost of renaming rises with every published
   artefact. Separately, MIT obligations stand: keep `LICENSE` and © 2025 Nous Research, add your
   own copyright alongside rather than over it.
2. **The hourly `auto: sync` commit is a backup, not version control** — no review, no CI. Decide
   whether `main` on `~/.hermes` is a reviewed branch or a snapshot stream. **Recommendation:** push
   snapshots to a `snapshots/` branch and keep `main` reviewed, so "the estate committed itself"
   and "a human changed the estate" stop being the same signal.

---

## 2. Workstreams

Nine workstreams. Each: owner level, findings closed, the change, the acceptance probe, and an
effort estimate labelled as such.

### WS1 — Fence integrity *(P0 · owner: **S**, design signed off by **P** · **never delegated**)*
**Closes F1, F2, F3, F4.** Depends on **D1**.

1. **Stop the bleeding — today, ~1 hour.** Move the fail-closed check from `coordinator.py:2131`
   to the **top** of the `for r in rows:` loop at `coordinator.py:2093`, above the junk-injection
   branch at `:2098` and the read-only escape at `:2105`. Delete the unreachable duplicate at
   `:2133-2134`.
2. **Delete the second predicate.** Remove `_is_readonly_status_objective` (`coordinator.py:1640`)
   and its only call site (`:2105`). The false-fence annoyance it solved is worth strictly less than
   the hole it opened — and F1's own evidence is that the hole was taken three times while the
   annoyance cost nothing but a manual tap.
3. **One classifier, one module.** Collapse `coordinator.py:419 FENCE`, `coordinator.py:759
   fence_class`, and `code_remote.py:21 _FENCE_RE` into a single `hermes/fence.py` with one
   vocabulary and one public API. Three vocabularies is the root cause of F2.
4. **Blast-radius gate** per D1: classify on touched paths / target repo / commands, evaluated
   after the plan exists and before mutation. Keywords demote to a trip-wire that can only *raise*
   risk, never lower it. **Delete the self-declared-intent downgrade at `coordinator.py:759-761`
   entirely** — nothing may lower its own risk class by asserting it is read-only.
5. **Repo-side enforcement** per D1(C) for money-rail repos.
6. **Backfill the 3 violations** to a terminal state that records what happened, rather than
   leaving `done` records that the invariant will flag forever.

**Acceptance probes:**
```bash
# PR-1 — the invariant. MUST print 0. Add this line to verify_estate.sh.
sqlite3 ~/.hermes/coordinator.db "SELECT COUNT(*) FROM tasks t
  WHERE lower(COALESCE(t.risk_class,'')) IN ('money','identity','contract') AND t.status='done'
  AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='approved');"

# PR-2 — regression test, must exist and pass: a money-classed task cannot reach done
#         without an approved event, by ANY route through drain/auto-close.
# PR-3 — the F4 table: all 8 realistic money tasks now fence. The existing test that asserts the
#         gap (test_code_remote.py:197) must be inverted, not deleted.
```
**Estimate: 4–6 engineer-days** for items 1–4; item 5 depends on how many repos are in scope.
*Replace the estimate with:* the count of call sites of the three fence functions.

### WS2 — Cockpit honesty *(P1 · owner: **S**)*
**Closes F6, F7, F8, F12, F13, and UI weaknesses 1–3, 5.**

- Delete `rsi_control.py:94-95` (the two fabricated metrics). Replace `latest_health = 0.69`
  (`:28`) with `None` rendering as `unknown`.
- Replace `OFF_SWITCH`-absence liveness (`rsi_control.py:46-49`) with a heartbeat + freshness bound.
  **Rule to apply everywhere, not just here: liveness is `last_run_at` within N intervals; the
  absence of a kill-switch file is not evidence of life.**
- Fix the `self-improve-hourly` interpreter/args split in the cron runner (`Script not found:
  …/scripts/python3 scripts/self_improve_runner.py --hourly`).
- `rm ~/.hermes/.git/index.lock`; delete the non-executable duplicate `~/.hermes/auto-push.sh`;
  find out why `scripts/auto-push.sh`'s own >300s stale-lock cleanup did not execute on a
  358,678s-old lock — **that is the real defect; the lock is just the symptom.**
- Diagnose `com.haworks.continuous-review last exit=1` (F12) — the single ❌ making the estate probe
  say DEGRADED. Next check: `launchctl print gui/$UID/com.haworks.continuous-review` + its stderr log.
- `proof.py:57-59`: give `failed` a distinct glyph from `pending_confirm`. `mission.py:485`: remove
  the literal `💰 Spend n/a`. Move the `estate.py:180-202` docstring above the first statement.

**Acceptance probes:**
```bash
# PR-4 — freshness. MUST fail if the last estate sync commit is older than 6h. New verify_estate.sh line.
# PR-5 — no fabricated metrics: AST sweep for placeholder-free f-strings under a "state" heading → 0.
# PR-6 — bash ~/.hermes/scripts/verify_estate.sh exits 0 (closes F12).
```
**Estimate: 2–3 engineer-days.** Mostly deletion. **Delegable except the freshness probe design.**

### WS3 — Retire the silent-failure class *(P1 · owner: **S**, execution **D**)*
**Closes F9, F11, and UI weakness 2.**

166 broad handlers, **91** silent. This is the estate's most expensive recurring defect — the
memory index records three separate multi-day outages caused by exactly this pattern
(`_refine_wave zero-yield`, the word-salad query generator, `web_calls structurally zero`).

- Lint rule: `except Exception: pass` without `logger.debug(..., exc_info=True)` fails the build.
- Fix the two bare `except:` at `rsi_control.py:43` and `:83` first — bare `except` also swallows
  `KeyboardInterrupt` and `SystemExit`.
- `code_remote.py:83-90` `quota_honesty` fails open while its own comment says it should not.
  Tolerable for a quota breaker; **write down that the pattern is forbidden for any safety breaker**,
  and make WS1's fence fail *closed* on probe failure.
- Order the 91 by blast radius, not by file: the 7 never-tested modules that shell out
  (`projects` ×4, `notify_fanout` ×2, `rsi_control` ×2, `commercial_ui`, `diagnose_panel`,
  `incident_panel`, `predict_panel`) go first.

**Acceptance probe:**
```bash
# PR-7 — MUST print 0.
grep -rEc '^\s*except( Exception| BaseException)?\s*:\s*$' \
  ~/.hermes/hermes-agent/gateway/operator_shell/*.py | awk -F: '{s+=$2} END{print s}'
# (refined by the lint rule, which distinguishes logged from silent)
```
**Estimate: 3–4 engineer-days** for the sweep, then permanent. Highly delegable behind the lint rule.

### WS4 — Atomicity and state ownership *(P1 · owner: **S**)*
**Closes F10, A4.**

- `proof.py:91-103`: `os.replace()` onto a same-directory tempfile + `fcntl.flock`. Note the
  estate's own recorded trap — **macOS has no `flock(1)`**; this is Python's `fcntl.flock`, which is
  what is being specified.
- Same treatment for the ~14 loose JSON files in `~/.hermes` mutated by both gateway and
  coordinator (`gateway_state.json`, `channel_directory.json`, `projects.json`, `processes.json`,
  `meta/operator_shell/idempotency.json`).
- `pop_undo` (`proof.py:166`) truncates the undo/audit trail to `keep[-50:]`. Separate the **audit
  log** (append-only, never truncated) from the **undo stack** (bounded). Conflating them means an
  audit trail that silently loses records — which, given WS1, is the thing that would evidence a
  future fence bypass.
- Unify `check_idempotent(ttl_s=120)` and `store_idempotent`'s 600s prune into one constant.
- Write down which process owns which store. Add a migration story for `coordinator.db` beyond
  `coordinator.py:434 init_db`.

**Acceptance probes:**
```bash
# PR-8 — concurrency test: N concurrent store_idempotent writers → 0 lost records, file always valid JSON.
# PR-9 — kill -9 mid-write → file still parses (tempfile+replace).
```
**Estimate: 2–3 engineer-days.**

### WS5 — CI that is green and gating *(P1 · owner: **S**)*
**Closes A5.** Depends on **D2**.

Per §0(b), scope is now: (1) finish the diagnosis — run CI's own runner locally
(`python scripts/run_tests_parallel.py --slice 3/6`), then in a Linux container; (2) implement D2's
answer — a required `hermes-cockpit` job over the surface we own, upstream matrix advisory;
(3) **make PR-1 and PR-2 from WS1 required checks** — this is the entire point of the workstream;
(4) kill the venv split-brain: one documented interpreter, `.venv`, with `uv sync`, and delete or
clearly mark `venv/` (note the **live gateway currently runs from `venv/`** — pid 85713 — so this
requires a restart, not just a delete).

**Acceptance probe:**
```bash
# PR-10 — MUST print "success".
gh run list -w tests.yml -R chidionyema/hermes-agent -L 1 --json conclusion -q '.[0].conclusion'
# PR-11 — branch protection lists the cockpit job + the fence check as required.
```
**Estimate: 1–2 days for (2)–(4); (1) is unbounded until the container run lands.**

### WS6 — Secret containment *(P0-adjacent · owner: **S** · **never delegated**)*
**Closes F5.**

38 of 40 `subprocess` calls in `operator_shell` inherit `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MINIMAX_API_KEY`, `EXA_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`RSI_SIGNING_KEY`, `TELEGRAM_WEBHOOK_SECRET`. Add `_safe_env()` to `panel_chrome.py` — `sdlc.py:97`
already documents the pattern and the reason — then convert all 38, allow-list per call site.

**Acceptance probe:**
```bash
# PR-12 — every subprocess call in operator_shell passes env=; MUST print 40 (or a lint rule enforcing it).
```
**Estimate: 1–2 engineer-days.** Mechanical but security-sensitive: specify and review inside Claude.

### WS7 — Fork boundary *(**P**-owned · highest structural leverage)*
**Closes A1.** Depends on **D3** and its measurement.

If extension boundary: extract every `from gateway.operator_shell…` call site
(`run.py:5127`, `:5135`, `:8203`; `telegram.py:4319`, `:4367`, `:4406`, `:6378`, `:6415`, `:6541`;
`slash_commands.py:575…:4000`) behind one registration hook, then drive upstream diffs to zero.
If hard fork: vendor at a SHA, drop the remote, document the security-patch obligation.

**Acceptance probe:**
```bash
# PR-13 (extension-boundary branch) — MUST print 0.
cd ~/.hermes/hermes-agent && git diff origin/main --stat -- \
  gateway/run.py gateway/platforms/telegram.py gateway/slash_commands.py | wc -l
```
**Estimate: 1–2 weeks — HYPOTHESIS, unproven.** Replace with D3's measurement before committing.

### WS8 — Tenancy seam *(owner: **S**, execution **D**)*
**Closes A2.** Depends on **D4**. Thread `actor` through 399 signatures; one authz checkpoint at
the `handle_estate_action` entry; per-tenant scoping for the `Path.home()`-rooted panels
(`daemons.py`, `host.py`, `builds.py`, `projects.py`) designed but not implemented.
**Acceptance probe: PR-14** — count of public `operator_shell` functions accepting an actor = 399.
**Estimate: 3–5 engineer-days**, mechanical, high delegation value.

### WS9 — Coverage where the risk is *(owner: **S**, execution **D**)*
**Closes A5's coverage half.** 23 of 52 modules are referenced by no test; 7 of those shell out and
can mutate the machine. Test those 7 first. Not "raise coverage %" — cover the modules that can
change the world.
**Acceptance probe: PR-15** — never-referenced modules that contain a `subprocess` call = 0.
**Estimate: 3–4 engineer-days.**

---

## 3. Sequencing

Ordered by risk retired per day, not by workstream number.

| Wave | When | Contents | Gate to exit the wave |
|---|---|---|---|
| **0** | Today, hours | WS1 step 1 (move the guard, delete dead code); `rm .git/index.lock`; delete `rsi_control.py:94-95` | PR-1 → 0 · PR-4 green |
| **1** | Week 1 | **D1 decided.** WS1 steps 2–4 · WS6 · rest of WS2 | PR-1, PR-2, PR-3, PR-5, PR-6, PR-12 |
| **2** | Week 2 | **D2 decided.** WS5 · WS3 lint rule + top 7 modules · WS4 | PR-7, PR-8, PR-9, PR-10, PR-11 |
| **3** | Weeks 3–4 | **D3 measured and decided.** WS7 · WS1 step 5 (repo enforcement) · WS9 | PR-13, PR-15 |
| **4** | Only if productizing | **D4, D5, D6 decided.** WS8 · `Supervisor` interface · rename · legal | PR-14 |

Wave 0 is deliberately tiny and deliberately today. It converts the live, proven, three-times-fired
fence bypass from open to closed in about an hour, without waiting for D1. Everything after it is
design work that can take the time it needs — but the estate should not run another autonomous
night with the guard 26 lines too late.

---

## 4. Traceability — every audit finding has an owner and a probe

"Fully addressed" means this table has no blank cells.

| Finding | Severity | Workstream | Owner | Acceptance probe |
|---|---|---|---|---|
| F1 fenced tasks auto-closed | P0 | WS1.1–1.2 | S/**P** | PR-1 = 0 |
| F2 two divergent predicates | P0 | WS1.2–1.3 | S | PR-2 |
| F3 fence trusts self-declared intent | P0 | WS1.4 | S | PR-2 |
| F4 coding fence misses 8/8 | P0 | WS1.3–1.5 | S/**P** (D1) | PR-3 |
| F5 38/40 subprocess leak secrets | P0 | WS6 | S | PR-12 |
| F6 fabricated metrics in panel | P1 | WS2 | S | PR-5 |
| F7 🟢 ACTIVE for a runner that never ran | P1 | WS2 | S | PR-5 + cron `last_status=ok` |
| F8 config backup dead 4 days | P1 | WS2 | S | PR-4 |
| F9 91 silent swallows | P1 | WS3 | S/D | PR-7 = 0 |
| F10 non-atomic idempotency ledger | P1 | WS4 | S | PR-8, PR-9 |
| F11 `quota_honesty` fails open | P1 | WS3 | S | policy written + fence fails closed |
| F12 launchd job failing every run | P1 | WS2 | S | PR-6 (probe exits 0) |
| F13 dead docstring | P3 | WS2 | D | `handle_estate_action.__doc__ is not None` |
| A1 fork cannot track upstream | Structural | WS7 | **P** (D3) | PR-13 |
| A2 no caller identity | Structural | WS8 | **P** (D4) | PR-14 |
| A3 macOS/launchctl only | Structural | D5 | **P** | `Supervisor` iface + no new `launchctl` outside it |
| A4 three stores, no ownership | P1 | WS4 | S | ownership doc + migration path |
| A5 CI red, coverage misaligned | P1 | WS5, WS9 | S (D2) | PR-10, PR-11, PR-15 |
| UI 1–5 | P1–P3 | WS2 | S | PR-5 + visual |
| Licensing / naming | Commercial | D6 | **P** | register search + solicitor note |

---

## 5. Explicitly not in this plan

Saying what we are *not* doing is part of the plan; silent de-scoping is how the audit's F6 class
of problem starts.

- **Fixing upstream's 17k tests.** See D2. If D2 lands on option A, this plan is wrong and needs
  rewriting.
- **Any hosting/container work.** D5 defers it deliberately. The `Supervisor` interface is the only
  concession.
- **Reducing `~/.hermes` from 373MB** (`bin/uv` 51MB, `bin/tirith` 19.7MB tracked as binaries).
  Real, not urgent, and secrets are correctly excluded — verified.
- **The `signal_engine` financial-promotion question.** Flagged in the audit §6; it is a legal
  scoping question for D6's solicitor conversation, not engineering work.
- **Live Telegram BFS reachability.** The 77-action claim still rests on `test_cockpit_ia.py`
  passing, not on driving the live UI. Per the estate's own rule, that claim is **unproven** until
  the BFS probe runs against the live gateway. It is a one-session task and it should happen before
  any UI redesign, not after.

---

## 6. Risks in this plan itself

1. **Wave 0 changes drain-loop ordering in a live coordinator** (pid 46835). Moving the guard above
   `:2098` means junk-injection tasks that are also fenced now stop auto-closing — the backlog will
   grow and require manual taps. That is the correct behaviour and it will feel like a regression.
   Watch the `awaiting_approval` count for two days.
2. **PR-1 as a required check can wedge the pipeline** if the 3 historical violations are not
   backfilled first (WS1.6). Backfill before wiring the check.
3. **D3's measurement may come back ambiguous** (e.g. 400–600 lines). Set the threshold *before*
   running it — that is why the rule is written above rather than after.
4. **WS3's lint rule will surface far more than 91 sites** once it runs across `~/.hermes/scripts`
   (36,046 LOC) as well. Scope it to `operator_shell` first or it stalls.
5. **The plan assumes the audit's findings are still true.** They were measured 2026-08-05 against a
   live, self-modifying estate that commits itself hourly. Re-run the appendix probes before
   starting each wave rather than trusting this document — this document is a lead, not state.

---

## Appendix — the probe set

```bash
# PR-1  fence invariant (target 0)
sqlite3 ~/.hermes/coordinator.db "SELECT COUNT(*) FROM tasks t
  WHERE lower(COALESCE(t.risk_class,'')) IN ('money','identity','contract') AND t.status='done'
  AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='approved');"

# PR-4  estate sync freshness (target: last auto: sync commit < 6h old)
cd ~/.hermes && git log -1 --format=%ct $(git log -1 --format=%H --grep='^auto: sync')

# PR-6  canonical estate state
bash ~/.hermes/scripts/verify_estate.sh

# PR-7  silent swallows (target 0)
grep -rEc '^\s*except( Exception| BaseException)?\s*:\s*$' \
  ~/.hermes/hermes-agent/gateway/operator_shell/*.py | awk -F: '{s+=$2} END{print s}'

# PR-10 CI conclusion (target "success")
gh run list -w tests.yml -R chidionyema/hermes-agent -L 1 --json conclusion -q '.[0].conclusion'

# PR-12 subprocess env narrowing (target: all 40)
grep -rc 'env=' ~/.hermes/hermes-agent/gateway/operator_shell/*.py | awk -F: '{s+=$2} END{print s}'

# PR-13 upstream divergence (target 0 on the extension-boundary branch)
cd ~/.hermes/hermes-agent && git diff origin/main --stat -- \
  gateway/run.py gateway/platforms/telegram.py gateway/slash_commands.py | wc -l

# D3 decision measurement
cd ~/.hermes/hermes-agent && git diff 21d80ca683..HEAD --stat -- \
  gateway/run.py gateway/platforms/telegram.py gateway/slash_commands.py hermes_cli/commands.py

# Cockpit suite (note: venv/, not .venv/ — see §0(c))
cd ~/.hermes/hermes-agent && ./venv/bin/python -m pytest tests/gateway/operator_shell/ -q
```
