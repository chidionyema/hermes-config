# Prospector — next ship item (2026-08-16, revision 2)

Source: live read-only inspection of `~/Documents/code/prospector`, HEAD **`8758213`**
("feat(console): run every tool from the console, with a rollback snapshot"). No code changed,
nothing committed, no PR. Every number below was re-derived on disk today.

**Supersedes the earlier 2026-08-16 revision of this file**, written at HEAD `6afa6cc`, which named
"re-render QA_Report.md from the stored dossier and re-upload" as the objective. That objective is
largely already met by a different mechanism — the pack conversion — and the receipt is in §1.
Also supersedes `docs/NEXT_MOVE_2026-08-15.md`.

---

## 1. The one objective

**Make `scripts/pack_banner_probe.py` measure what a buyer actually receives — the rendered
`index.html`, fetched from R2 — then convert the remaining live packs until it exits 0.**

The measurement comes first because the current measurement is wrong in both directions. No
decision about the shelf can be trusted until it is fixed.

### Why the old objective is no longer the objective

The prior revision said every live pack ships a `QA_Report.md` claiming it cleared checks its own
report shows it failed. On disk today that is no longer true for the converted packs.

Re-derived today across `publish/bundles/`:

```
CONVERTED PACKS (no QA_Report.md, has index.html): 74
  index.html carries retired PASS banner        : 0
  ...and contradicts it in the same document    : 0
```

Pack `08b22037fc2afc07` is the exact offender quoted in `docs/NEXT_MOVE_2026-08-15.md`. Its built
zip now holds six entries — `Marketing_Assets.txt`, `First_Fortnight.html`, `Assumptions.csv`,
`index.html`, `Complete_Pack.pdf`, `manifest.jsonld` — and `index.html` contains the retired
sentence "cleared every check we hold it to" **0 times**, while still carrying the QA content
(`❌` ×1, "contradict" ×4). The conversion in `tools/backfill_bundle_html.py` drops every `.md`
and renders the reader through the shared renderer, so the honest banner reached the shelf without
anyone writing the QA-re-render step the old plan asked for.

### The two defects that are actually open

**(a) The probe cannot see a converted pack, and calls it broken.**
`scripts/pack_banner_probe.py:46` pins `QA_MEMBER = "QA_Report.md"`, and `_qa_text` returns `None`
when that member is absent. A converted pack — the fixed shape — lands in `unreadable`, which
`main()` treats as FAIL. So the probe fails hardest on the packs that are correct.

**(b) The probe reads disk, and its own docstring says disk is not the product.**
`scripts/pack_banner_probe.py:17-21` describes `--from disk` versus R2 and states "only an R2 read
can prove what is SERVED". `main()` (`:67-71`) accepts only `--verbose` and globs
`publish/bundles/`. The flag does not exist. Uploads are content-addressed to a new key
(`prospector/bridge.py:1215-1224`), so the local build directory is stale by design.

Disk probe, run today:

```
── PACK BANNER PROBE ── source: publish/bundles (BUILT, not necessarily SERVED)
live listings                         : 117
  no bundle on this disk              : 0
  bundle unreadable                   : 47      <- converted packs, i.e. the FIXED ones
  QA_Report carries retired banner    : 70      <- genuinely unconverted
  …and contradicts it in the same doc : 11
FAIL — a pack on sale states it cleared checks that its own report says it did not.
```

Read correctly, that output says: **70 of 117 live listings are still unconverted on this disk, and
nothing here tells us what R2 serves for any of the 117.**

---

## 2. Acceptance test

The verdict command, once the probe is fixed:

```bash
cd ~/Documents/code/prospector
set -a; . .env; set +a
.venv/bin/python scripts/pack_banner_probe.py --from r2   # must exit 0
```

Done means that command exits 0 on a cold cache. Not that the code changed, and not that the disk
probe went green.

Interim gate while the probe change is in flight — offline, no credentials, runs anywhere:

```bash
cd ~/Documents/code/prospector
.venv/bin/python -m pytest -q tests/unit/test_pack_banner_probe.py && \
.venv/bin/python scripts/pack_banner_probe.py --from disk --verbose
```

The unit test must cover both zip shapes: a legacy zip with `QA_Report.md`, and a converted zip
with `index.html` and no `.md`. The probe has no test file at all today.

---

## 3. Files to touch

| File | Change |
|---|---|
| `scripts/pack_banner_probe.py` | Add `--from {disk,r2}`, default `r2`. Reuse `fetch_catalogue` / `_s3` / `_content_key` / `zip_for` from `tools/preview_packs.py:61,67,87,106` instead of writing a second fetcher. Widen the evidence member: prefer `QA_Report.md`, fall back to `index.html` when no `.md` is present, and strip HTML tags before matching so a tag boundary cannot hide the banner. Keep `unreadable` only for a genuinely broken zip. |
| `tests/unit/test_pack_banner_probe.py` | New. Two fixture zips (legacy `.md` shape, converted `index.html` shape) × two texts (retired banner present, absent). Asserts exit 1, 1, 0, 0. |
| `tools/backfill_bundle_html.py` | No code change expected. The runner already exists: `--dry-run` (default), `--apply`, `--only PACK_ID`, `--take-newest` (`:427-451`). Use `--only` for the first pack, then batch. |
| `docs/NEXT_MOVE_2026-08-16.md` | Record the corrected census once the R2 probe has run, superseding the 08-15 numbers. |

Order of work: fix the probe, run `--from r2` to get the true count, then convert only the packs it
names. Converting blind before measuring re-uploads packs that may already be clean.

---

## 4. Risks

1. **The PDF is not covered.** `Complete_Pack.pdf` ships in every bundle and is rendered from the
   same text. A probe that reads only `index.html` can exit 0 while the PDF still carries the
   retired sentence. HYPOTHESIS, not measured — PDF streams are compressed, so a byte grep proves
   nothing. Check before declaring done: extract the text of one converted pack's PDF and search it,
   or state the gap explicitly in the probe's docstring.
2. **`--from r2` needs credentials.** Defaulting to `r2` means the probe fails in any context
   without `.env`. It must exit non-zero with a clear message when credentials are missing. It must
   never fall back to disk and print PASS. Silent fallback is how the 2026-08-14 ticket read as
   nearly-done.
3. **Twelve live listings have no stored dossier.** 117 live listings, 105
   `store/dossiers/*.pass.json`. The backfill returns `None` for a pack with no dossier and leaves
   it untouched (`tools/backfill_bundle_html.py:28-31`). Those packs cannot be converted by this
   route. Name them; do not skip them silently.
4. **`--apply` writes to the live shelf.** It uploads a new zip and PATCHes the listing's content
   pointer. Content-addressed keys mean the old object survives and the change is reversible, but
   this is a write against what customers download. Run `--dry-run` over the full set and read the
   report before any `--apply`.
5. **The disk numbers will keep drifting.** `publish/bundles/` holds packs that were never listed
   and misses re-uploads. Once `--from r2` exists, treat every disk number in this document as
   historical.

---

## Not the objective, and why

- **Storefront v5 and the control-center split** — `66ae45f` and `3c74750` landed. No failing gate
  points at them today.
- **Money rail status endpoint** — uncommitted work in `store_platform/src/Store.Api/Payments/`
  (`MoneyRailStatus.cs` and `MoneyRailStatusTests.cs`, both staged). Real work, but it is a
  money-rail change: it belongs in a dedicated session, and it does not compete with a false claim
  inside the artefact 117 listings sell.
- **The five stranded PASSes** — smaller, and it needs a diagnosis before a fix exists.
