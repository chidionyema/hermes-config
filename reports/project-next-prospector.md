# Prospector — next ship item (2026-08-16)

Source: live read-only inspection of `~/Documents/code/prospector`, HEAD **`322e9ee`**
(`2026-08-16 03:56:05 +0100`, "fix(sweep): the rewrite knew who the customers were…").
No code changed, nothing committed, no PR. Every number below was re-derived on disk today —
none is quoted from `docs/NEXT_MOVE_2026-08-15.md`, and two of that ticket's five work-order
steps have since shipped (see §5). Supersedes the 2026-08-07 version of this file.

---

## 1. The one objective

**Make every stored PASS dossier renderable again: `dossier.render_markdown()` must not raise on
a `store/dossiers/<id>.pass.json` record that predates a `Dossier` field.**

Measured today, 84 of 84 stored PASS records still fail — but on a *different* cause than the one
the 2026-08-15 ticket named, and one that is now a single field:

```
stored PASS dossiers=84 rendered_ok=0 raised=84
FIRST FAILURE: store/dossiers/08b22037fc2afc07.pass.json
    if dossier.persona:
       ^^^^^^^^^^^^^^^
AttributeError: 'types.SimpleNamespace' object has no attribute 'persona'
```

Set `persona` on the namespace and **all 84 render** (`rendered_after_patching: 84`, enumeration
run this session — one AttributeError name collected per file until render succeeded; `persona`
was the only name that ever appeared, 84/84).

**Why this and not the shelf itself.** The product defect is still 73 of 94 live listings shipping
a `QA_Report.md` that claims a clean sheet, 12 of which contradict it in the same document
(`.venv/bin/python scripts/pack_banner_probe.py` → **exit 1**, run today). The probe's own remedy
line names the input: *"re-render QA_Report.md from the stored record (store/dossiers/<id>.pass.json…)"*.
Nothing downstream — re-render, re-upload, R2 verification, the one-way `.md`→`index.html`
conversion — can start while that input cannot be read. This is the only item with **zero
dependencies and 73+ packs behind it**.

## 2. Root cause, at line numbers

- `prospector/pack_manifest.py:342-360` — `_ns()` builds a `SimpleNamespace` **from the keys the
  JSON happens to have**. Its docstring argues (correctly) that persisted keys *are* the dataclass
  field names, but that only holds for fields that existed when the record was written. Any field
  added later is simply absent from the namespace.
- `prospector/models.py:460` — `persona: str = ""` was added after these 84 records were written.
  Diffing one record against `dataclasses.fields(Dossier)`: **missing = `persona`,
  `publish_status`, `publish_error`**; only `persona` is read by `render_markdown`, so it is the
  only one that fires today. `publish_status` / `publish_error` are the same bomb, unarmed.
- `prospector/dossier.py:776-777` — `if dossier.persona:` reads the field unguarded.

This is the same class of defect as the one `_mapping()` fixed (`prospector/dossier.py:342`, used
at `:711-712`) — *stored record ≠ live dataclass* — on the other axis: **absent field** rather than
**dict-whose-keys-are-data**.

**Recommended fix (chosen, not a menu):** fill the gap where the shape is known — in
`pack_manifest._ns`'s dossier entry point, apply `dataclasses.fields(Dossier)` defaults for keys
absent from the record. That kills the whole class (`publish_status` too), costs ~6 lines, and —
unlike a `__getattr__`-returning-`None` namespace — still raises on a *misspelled* field name, so
it does not convert future typos in `render_manifest`/`render_markdown` into silent blanks.
Guarding `dossier.py:776` with `getattr(..., "persona", "")` is the 1-line alternative but is
whack-a-mole: it leaves `publish_status` to fire the next time someone reads it.

## 3. Acceptance test

Read-only, no network, exit code is the verdict:

```bash
cd ~/Documents/code/prospector && .venv/bin/python - <<'PY'
import glob, json, sys
sys.path.insert(0, '.')
from prospector import pack_manifest, dossier
fs = sorted(glob.glob('store/dossiers/*.pass.json'))
bad = []
for f in fs:
    try:
        dossier.render_markdown(pack_manifest._ns(json.load(open(f))))
    except Exception as e:
        bad.append((f, type(e).__name__, str(e)[:80]))
print(f'stored PASS dossiers={len(fs)} rendered_ok={len(fs)-len(bad)} raised={len(bad)}')
for b in bad[:3]:
    print('FAIL', *b)
sys.exit(1 if (bad or not fs) else 0)
PY
```

Today: **exit 1**, `raised=84`. Done means **exit 0 over the live `store/dossiers/*.pass.json`
population**, not over fixtures.

⚠ The unit suite cannot serve as this gate, and must not be substituted for it:
`tests/unit/test_pack_manifest.py` + `tests/unit/test_backfill_bundle_html.py` were **green** on
2026-08-15 while 64 of 64 real records failed, because their fixtures are complete records. Add the
loop above as a test (it is ~10 lines) so the gate can actually fail on the live defect. Run
`.venv/bin/python -m pytest -q` as the no-regression check alongside it.

## 4. Files to touch

| File | Change |
|---|---|
| `prospector/pack_manifest.py:342-360` | `_ns` (dossier entry point): fill `Dossier` dataclass defaults for absent keys; extend the docstring's "no mapping table" note with the *record predates the field* case. |
| `prospector/dossier.py:776` | Only if the reader-side variant is chosen instead — `getattr(dossier, "persona", "")`. Not both. |
| `tests/unit/test_pack_manifest.py` | New test: iterate `store/dossiers/*.pass.json`, assert `raised == 0`; plus a synthetic record missing `persona`/`publish_status`. Skip cleanly when the dir is empty so CI stays machine-independent (`tests/test_suite_is_machine_independent.py` enforces this). |
| `scripts/pack_banner_probe.py:66-80` | *Next* item, not this one: `--from {disk,r2}` (default `r2`) reusing `tools/preview_packs.py` `fetch_catalogue`/`_s3`/`zip_for`. `main()` still populates from `store/listings/*.json` (`:73`) and reads `publish/bundles/` (`:56-64`) — both local build state, which is why disk says 94 listings / 73 stale while the last R2 census said 59 / 59. |

## 5. Risks

1. **The 2026-08-15 ticket is partly stale — do not re-do shipped work.** Verified today: step 1's
   `_mapping()` reader **has shipped** (`prospector/dossier.py:342`, `:711-712`; the
   `sc.scores.items()` AttributeError no longer occurs), and step 4 has shipped —
   `git ls-files --error-unmatch scripts/pack_banner_probe.py` now **exits 0**. Still open: the
   `persona` gap (this item), `--from r2` (probe exits 2 on that flag; only `--verbose` is
   declared, `:70`), the re-render/re-upload, and the conversion.
2. **A defaulting-namespace implementation hides typos.** Returning `None` for *any* absent
   attribute would make a misspelled field read as empty in the published QA report — a silent
   wrong claim in the exact artefact this programme exists to correct. Hence the dataclass-defaults
   form above.
3. **Ordering still binds.** The `.md`→`index.html` conversion is one-way by design
   (`tools/backfill_bundle_html.py:24-33`: a source zip with no `.md` returns `None`). Convert
   before fixing the QA text and *"This cleared every check we hold it to"* is composed verbatim
   into `index.html` with its source `.md` gone — a full regenerate, not a backfill. **QA text
   first, conversion second.**
4. **A dirty checkout.** `git status --short` shows ~30 modified paths (incl. `prospector/store.py`,
   `prospector/operator.py`, `prospector/control_center/*`) plus untracked `.backfill-logs/`.
   Another session has been live here. Add the specific files; never `git add -A`.
5. **Disk numbers are not the product.** 94 listings / 73 stale / 12 contradicting is the *build
   directory*; the last R2 census read 59 / 59 / 11. Neither this item nor its acceptance test
   depends on that gap — but no "the shelf is fixed" claim is admissible until `--from r2` exists.

### Explicitly not this ticket

- **5 stranded PASSes** (`tools/verify_pass_shelf_coverage.py`) — runner-up; 4 of 5 need a
  diagnosis before a fix exists.
- **Thin `Marketing_Assets`** — generation quality, own owner.
- **ML/yield work** (`docs/ML_OPPORTUNITY_AUDIT_2026-08-15.md`) — its own recommendation #1 is that
  the engine keeps no `(features, outcome)` pairs, so it is a programme, not a ship item.
