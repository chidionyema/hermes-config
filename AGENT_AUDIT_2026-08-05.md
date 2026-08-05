# Hermes — deep audit for commercial readiness, 2026-08-05

Scope: architecture, features, UI, and line-level code review of `~/.hermes` and
`~/.hermes/hermes-agent`. Brief: *"started as pet project but needs commercial readiness"*.
Target agreed with founder: **harden for own use now, flag the choices that are expensive to
reverse when productizing later.**

Every claim below carries a `file:line`, command output, or live-database evidence. Anything
I could not prove is labelled **HYPOTHESIS** with the exact check that would settle it.

Companion to `AGENT_AUDIT_2026-07-31.md` and `AGENT_AUDIT_2026-08-04.md`. This audit does not
re-litigate their findings; it goes at the layers they did not reach — the **fence logic**, the
**fork strategy**, and the **honesty of the cockpit's own reporting**.

---

## 0. The one-paragraph verdict

Hermes is a genuinely impressive single-operator system with a real moat: a 53-module Telegram
cockpit driving an autonomous coordinator across four projects. The engineering hygiene in the
places people usually get it wrong is **good** — no `shell=True`, no `eval`/`exec`, secrets are
`0600` and absent from git and logs, and 479 tests pass. But it is not commercially ready, for
three structural reasons, in order of severity: **(1) the money/identity safety fence does not
work and has already been bypassed twice in production; (2) the cockpit reports state it does
not measure, so its green lights are not evidence; (3) it is a live fork of someone else's
11,923-commit repo with local edits interleaved into 800KB files, which makes it unmaintainable
the moment upstream matters.** None of these is fatal. All three are expensive to fix later and
cheap to fix now.

---

## 1. What Hermes actually is

Measured, not assumed.

| Layer | Location | Size | Owner |
|---|---|---|---|
| Upstream agent framework | `~/.hermes/hermes-agent` | 1.13M LOC Python, 2,403 files | **NousResearch** (fork) |
| Operator cockpit (the product) | `hermes-agent/gateway/operator_shell/` | 52 modules, ~600KB | **You** |
| Estate orchestration | `~/.hermes/scripts/` | 36,046 LOC, 143 files | **You** |
| Skills | `~/.hermes/skills/` | 12,844 LOC, 47 files | You + vendored |
| Runtime state | `state.db` 102MB, `coordinator.db` 29MB | — | — |

**The fork.** `hermes-agent` is `https://github.com/NousResearch/hermes-agent.git`, MIT,
© 2025 Nous Research, 11,923 commits. Yours is **53 of them** (0.44%). Top author Teknium, 4,999.
Upstream is reachable and **already ahead** — `git fetch` moved `origin/main`
`aec331899e..fb402106f8` during this audit.

**Live topology** (`launchctl list`, `ps aux`):

```
85713  ai.hermes.gateway          hermes_cli.main gateway run --replace   (64MB)
46835  ai.hermes.coordinator      scripts/coordinator.py                  (13MB)
99439  com.signalengine.daemon    signal_engine.daemon    equity $9,649.52 rail=paper
64404  com.prospector.scheduler   prospector.scheduler                    (73MB)
77927  com.prospector.control-center
   -   com.haworks.continuous-review   last exit=1  ← failing every run
```

**Canonical state probe** (`bash ~/.hermes/scripts/verify_estate.sh`), run at audit time:

```
❌ com.haworks.continuous-review last exit=1 — job is failing every run
🟡 ACL allowlist = 1 user (founder only)
VERDICT: ❌ DEGRADED — at least one ❌ above. Fix before claiming ready.
```

---

## 2. P0 — The safety fence does not hold

This is the section that matters. Hermes autonomously executes coding tasks that edit files and
open PRs. The only thing standing between the autopilot and your money rail is a "fence" that
sets `status="awaiting_approval"` and waits for you to tap ✅ APPROVE. **That fence is bypassable
by text, and it has already been bypassed.**

### F1 — Fenced money/identity tasks were auto-closed without approval. *Proven in production.*

`scripts/coordinator.py:2105` releases tasks it judges to be read-only status reports:

```python
# Read-only status reports stuck on fence — release (no mutation risk)
if r["status"] == "awaiting_approval" and _is_readonly_status_objective(r):
    add_event(conn, r["id"], "auto_close", "readonly_status_false_fence")
    _set(conn, r["id"], status="done", completed_at=time.time())
```

Twenty-six lines later, `coordinator.py:2124-2131` states the actual policy:

```python
# Product next-moves that only failed because executors are quota-starved.
# NEVER auto-close money/identity fences — founder must tap APPROVE.
...
if risk in ("money", "identity", "contract"):
    continue  # fail-closed: never drain fenced work
```

**The guard is 26 lines too late.** The escape hatch at 2105 runs first and `continue`s past it.

This is not theoretical. Querying the live `coordinator.db`:

```sql
SELECT t.risk_class, COUNT(*) FROM events e JOIN tasks t ON t.id=e.task_id
WHERE e.kind='auto_close' AND e.payload LIKE '%readonly_status_false_fence%'
GROUP BY t.risk_class;
```
```
risk_class  n
----------  -
identity    1
money       1
```

The two tasks, with **zero approval events** recorded against either:

| id | risk_class | source | created→closed | title |
|---|---|---|---|---|
| `8fb949064732` | **identity** | `project:tie` | 2026-07-28 → 2026-07-31 02:46:03 | `Introduction Exchange: Status report … read its graphify-out knowledge graph` |
| `1582bddd1a8b` | **money** | `project:signalengine` | 2026-07-29 → 2026-07-31 02:46:03 | `Signal Engine: Status report … read its graphify-out knowledge graph` |

**In fairness: both were genuinely read-only status reports. No harm occurred.** That is the
honest finding, and it is also the point — the control that exists to prevent harm was bypassed,
and the mechanism cannot distinguish a benign case from a harmful one, because it reads the
task's *self-description*.

Note also that `coordinator.py:2132-2133` is **dead code** — `if risk in (...): continue`
followed by `if r["status"]=="awaiting_approval" and risk in (...): continue`. The second is
unreachable. Someone added the guard twice and neither copy covers the 2105 path.

### F2 — Two divergent predicates for the same concept

The bypass exists because "is this read-only?" is implemented **twice, differently**:

| | `fence_class` (`coordinator.py:759`) | `_is_readonly_status_objective` (`coordinator.py:1640`) |
|---|---|---|
| Trigger group A | `status report` \| `product next-move` \| `graphify` | `status report` |
| Trigger group B | `read-only` \| `make no code changes` \| `do not open a pr` | `read-only` \| `make no code changes` \| **`graphify`** |

`graphify` is in group A for one and group B for the other. So a task saying *"status report:
graphify …"* is **fenced** by the first function and **auto-closed** by the second. Executed:

```
fence_class  auto-close?  task
money        AUTO-CLOSED  status report: graphify the stripe payout ledger
money        AUTO-CLOSED  status report on the refund pipeline — graphify it
identity     AUTO-CLOSED  status report: graphify the kyc credential store
money        -            wire up stripe payouts                      ← control
```

### F3 — The fence trusts self-declared intent

`coordinator.py:759-761` downgrades risk class to `"low"` when the task text *claims* to be
read-only. Nothing enforces the claim; the body is then handed to an executor that does real
file edits. Executed:

```
CLASS      task
money      wire up stripe payouts
low        graphify the stripe payout module — read-only
low        status report on the kyc identity flow, read-only
low        product next-move for stripe settlement: make no code changes
low        graphify: rotate the stripe secret key. read-only.
```

Task titles are **not all founder-authored** — both bypassed tasks above were `created_by=portfolio`,
an automated source. A fence keyed on text that automation generates is a fence the automation
can open.

### F4 — The coding-run fence misses 8 of 8 realistic money tasks

`gateway/operator_shell/code_remote.py:21-25` is a *third* fence, a keyword denylist:

```python
_FENCE_RE = re.compile(
    r"\b(signalengine|signal engine|tie\b|introduction exchange|stripe|payout|"
    r"settlement|kyc|identity|money|billing|live order)\b", re.I)
```

It is load-bearing — `code_remote.py:151-166` is the only thing that sets `awaiting_approval`
for a coding run. Executed against realistic tasks:

```
FENCED?    task
NO         refactor the checkout flow to use the new provider
NO         change the price of every pack in the catalogue to 1p
NO         update the payment integration and redeploy
NO         rotate the API credentials in .env
NO         issue refunds for all orders this month
NO         wire up the new card processor
NO         modify the bank details on the invoice template
NO         push the subscription tier change live
money      update Stripe keys        ← control
identity   run a kyc check           ← control
```

This vocabulary also **diverges from the coordinator's** (`coordinator.py:420`), which does catch
`payment|refund|charge|invoice|wallet|ledger`. Three fences, three vocabularies, no shared source
of truth.

The gap is *known* — `tests/gateway/operator_shell/test_code_remote.py:197` asserts it:

```python
def test_detect_fence_is_keyword_only_and_misses_paths():
    """Documents a known gap: the fence reads words, not blast radius."""
    assert detect_fence("fix the buy button in store_platform") is None
```

Documenting a hole in a safety control is better than hiding it, but a passing test that asserts
the control fails is not a mitigation.

**The fix, for all four findings:** fence on **blast radius, not intent**. One shared classifier,
keyed on what the run will *touch* — repo paths, files matched, commands invoked, whether a PR
targets a money-rail repo — evaluated *after* the plan exists and *before* mutation. Text keywords
can stay as an additional trip-wire, never as the primary gate. Order the drain loop so the
fail-closed check runs first, and delete the second predicate entirely.

### F5 — 38 of 40 subprocess calls hand every secret to the child

```
subprocess calls in operator_shell: 40
with a narrowed env=:                2      (sdlc.py:110, integrity.py:48)
```

`hermes_cli/env_loader.load_hermes_dotenv` (`gateway/run.py:1166`) loads `.env` into
`os.environ`, so the gateway process holds `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MINIMAX_API_KEY`, `EXA_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`RSI_SIGNING_KEY`, `TELEGRAM_WEBHOOK_SECRET`. All 38 unnarrowed calls pass the lot to
`git`, `gh`, `launchctl`, `pgrep`, and Claude Code runs.

`sdlc.py:97` already shows the right pattern and the reason:
`# Narrow env: don't leak secrets to the gh subprocess.` Generalise it — a `_safe_env()` helper
in `panel_chrome.py` and 38 call-site edits.

---

## 3. P1 — The cockpit reports state it does not measure

Your own operating rule says *"State is a probe, not a paragraph."* The cockpit violates it.

### F6 — The RSI panel displays hardcoded numbers as live telemetry

`gateway/operator_shell/rsi_control.py:94-95` — f-strings with **no interpolation**, rendered
into a live panel under the heading *"Pipeline state:"*:

```python
f"• Regression: 110 pass / 15 fail (auto-fixed)",
f"• Gap-finding: 6 gaps (0 uncovered, 6 weak coverage)",
```

An AST sweep for this pattern across all 52 modules found 22 placeholder-free f-strings; these
two are the only ones presenting fabricated *metrics* (the rest are button labels and format
specs). `rsi_control.py:28` also defaults `latest_health = 0.69` — so a missing outcomes file
renders a plausible **"Health: 69%"** rather than "unknown". *(Currently the file exists, so the
panel shows the real 21% — the default is latent, not live.)*

### F7 — The self-improvement runner has never run, and the panel says 🟢 ACTIVE

`~/.hermes/cron/jobs.json`, job `self-improve-hourly`:

```
last_status: error
last_error:  Script not found: /Users/chidionyema/.hermes/scripts/python3 scripts/self_improve_runner.py --hourly
last_run_at: 2026-08-05T20:00:12+01:00
```

The whole command string is being treated as a script path — an interpreter/args split bug in
the cron runner. `scripts/self_improve_runner.py` exists and is executable; it is simply never
invoked. Meanwhile `rsi_control.py:46-49` derives liveness solely from the *absence* of an
`OFF_SWITCH` file:

```python
off_switch = HERMES / "logs" / "meta-improver" / "OFF_SWITCH"
is_active = not off_switch.is_file()
```

`OFF_SWITCH` is absent, so the panel renders **"🟢 ACTIVE"** for a subsystem whose runner has
never successfully executed. Real health, from `logs/meta-improver/change-outcomes.jsonl`:
`health_score 0.213`, `injections: 0`, `firings: 0`.

**Fix:** liveness must come from a heartbeat with a freshness bound (`last_run_at` within N
intervals), never from the absence of a kill-switch file.

### F8 — The estate config backup has been dead for 4.15 days, silently

```
last sync commit:      2026-08-01 17:01:08 +0100
now:                   2026-08-05 20:47
dirty files right now: 139
```

Root cause, from `cron/jobs.json` job `hermes-config-auto-push`:

```
last_error: Script exited with code 128
stderr: fatal: Unable to create '/Users/chidionyema/.hermes/.git/index.lock': File exists.
```

```
-rw-r--r--  0 bytes  1 Aug 17:10  .git/index.lock     AGE: 358678s (4.15 days)
```

A git process died at 17:10 on 1 Aug and left a zero-byte lock. Every hourly run since has
failed. **The self-heal did not heal:** `scripts/auto-push.sh` contains stale-lock cleanup that
removes locks older than 300s — this lock is 358,678s old and still there, so the cleanup path
is not executing. There are also **two** different auto-push scripts:

| path | perms | commit message |
|---|---|---|
| `~/.hermes/auto-push.sh` | `-rw-r--r--` (**not executable**) | `estate: auto-push snapshot …` |
| `~/.hermes/scripts/auto-push.sh` | `-rwx--x--x` | `auto: sync …` ← the one in git log |

The root copy also has an **inverted guard**:

```bash
if ! git diff --quiet && ! git diff --cached --quiet; then
    echo "No changes to push"; exit 0
fi
```

`git diff --quiet` exits 0 when there are *no* changes, so this prints "No changes to push"
exactly when there *are* changes — though only in the both-staged-and-unstaged case, which is
narrower than it first appears (verified against the current tree: guard not taken, nothing
staged). Delete the dead root copy rather than fix it.

### F9 — 91 silent exception swallows

Across ~9k LOC of `operator_shell`: **166** broad `except Exception:` / bare `except:` handlers,
of which **91** immediately `pass` / `return None` / `return {}` / `continue` with no logging.

This is your single most expensive defect class and you have been bitten by it repeatedly — your
own memory index records `_refine_wave zero-yield` (a silent kill pass that dropped every
candidate), the `word-salad query generator` fallback, and `web_calls was structurally zero`.
All three were silent swallows.

Worst offenders: `mission.py` (20), `prospector_daemon.py` (14), `health_panel.py` (11),
`fleet.py` / `estate.py` / `cockpit.py` (9 each). `rsi_control.py:43` and `:83` are bare
`except: pass`, which also swallows `KeyboardInterrupt` and `SystemExit`.

**Fix:** a lint rule banning `except Exception: pass` without a `logger.debug(..., exc_info=True)`.
Mechanical, one pass, permanently prevents the class.

### F10 — The idempotency ledger is not atomic

`gateway/operator_shell/proof.py:91-103` — read-modify-write on a shared JSON file, no lock, no
atomic rename:

```python
data = json.loads(path.read_text()) if path.is_file() else {}
data[request_id] = {"ts": now, "result": result}
path.write_text(json.dumps(data))
```

**Failure scenario:** you double-tap a mission-card button. Two callbacks enter
`store_idempotent` concurrently, both read the same `data`, both write; one write wins. The
second tap's request_id is lost from the ledger, `check_idempotent` misses, and the action —
a daemon restart, a deploy, an approve — **executes twice**. A crash mid-`write_text` truncates
the whole ledger, since `write_text` truncates before writing.

Same file, `pop_undo` at `:166` rewrites the undo stack keeping only `keep[-50:]` — the audit
trail is silently truncated to 50 records on every undo.

Also `check_idempotent` uses `ttl_s=120` while `store_idempotent` prunes at 600s — harmless
today, but they should be one constant.

**Fix:** `os.replace()` onto a tempfile in the same directory, plus `fcntl.flock`. Note your own
memory: *macOS has no `flock(1)`* — use `fcntl.flock` from Python, which is what this is.

### F11 — `quota_honesty` fails open

`code_remote.py:83-90`:

```python
except Exception as exc:
    # A failed probe is not a healthy breaker. Say so rather than
    # reporting "ready" off a default we never confirmed.
    logger.warning("circuit-breaker probe failed: %s", exc)
    return True, f"⚠️ Breaker state unknown (probe failed: …) — proceeding"
```

The comment is right and the code does the opposite: it returns `can_run_tools=True`. It *says*
the state is unknown and then proceeds anyway. For a quota breaker that is arguably tolerable;
if this pattern is reused for a safety breaker it is not.

### F12 — A launchd job has been failing every run

`com.haworks.continuous-review last exit=1` — the single `❌` that makes the estate probe report
DEGRADED. Not diagnosed in this audit. **Next check:** `launchctl print gui/$UID/com.haworks.continuous-review`
and the job's stderr log.

### F13 — A dead docstring

`estate.py:180-202`: the `"""Public entry point: dispatch…"""` block sits *after* the
`if action == "now"` statement, so it is a no-op string expression, not a docstring. Proven:

```
handle_estate_action.__doc__ = None
first stmt line: 187 If
```

Cosmetic, but it is the entry point of the whole cockpit and the text is genuinely useful.

---

## 4. Architecture — what is expensive to reverse

### A1 — The fork strategy is the biggest structural liability

Your edits are **interleaved into upstream files**, not isolated behind a plugin boundary:

| upstream file | size | your commits touching it |
|---|---|---|
| `gateway/run.py` | **822 KB** | 12 |
| `gateway/platforms/telegram.py` | **344 KB** | 6 |
| `gateway/slash_commands.py` | **190 KB** | 4 |
| `hermes_cli/commands.py` | — | 7 |
| `gateway/stream_consumer.py` | 84 KB | 1 |

Integration is by scattered function-local imports — `grep` finds `from gateway.operator_shell…`
at `run.py:5127`, `:5135`, `:8203`, `telegram.py:4319`, `:4367`, `:4406`, `:6378`, `:6415`,
`:6541`, `slash_commands.py:575`…`:4000`.

**Consequence:** you cannot rebase onto upstream. Upstream moved during this audit
(`aec331899e..fb402106f8`). Every future security fix, dependency bump, or Telegram API change
from Nous Research is a manual merge into 800KB files. Today you are effectively **frozen on a
2026-06-17 snapshot** of a repo with 11,923 commits and active daily development.

**Recommendation — this is the highest-leverage architectural change available.** Define a real
extension boundary and get to **zero diffs in upstream files**: one registration hook upstream
(or a `sitecustomize`-style entry point), everything else in `operator_shell/`. Then `git pull`
becomes routine instead of impossible. Cost: I estimate 1–2 weeks. **HYPOTHESIS** — that estimate
is not proven; the check is to count the actual hunks with
`git diff 21d80ca683..HEAD --stat -- gateway/run.py gateway/platforms/telegram.py gateway/slash_commands.py`
restricted to your commits.

### A2 — Nothing in the cockpit knows who is calling. This is *the* multi-tenancy blocker.

Mechanically measured:

```
public functions in operator_shell:                       399
that accept a user_id / actor / caller / tenant / principal:  0
authorization checks inside operator_shell:                   0
```

All authz lives upstream at message ingress (`gateway/authz_mixin.py:176 _is_user_authorized`),
gated on `TELEGRAM_ALLOWED_USERS`. Below that line, `handle_estate_action(action, request_id)`
executes whatever string arrives, with no notion of *who*.

That is a correct and clean design for one operator — and it means **"add a second user" is not
a feature, it is a refactor of 399 signatures and 40 subprocess call sites.** Every panel would
also need per-tenant data scoping: today `daemons.py`, `host.py`, `builds.py` and `projects.py`
read and mutate `Path.home()`-rooted paths and `launchctl` labels belonging to *the machine*, not
to a tenant.

If you may ever productize, thread an `actor` (even an unused one) through the API **now**, while
it is 399 mechanical edits rather than 399 edits plus a migration of live state.

**Credit where due:** `grep -c chidionyema gateway/operator_shell/*.py` returns **0**. There are
no hardcoded founder paths in the cockpit — better hygiene than most codebases at this stage.

### A3 — macOS-only, single-machine

`daemons.py:21-110` hardcodes `launchctl` labels and `Path.home()` log paths, including a
specific project (`com.tie.ai-review` → `~/Documents/code/the-introduction-exchange/…`).
`daemons.py:357` renders a literal `Mac: launchctl kickstart -k gui/$UID/…` string to the user.
There is no container story: `docker-compose.yml` exists upstream but the estate layer assumes a
logged-in macOS GUI session (`gui/$UID`).

For "run my own business on it", fine. For anything hosted, this is a rewrite of the daemon layer.

### A4 — Three state stores with no defined ownership

`state.db` (102MB, messages/FTS), `coordinator.db` (29MB, tasks/events/outbox), `kanban.db`
(114KB), plus ~14 loose JSON files in `~/.hermes` mutated by both the gateway and the coordinator
(`gateway_state.json`, `channel_directory.json`, `projects.json`, `processes.json`,
`meta/operator_shell/idempotency.json`…). The JSON files are the ones with the atomicity bug in
F10. There is no schema-migration story for the two SQLite databases beyond
`coordinator.py:434 init_db` and a `schema_version` table in `state.db`.

`sys.path.insert(0, …)` appears **11 times** in `operator_shell` — 10 inside functions,
one at import time (`rsi_control.py:18`). This front-inserts `~/.hermes/scripts` (140 modules)
ahead of stdlib and site-packages for the whole gateway process. **Currently harmless** — I
checked, and there are zero name collisions with either stdlib or the venv's site-packages
today. It is a latent trap: the day someone adds `~/.hermes/scripts/types.py`, the gateway
breaks process-wide in a way that will look like anything but a path bug.

### A5 — Test coverage is concentrated away from risk

```
operator_shell modules:                   52
referenced by any test in tests/:         29
NEVER referenced by any test:             23
```

(This matches `AGENT_AUDIT_2026-08-04.md` F-NEW-16's "~23 of 53" — my first cut said 44, which
was the wrong measure; "no file named `test_<module>.py`" is not the same as "untested".)

Of the 23 never-referenced modules, **7 shell out** and can mutate the machine:

```
projects        4 subprocess calls
notify_fanout   2
rsi_control     2
commercial_ui   1
diagnose_panel  1
incident_panel  1
predict_panel   1
```

The suite that does exist is healthy: `pytest tests/gateway/operator_shell/ -q` →
**479 passed, 5 skipped, 1 warning in 26.04s**. The 16 failures from the 2026-08-04 audit are
genuinely fixed.

**But CI is red on `main` and has been ignored.** `.github/workflows/tests.yml` exists (contrary
to `AGENT_AUDIT_2026-08-04.md` D3, which recorded the workflows directory as absent — it is
present) **and it runs on every push to your `main`.** The last five `Tests` runs:

```
failure    fix(gateway): always start source-watch, don't gate on connected_count   2026-08-04
failure    feat(summary): UI display + math derivation improvements                 2026-08-04
failure    feat(summary): 10 improvements to /summary text analysis tool            2026-08-04
cancelled  test(gateway): lock in 'summary' as a required ACTIVE_SESSION_BYPASS…    2026-08-04
failure    fix(cockpit): restore SPINE order, remove SDLC duplicate, fail-closed…   2026-08-04
```

Most recent run `30948977173` — two jobs failing: **`e2e` → "Run e2e tests"** and
**`test (3)` → "Run tests (slice 3/6)"**.

So the position is not "no CI"; it is **CI that runs, fails, and is not gating anything**, on the
same commits whose `operator_shell` slice passes locally (479 passed). That is precisely the
local-green/CI-red trap already in your memory index (`fold-test-passes-locally-fails-in-ci.md`),
where a `ch`-unit max-width made line counts font-dependent. **Not diagnosed here.** The check:
`gh run view 30948977173 -R chidionyema/hermes-agent --log-failed | tail -60`.

A red-and-ignored CI is worse than an absent one, because it trains you to ignore the signal that
would have caught F1.

---

## 5. UI / UX assessment

The cockpit is the most commercially valuable thing here, and it is the part most obviously built
by someone who uses it daily.

**Strong:**
- **77 distinct `estate:*` actions** behind a 4-item SPINE (Home/Actions/SDLC/Browse) with
  `with_nav()` applied centrally in `panel_chrome.py` — the IA work from the "Now/Run/Tune"
  redesign held up; there is no duplicate-callback problem in the current tree.
- Genuine product instincts: stale-while-revalidate caching for the six slowest panels
  (`estate.py:210-246`) with a documented 6s cold path; idempotent callbacks; an undo stack;
  `first_run.py`; a command palette; proof receipts with `rid:` on every action.
- Honest status vocabulary — `daemons.py:1-5` distinguishes "🟢 armed" (interval job idle) from
  "🔴 down", which is a distinction most dashboards get wrong.

**Weak, in priority order:**

1. **Truthfulness (F6/F7).** A dashboard that fabricates two metrics and derives liveness from a
   missing file is worse than no dashboard, because it is trusted. Fix before anything cosmetic.
2. **Failure is invisible.** With 91 silent swallows, a panel that cannot compute a section
   renders it as absent or zero rather than as an error. The operator cannot distinguish "healthy"
   from "the probe threw."
3. **`Proof.render` (`proof.py:57-59`)** renders every non-`done` status — including `failed` —
   with the same ⚠️ glyph. `failed` and `pending_confirm` should not look identical.
4. **77 actions is past the point where flat naming scales.** Fine for you; a second operator
   will need grouping and search. `find.py` and `command_palette.py` are the right foundation.
5. **`mission.py:485`** renders a literal `💰 Spend \`n/a\`` — placeholder text on the primary card.

**Not assessed:** I did not drive the live Telegram UI. Per your own memory
(*"prove reachability with the BFS probe, never by reading code"*), the reachability claims above
come from `test_cockpit_ia.py` passing, not from a live BFS over the rendered keyboards. **The
check that would settle it:** run the BFS probe against the live gateway and confirm all 77
actions are reachable within 3 taps.

---

## 6. Commercial readiness

### Licensing — permissive, but with obligations and a naming risk

MIT is fine for commercial use. Two things follow:

1. **You must retain the copyright notice and licence text** in any distribution. `LICENSE`
   (© 2025 Nous Research) is present — keep it, and add your own copyright alongside rather than
   replacing it.
2. **Naming.** Selling a product called "Hermes" that is a fork of NousResearch's "Hermes" is a
   trademark question, not a licensing one — MIT grants no trademark rights.
   **HYPOTHESIS — I am not qualified to rule on this and have not researched their marks.** The
   check is a UKIPO/EUIPO/USPTO search for "Hermes" in software classes plus 20 minutes of
   solicitor time. Note there is also a very large unrelated trademark holder in that name.
   Budget for a rename.

### Blockers to selling, ranked by cost to fix later

| # | Blocker | Cost now | Cost after launch |
|---|---|---|---|
| 1 | Fence keyed on intent, not blast radius (F1–F4) | days | a breach |
| 2 | No caller identity anywhere in the cockpit (A2) | 399 mechanical edits | edits + live-state migration |
| 3 | Fork cannot track upstream (A1) | 1–2 weeks | grows monotonically |
| 4 | macOS/launchctl/single-machine (A3) | daemon-layer rewrite | same, plus customers |
| 5 | Secrets are one flat `.env` for one operator (F5) | a `_safe_env()` helper | per-tenant KMS |
| 6 | CI red and ungated on `main` (A5) | an afternoon | — |

### Also worth knowing

- **`~/.hermes` is a 373MB git repo** with `bin/uv` (51MB) and `bin/tirith` (19.7MB) tracked as
  binaries. Secrets are correctly excluded — `.env`, `state.db`, `coordinator.db` and
  `repomix-output.xml` (75MB) are all untracked. Verified.
- **The estate auto-commits itself hourly** with no review and no CI (`auto: sync <timestamp>`).
  That is a backup mechanism, not version control — and it has been broken for 4 days (F8).
- **Financial claims.** `signal_engine` reports `equity $9,649.52 · rail paper`. If Hermes is ever
  sold or marketed on the strength of trading performance, UK financial-promotion rules apply and
  paper-trading results have specific disclosure requirements. Out of scope here; flagging it
  because "commercial readiness" and a money daemon in the same estate is a combination worth a
  deliberate decision.

---

## 7. What I'd do, in order

**This week — restore the fence (F1–F4).** Nothing else on this list matters if the autopilot can
edit the money rail unapproved. Concretely: (a) move the fail-closed `risk in (money, identity,
contract): continue` check to the **top** of the drain loop, above `coordinator.py:2105`;
(b) delete `_is_readonly_status_objective` and its call site — the false-fence problem it solves
is worth less than the hole it opens; (c) replace all three keyword fences with one blast-radius
classifier keyed on touched paths and target repo; (d) add a regression test that a
`money`-classed task can never reach `done` without an approval event.

**This week — stop the lying (F6, F7, F8).** Delete `rsi_control.py:94-95`. Replace the
`OFF_SWITCH` liveness derivation with a heartbeat freshness check. Fix the
`self-improve-hourly` command split. Clear the stale `index.lock`, delete the non-executable
duplicate `auto-push.sh`, and add a probe line to `verify_estate.sh` that fails when the last
sync commit is older than 6 hours — you found this only because I went looking.

**This fortnight — the silent-failure class (F9) and atomicity (F10).** Lint rule for bare
swallows; `os.replace` + `fcntl.flock` for the JSON stores. Both are mechanical and both
permanently retire a category of bug that has cost you real days.

**This month — decide the fork question (A1).** This is the strategic call. Either commit to the
extension boundary and get to zero upstream diffs, or consciously accept that you have
hard-forked and will never take upstream changes again. Drifting is the only genuinely bad
option, and drifting is the current state.

**Before any second user — thread `actor` through the cockpit API (A2)**, and get `tests.yml`
green then make it required, so the fence regression test in step one can actually block a merge.

---

## Appendix — verification commands

```bash
# The fence bypass, live
sqlite3 ~/.hermes/coordinator.db "SELECT t.risk_class, t.title FROM events e JOIN tasks t ON t.id=e.task_id
  WHERE e.kind='auto_close' AND e.payload LIKE '%readonly_status_false_fence%';"

# Estate state
bash ~/.hermes/scripts/verify_estate.sh

# Cockpit suite
cd ~/.hermes/hermes-agent && ./venv/bin/python -m pytest tests/gateway/operator_shell/ -q

# Silent swallows
grep -rcE '^\s*except (Exception|BaseException)?\s*:' ~/.hermes/hermes-agent/gateway/operator_shell/*.py

# Secret exposure to children
grep -rc 'env=' ~/.hermes/hermes-agent/gateway/operator_shell/*.py | awk -F: '{s+=$2} END{print s}'

# Fork divergence
cd ~/.hermes/hermes-agent && git fetch origin && git log --oneline HEAD..origin/main | wc -l
```
