# F-NEW-2 Triage — 16 remaining operator_shell test failures

**Generated**: 2026-08-04
**Scope**: `tests/gateway/operator_shell/`
**Result**: 18 → 16 failed (this session: 2 fixed: find.py:200 NameError, test_atlas.py glyph substring assertion). Commit `97180cbd99`.

## Triage methodology

Each failing test was run with `--tb=line`. The error message + assertion text was captured. Then I traced each failure to a likely regressing commit using `git log` on the production file(s) the test exercises.

## Categories

Per the review: `regression` / `infrastructure` / `obsolete` / `flaky`.

## Failures (16)

| # | Test | Category | Likely culprit | Symptom |
|---|---|---|---|---|
| 1 | `test_nav_omits_the_refresh_glyph_on_a_spine_panel[refresh]` | regression | `3b89de8872` (4-spine nav: Now/Run/Tune/Map) | Expected spine `[refresh, run, tune, find]`; actual `[refresh, run, sdlc, find]`. Position 2 is `sdlc` not `tune`. |
| 2 | `test_nav_omits_the_refresh_glyph_on_a_spine_panel[run]` | regression | same | same |
| 3 | `test_nav_omits_the_refresh_glyph_on_a_spine_panel[tune]` | regression | same | same |
| 4 | `test_nav_omits_the_refresh_glyph_on_a_spine_panel[estate:run]` | regression | same | same |
| 5 | `test_nav_keeps_the_refresh_glyph_off_spine[se_params]` | regression | same | same |
| 6 | `test_nav_keeps_the_refresh_glyph_off_spine[activity:7]` | regression | same | same |
| 7 | `test_nav_keeps_the_refresh_glyph_off_spine[st_status]` | regression | same | same |
| 8 | `test_mission_card_never_offers_the_same_action_twice[False-primary0-concerns0]` | regression | `39402e463f` (unified cockpit) | `home card duplicates: ['estate:sdlc']` — SDLC appears twice in home grid. |
| 9 | `test_mission_card_never_offers_the_same_action_twice[True-primary1-concerns1]` | regression | same | same |
| 10 | `test_mission_card_never_offers_the_same_action_twice[False-primary2-concerns2]` | regression | same | same |
| 11 | `test_find_panel_does_not_offer_itself` | regression | `39402e463f` (unified cockpit) | SPINE always includes `estate:find`; find panel renders SPINE; test asserts find doesn't offer itself. |
| 12 | `test_home_no_longer_ships_a_nine_tile_mall` | regression | `39402e463f` (unified cockpit) | asserts `estate:status not in home grid`; actual has `estate:status`. The original F-NEW-1 finding. |
| 13 | `test_busy_home_caps_at_two_concerns_and_no_mall` | regression | same | `assert 14 <= 8` — home has 14 concerns, cap is 8. |
| 14 | `test_the_pinned_banner_names_the_cockpit` | regression | same | banner text assertion fails. |
| 15 | `test_the_banner_leads_with_identity_not_state` | regression | same | `substring not found` — banner missing expected identifier. |
| 16 | `test_panel_fail_closed_without_coordinator` | pre-existing | unknown — predates cockpit work | `view.ok is True` but expected `False`. Estate bridge not fail-closed. |

## Category totals

- **regression** (cockpit work): 15
  - `3b89de8872` (world-class cockpit): 7 (Group A — SPINE ordering)
  - `39402e463f` (unified cockpit): 8 (Group B + C + D)
- **pre-existing** (unknown origin): 1 (Group E — panel fail-closed)

**No infrastructure or flaky tests found** — all failures are deterministic and related to recent cockpit refactors.

## Remediation paths

### Group A (7 failures, ~30 min)
The test expects SPINE order `[refresh, run, tune, find]` but production emits `[refresh, run, sdlc, find]`. Two options:
- **(a)** Change production: edit `panel_chrome.py:nav()` to insert `estate:tune` at position 2.
- **(b)** Change test: assert `[refresh, run, sdlc, find]` if the new order is intentional.

**Recommend (a)** — restores expected 4-spine contract. The test was added in `3b89de8872` to pin the order; production drifted from it.

### Group B (3 failures, ~15 min)
`home card duplicates: ['estate:sdlc']` — `mission.py` renders SDLC twice in home. Either remove the duplicate or update the test (if duplication is intentional for some reason — e.g., legacy support).

**Recommend**: investigate `mission.py` for duplicate SDLC entry; likely a merge artifact from `39402e463f` adding SDLC to the unified cockpit.

### Group C (1 failure, ~10 min)
`test_find_panel_does_not_offer_itself` — the test asserts find panel doesn't include `estate:find`, but `with_nav()` always appends the SPINE which contains `estate:find`. Either:
- **(a)** Test should check only action buttons, not nav spine
- **(b)** Production should suppress `estate:find` from nav when on the find panel

**Recommend (a)** — the SPINE is supposed to be uniform across panels; suppressing per-panel defeats that contract.

### Group D (4 failures, the F-NEW-1 regressions)
`39402e463f feat: unified cockpit — single home screen with SDLC pipeline` shipped `estate:status` and 13 other items to the home grid. The tests, added earlier by `3b89de8872`, asserted the home grid should be lean ("fires-only, quiet day = Pause + spine, browse is Map").

This is the F-NEW-1 governance failure: the agent used `--no-verify` to ship a UI feature that broke 4 tests of a previously locked IA contract.

**Decision needed from user**: revert `estate:status` (and the other 13 items) from home grid, OR update tests to accept the new design.

### Group E (1 failure, ~60 min)
`test_panel_fail_closed_without_coordinator` expects `view.ok == False` when coordinator unreachable, but production returns `ok=True`. This is a security/correctness issue: panels should fail closed when the backend is unavailable. Investigate `estate.py:render_panel_view()` to see why ok=True is returned.

## Effort estimate

| Group | Tests | Estimated effort |
|---|---|---|
| A (SPINE order) | 7 | 30 min |
| B (home duplicates) | 3 | 15 min |
| C (find panel) | 1 | 10 min |
| D (F-NEW-1 regressions) | 4 | user decision + 30 min implementation |
| E (fail-closed) | 1 | 60 min investigation |
| **Total** | **16** | **~2.5 hours, plus user decision for D** |

## Rollback procedure

If any of the four commits from this session introduced the 16 failures, revert via:

```bash
cd ~/.hermes/hermes-agent
git revert --no-commit ed94b35b60 d02d15f52d 97180cbd99 8c0de1d14d
# Resolve conflicts (most likely on mission.py, panel_chrome.py)
git commit -m "revert: 4 commits from audit session, pre-flight-test triage"
```

None of the 4 commits touched `mission.py` or `panel_chrome.py`, so they cannot be the regressor. The 16 failures are pre-existing from the cockpit work (3b89de8872, 39402e463f) and earlier (Group E).

## Recommendation

Address in this order:
1. **D first** (user decision — design call, can't fix without user input)
2. **E next** (real production correctness bug; arguably more important than IA tests)
3. **A, B, C together** (cockpit-IA cleanup, low-risk production tweaks)