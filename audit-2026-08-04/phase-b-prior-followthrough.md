# Phase B — Prior-Audit Follow-Through

Baseline: `~/.hermes/AGENT_AUDIT_2026-07-31.md` (4 days old).

## Decisions-needed checklist

| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Restart coordinator (F7 not live) | ✅ Done | `ps -p 83464` returns no row; `launchctl list` shows `1002 0 ai.hermes.coordinator` (different PID, different uptime). F7 fix is live. |
| D2 | Review/commit 6 dirty operator_shell files | ⚠️ Regressed | `git status` is clean NOW, but `integrity.py` is logging **5 NEW untracked modules**: `commercial_ui.py, discovery.py, health_panel.py, projects.py, rsi_control.py`. Old set was committed in `4e24cea1e9 fix: add untracked operator_shell modules for integrity check`, but the same anti-pattern has recurred. |
| D3 | Enable `tests.yml` on fork, trigger on push | ❌ Not done | `ls .github/workflows/` returns empty (directory does not exist). Fork's default branch is still `backup-2026-06-20`; current work is on `main` (local) and `remotes/backup/main` (pushed). |
| D4 | Tier-2 extraction to `chidionyema/hermes-operator` | ✅ Done | `gh repo view chidionyema/hermes-operator` returns a repo with description "Operator shell for Hermes: Telegram-driven estate ops, daemon control, remote coding. Extracted from hermes-agent." **But:** `gateway/operator_shell/` is still present in `hermes-agent`. Extraction is incomplete — code is duplicated, not removed from source. |
| D5 | Push `77fe5fa616` and follow-on commits | ⚠️ Partial | `77fe5fa616` is on `main`, `remotes/backup/main`, `remotes/backup/operator-shell-20260731`. BUT `git log @{u}..HEAD` shows **10 unpushed commits** on local main (top: `d03557ff91 fix(gateway): allow /summary mid-turn`). Work done since the audit is local-only. |

## Prior-audit finding status

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F1 | Untracked, unreviewed code w/ launchctl bootout powers | ⚠️ **Recurring** | `errors.log:2026-08-04 01:01:11 ERROR gateway.operator_shell.integrity: ... running UNREVIEWED code: commercial_ui.py, discovery.py, health_panel.py, projects.py, rsi_control.py`. The fence is **firing** — that's the good news. The bad news: same anti-pattern 4 days later. `HERMES_STRICT_TRACKED_IMPORTS=1` is NOT set, so it warns rather than denies. |
| F2 | Test suite shipped red, invisibly | ❌ **Regressed — RED AGAIN** | `pytest tests/gateway/operator_shell/`: `18 failed, 383 passed, 5 skipped in 24.14s`. Failures are in `test_cockpit_activity.py`, `test_cockpit_ia.py`, `test_find.py`, `test_operator_shell.py`. The pre-commit TEST GATE either (a) does not cover these tests, (b) was bypassed, or (c) the suite regressed after the gate was authored. |
| F3 | `dict.fromkeys(paths)[:4]` crash on 12% of tasks | ✅ Fixed | `grep -nE 'dict\.fromkeys.*\[' code_remote.py coordinator.py` → no matches. Both copies replaced. |
| F4 | Tests covered 19% of operator_shell (11 tests) | ⚠️ Slightly improved, still poor | `pytest --collect-only tests/gateway/operator_shell/`: **406 tests collected** (vs. 11 in 2026-07-31 audit, 58 after that audit). So now **403 tests** (delta = ~348 since original audit). But this may be inflated by upstream `NousResearch/hermes-agent` tests being collected too — needs disambiguation. |
| F5 | 74 broad `except`, 20 silently swallowing | ⚠️ Mostly unaddressed | 2026-07-31 audit fixed one instance (`code_remote.py:79-82`). Sweep of remaining 73 is "not mechanical — each needs judgement". Not yet done. |
| F6 | Monorepo tax (1.6 GB `.git`, 403 on push) | ⚠️ Mitigated, not solved | Origin still `NousResearch/hermes-agent`, still 403s. Backup remote still works. D4 (Tier-2 extraction) reduces but doesn't eliminate: extraction is partial (code still in `hermes-agent/gateway/operator_shell/`). |
| F7 | `sqlite3.Row.get()` crash-loop on `code:` tasks | ✅ Fixed and live | `grep -n 'r\.get(' coordinator.py` → no matches. Coordinator restarted (D1), so fix is in the running process. |

## New findings raised by Phase B

### B-1 (HIGH) — Test suite is RED; gate is failing
- 18 failures in `tests/gateway/operator_shell/`. Specific classes:
  - `test_cockpit_activity.py::test_mission_card_never_offers_the_same_action_twice` (×2)
  - `test_cockpit_ia.py::test_home_no_longer_ships_a_nine_tile_mall`
  - `test_cockpit_ia.py::test_busy_home_caps_at_two_concerns_and_no_mall`
  - `test_cockpit_ia.py::test_the_pinned_banner_names_the_cockpit`
  - `test_cockpit_ia.py::test_the_banner_leads_with_identity_not_state`
  - `test_find.py::test_render_find_with_no_match_says_so`
  - `test_operator_shell.py::test_panel_fail_closed_without_coordinator`
  - … and 10 more
- The pre-commit hook is dated 2026-07-31 08:39 — present, but its TEST GATE may not cover these new tests or may have been bypassed.
- This is the F2 anti-pattern repeating. Investigation needed: read `pre-commit` to see what it actually gates.

### B-2 (MEDIUM) — Tier-2 extraction is partial; code duplicated
- `chidionyema/hermes-operator` repo exists.
- `gateway/operator_shell/` is **still present** in `hermes-agent/`.
- Either extraction imported the code into hermes-operator without removing it from hermes-agent (duplication drift), or extraction is a different surface (not operator_shell). Need to check what hermes-operator actually contains.

### B-3 (MEDIUM) — 10 commits unpushed to backup remote
- `git log @{u}..HEAD`: 10 commits including `d03557ff91 fix(gateway): allow /summary mid-turn` — most recent. None of the 2026-07-31 audit's "Changes landed" table is on backup remote.
- Risk: laptop dies, work is gone.

### B-4 (LOW) — `ghost_imports` fence firing every restart
- `errors.log` shows the same 5-file warning has fired at least twice (2026-08-03 23:40 and 2026-08-04 01:01). Means the gateway has restarted at least twice since then.
- Either the gateway is being restarted and re-warns on boot (acceptable), or the warning is repeating within a single session (would indicate the integrity check runs more than once — check).