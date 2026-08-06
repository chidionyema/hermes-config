# Prospector — next ship item (2026-08-06)

Source: live inspection of `~/Documents/code/prospector` (branch `fix/durable-ledger-fence`,
HEAD `5cacaa1`). Read-only — no code changed, no PR opened.

Supersedes the 2026-07-31 entry in this file: that report's target
(`tests/test_engine_bridge.py` Stripe-provisioner failures, 4 fails at HEAD `b21a3ca`) is now
**resolved** — re-run live today: `python -m pytest tests/test_engine_bridge.py -q` → `17 passed`,
0 failed. That work already shipped somewhere in the 2026-07-31→2026-08-06 history; this report
replaces it with the current highest-leverage item.

## Finding

The working tree already contains a **complete, tested, uncommitted fix** for a live storefront
defect, sitting unshipped:

- `git status --short` (in `~/Documents/code/prospector`) shows modified: `prospector/bridge.py`,
  `prospector/plain_text.py`, `tests/unit/test_plain_text_storefront.py`,
  `tools/backfill_listing_copy.py`, plus 6 `store_platform/src/Store.Web` files, and 2 new
  untracked files (`src/lib/copy.ts`, `src/lib/searchEvent.ts`).
- The defect (documented in the new `copy.ts` header, measured 2026-08-06 against
  `https://api.mumchimp.com/catalog`): 34 of 63 live catalogue rows (54%) have `oneLine`
  truncated to exactly 153 chars, some mid-word (`"for a flat fee per applicat…"`,
  `"keeps you on …"`). Root cause: `prospector/bridge.py:394` was a hard character-index slice
  (`one_liner[:150] + "..."`) with no word-boundary awareness, on the publish path that feeds the
  storefront's card description AND the pack-page lead paragraph, directly above the buy button.
- The uncommitted diff fixes it in three places: (a) `bridge.py` now cuts on the last space
  inside the 150-char window (`rsplit(" ", 1)`) so nothing published from here on is cut mid-word;
  (b) `plain_text.py` gained escaping/HTML/setext-heading/reference-link fixes for the markdown
  pass that feeds the same pipeline; (c) `store_platform/src/Store.Web/src/lib/copy.ts` (new,
  untracked) repairs the 34 *already-published* rows client-side, since re-publishing is a
  money-rail operation (bundle upsert can ignore `PricePence` on update) and out of scope for
  a text fix.
- All tests scoped to this diff pass live, right now, on disk:
  - `pytest tests/unit/test_plain_text_storefront.py` → 37 passed
  - `pytest tests/unit -k "bridge or truncat"` → 13 passed (0 failed, 831 deselected)
  - `vitest run src/__tests__/usTwoPackArt.test.ts src/lib/__tests__/categoryScale.test.ts` → 2
    files / 12 tests passed
- `CLAUDE.md` also has an uncommitted diff, but it is a pure doc-compression pass (verified by
  reading the full diff) — no rule changes, not part of the ship decision.

**This is not a design or discovery task — it's a finished fix that never got committed.** That
makes "commit and land it" the single highest-leverage next-ship action: it fixes a live,
customer-visible defect on the money page, the code is already written and green, and every day
it stays uncommitted is another day new candidates can still publish with the pre-fix truncation
if `bridge.py`'s working copy is ever discarded (e.g. `git checkout .`, a clean worktree rebuild,
CI checking out HEAD instead of the working tree).

## (1) The one objective

Commit the uncommitted `prospector/bridge.py` + `prospector/plain_text.py` +
`tools/backfill_listing_copy.py` + `store_platform/.../copy.ts` word-boundary-truncation fix
(currently sitting unshipped on `fix/durable-ledger-fence`) and open a PR, so the fix that stops
54% of live product descriptions from being cut mid-word actually ships instead of living only in
an uncommitted working tree.

## (2) Acceptance test

The fix is "shipped" when it is committed (not merely present in the working tree) and its own
tests still pass from that commit. Single self-contained read-only check:

```bash
cd ~/Documents/code/prospector && git log --oneline -5 -- prospector/bridge.py | grep -qi 'word.boundary\|rsplit\|truncat' && git diff --quiet HEAD -- prospector/bridge.py prospector/plain_text.py tools/backfill_listing_copy.py && python -m pytest tests/unit/test_plain_text_storefront.py -q | tail -1 | grep -q 'passed'
```

Exit 0 = the truncation fix has been committed (git history references it, working tree is clean
against HEAD for the three files) AND its test file still passes from that commit. Exit 1 = still
unshipped or broken.

## (3) Files to touch

- `prospector/bridge.py` — already-written fix at the `one_liner` truncation site (~line 394-410);
  just needs `git add` + commit, no further edits identified.
- `prospector/plain_text.py` — already-written escaping/setext/ref-link/HTML fixes; same.
- `tests/unit/test_plain_text_storefront.py` — already-written, 37/37 passing; commit as-is.
- `tools/backfill_listing_copy.py` — already-written `has_card_line` + `--plan-only` additions;
  commit as-is.
- `store_platform/src/Store.Web/src/lib/copy.ts` (new/untracked) and
  `src/lib/searchEvent.ts` (new/untracked, appears unrelated — verify before bundling into the
  same commit or split it out) — add and commit.
- `store_platform/src/Store.Web/src/components/discovery/CommandPalette.tsx`,
  `marketing/DossierExcerptPlate.tsx`, `marketing/MarketingLayout.tsx`, `pages/index.tsx`,
  `pages/pack/[id].tsx`, `src/__tests__/usTwoPackArt.test.ts`,
  `src/lib/__tests__/categoryScale.test.ts`, `store_platform/src/Store.Web/e2e/discovery.spec.ts`
  — modified, presumably wiring `copy.ts`/`searchEvent.ts` in; review diffs before commit since
  they weren't all inspected line-by-line here.
- Before committing: decide whether `CLAUDE.md`'s doc-compression diff ships in the same commit
  or separately (recommend separate — it's unrelated to this fix).

## (4) Risks

- **`bridge.py` is the money-rail entry point** (per its own module docstring: "one
  `PriceDecision` feeds both [minted price and catalogue row]"). The diff touches only the
  one-liner truncation, not pricing — confirmed by reading the full diff (22 lines, all in the
  truncation block) and by `test_bridge_pricing.py` (5/5 passing, unmodified) — but any commit
  touching this file should get a second look at the pricing tests specifically before merge, not
  just the truncation tests.
- **`searchEvent.ts` looks unrelated to the truncation fix** (it's a window-event constant for
  opening the command palette) — bundling it into the same commit/PR as a copy-truncation fix
  mixes concerns; recommend verifying it's actually load-bearing for this diff (e.g. is it
  imported by `CommandPalette.tsx`'s modified diff) before committing, or split into its own
  commit.
- **The 34 already-published rows are not fixed by this commit** — `copy.ts` repairs them
  client-side at render time; the dossier/catalogue rows themselves stay truncated at rest. That's
  a deliberate, documented scope decision (re-publish is a separate money-rail operation with its
  own hazards) — but it means "ship this" does not mean "the 34 rows are fixed," only that no more
  rows join them and the 34 render correctly to buyers.
- **Six other frontend files in the diff were not individually reviewed** here beyond confirming
  their two associated test files pass — a full review before merge should read those diffs, not
  just trust the two test files inspected.
- Branch is `fix/durable-ledger-fence`, named for a different fix (per HEAD commit
  `5cacaa1 fix(ledger): the test suite wrote 1,874 fake laws into the engine's own memory`) — the
  truncation fix is unrelated work sitting on the same branch. Confirm the intended PR boundary
  (this branch vs. a fresh branch off `main`) before opening a PR.
