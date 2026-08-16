# Prospector — next ship item (2026-08-16)

Source: live read-only inspection of `~/Documents/code/prospector`, HEAD **`6afa6cc`**
("fix(shelf): OSHA is a word, and our record was the stale copy of the shelf"). No code changed,
nothing committed, no PR. Every number below was re-derived on disk today.

**Supersedes the earlier 2026-08-16 version of this file**, which was written at HEAD `322e9ee`
and named "make stored PASS dossiers renderable" as the objective. `40a8ada` landed after it and
closed that item — receipt in §1. Also supersedes `docs/NEXT_MOVE_2026-08-15.md`, whose step 1 is
likewise now done.

---

## 1. The one objective

**Re-render the QA report from the stored dossier for every live pack, re-upload it, and prove it
from R2 — so no pack a buyer downloads claims it cleared checks its own record says it failed.**

Why this and not something else: it is a false factual claim inside the artefact every live listing
sells, and it contradicts the one proposition the product rests on — that the checks are real,
grounded and published (`README.md:1-13`). The other open items (5 stranded PASSes, thin
`Marketing_Assets`, storefront v5) are smaller or need a diagnosis before a fix exists.

**Why it is the ship item today:** the blocker is gone. `docs/NEXT_MOVE_2026-08-15.md` recorded
`stored PASS dossiers=64 rendered_ok=0 raised=64` against
`AttributeError: 'SimpleNamespace' object has no attribute 'items'`. Re-measured today through the
supported reader `pack_manifest.dossier_from_dict` (`prospector/pack_manifest.py:403`):

```
SUPPORTED READER: stored PASS dossiers=97 rendered_ok=97 raised=0
```

`dossier._mapping` (`prospector/dossier.py:342`, used at `:711-712`) and
`pack_manifest._fill_defaults` (`prospector/pack_manifest.py:373`) shipped in `40a8ada`
("test(packs): the fixture was green while every real record on the shelf failed", 2026-08-16).
The work is now unblocked and bounded to two files plus tests.

### Measured state of each step in the 08-15 work order

| Step | State | Receipt (re-run today) |
|---|---|---|
| 1. Stored dossiers render | **DONE** | `rendered_ok=97 raised=0` via `dossier_from_dict` |
| 2. Backfill regenerates the QA report | **NOT DONE** | `rg "render_markdown\|QA_Report" tools/backfill_bundle_html.py` returns no re-render path; the tool carries the `.md` text through with "exactly ONE edit" (docstring `:44-51`) |
| 3. Probe has `--from r2` | **NOT DONE** | `scripts/pack_banner_probe.py:67-71` — `main()` takes only `--verbose` and globs `publish/bundles/` |
| 4. Probe committed | **DONE** | `git ls-files --error-unmatch scripts/pack_banner_probe.py` → matches |
| 5. Re-upload + verify from R2 | **NOT DONE** | `.venv/bin/python scripts/pack_banner_probe.py` → `FAIL`: live listings 108, retired banner 73, contradicted 12, unreadable 35 |

**The defect changed shape — read this before starting.** `prospector/bridge.py:284-316` now splits
`PACK_DOCUMENTS` (render input, `.md`) from `BUNDLE_FILES` (what ships: `index.html`,
`Complete_Pack.pdf`, `First_Fortnight.html`, `Assumptions.csv`, `Marketing_Assets.txt`).
`QA_Report.md` is no longer a shipped file. So dropping the `.md` does not fix the claim — it
carries it into `index.html`, which is rendered from that same stale text. Re-render the QA content
**before** converting a pack, or the false line is baked into the reader permanently.

---

## 2. Acceptance test

Three commands, in order. All must pass; the third decides it.

```bash
cd ~/Documents/code/prospector

# a) unit gates for the files touched
.venv/bin/python -m pytest -q tests/unit/test_pack_manifest.py tests/unit/test_backfill_bundle_html.py

# b) no regression
.venv/bin/python -m pytest -q

# c) THE VERDICT — the live shelf, cold cache, not disk
set -a; . .env; set +a
.venv/bin/python scripts/pack_banner_probe.py --from r2   # must exit 0
```

Done means **`pack_banner_probe.py --from r2` exits 0 on a cold cache**. Not that the code changed,
and not that the disk probe went green: `publish/bundles/` is stale by design because uploads are
content-addressed to a new key (`prospector/bridge.py:1215-1224`). Reading disk instead of R2 is
the exact mistake that made the 2026-08-14 ticket read as nearly-done.

**Interim gate while in flight** (offline, runs anywhere):

```bash
cd ~/Documents/code/prospector && .venv/bin/python scripts/pack_banner_probe.py --from disk
```

---

## 3. Files to touch

| File | Edit |
|---|---|
| `tools/backfill_bundle_html.py` | Regenerate the QA content from the stored dossier (`pack_manifest.dossier_from_dict` → `dossier.render_markdown`) when the record contradicts the pack's banner, instead of carrying the stored `.md` through. Second deliberate exception to the byte-identical rule — document it in the docstring beside the first (`:44-51`). Content-compare so a re-run is a no-op. Packs with no stored dossier keep falling through the existing `dossier is None` guard (docstring `:29-33`): reported, not converted. |
| `scripts/pack_banner_probe.py` | Add `--from {disk,r2}`, default `r2`. Reuse `tools/preview_packs.py`'s `fetch_catalogue` / `_s3` / `_content_key` / `zip_for` rather than re-rolling an R2 reader. In `r2` mode inspect the shipped `index.html`, not `QA_Report.md` — that file no longer ships (`bridge.py:310-316`). Override `pp.CACHE` per run so a cold fetch is possible. |
| `tests/unit/test_backfill_bundle_html.py` | A case built from a **real** `store/dossiers/*.pass.json` carrying a failed check, asserting the rendered output has no clean-sheet banner. `40a8ada`'s subject is the warning: the fixture was green while every real record failed. |
| `tests/unit/test_pack_manifest.py` | Extend only if the backfill needs a new reader path. |

Do **not** touch `prospector/dossier.py` `_pass_gloss`. It was fixed on 2026-08-14 and counts
verdicts instead of asserting them. The generator is correct; only the shelf is stale.

---

## 4. Risks

1. **Another session is live in this checkout.** `git status --short` shows ~30 modified paths
   including tracked `store/` state. Never `git add -A`; add the four files above by name.
2. **The conversion is one-way.** `backfill_bundle_html.py` drops the `.md` render input from the
   zip (docstring `:23-33`). After conversion there is nothing left to re-render from, so the QA
   re-render must land first. The old object stays fetchable (content-addressed keys), so a
   mistake is recoverable, but only by a manual repoint of the listing.
3. **A disk-only probe can report PASS while the whole shelf is stale.** That is how 2026-08-14
   read as 73-of-75-nearly-done when R2 said 59-of-59. Until step 3 ships the probe cannot see the
   product. Do not accept a green disk run as the verdict.
4. **Wrong env var names fail silently.** They are `STORE_INTERNAL_API_KEY` and `STORE_API_URL`
   (`tools/preview_packs.py:49,280`). Guess them and `_content_key` falls through to a prefix
   listing, returns `None` for all packs, and the census reads as "0 stale".
5. **`pp.CACHE` persists zips between runs.** Without overriding it, a "verified fix" is verified
   against yesterday's bytes.
6. **35 of 108 live listings are unreadable on disk** (today's probe run). Separate defect, may
   hide more offenders. Diagnose it during step 3 — the R2 read may make it moot.
7. **Cost:** zero model calls. The backfill renders from stored records and never re-vets
   (docstring `:16-20`). Re-upload traffic only.
