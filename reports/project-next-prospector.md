# Prospector — next ship item (2026-08-07)

Source: live inspection of `~/Documents/code/prospector`, branch `fix/durable-ledger-fence`,
HEAD **`e0f6991`** (`2026-08-07 08:30:58 +0100`, "feat(gates): apply confidence_floor 0.4 +
measure the rerank ceiling (E16)"). Read-only — no source changed, no PR opened, no publish or
backfill tool run. Quote this SHA when checking whether this report has gone stale.

**Supersedes the 2026-08-06 entry.** That report's objective was to ship the uncommitted
word-boundary truncation fix in `prospector/bridge.py`. It **has shipped**:

```
$ git log --oneline -5 -- prospector/bridge.py
190cd00 merge: origin/main into fix/durable-ledger-fence — lands P0 in the daemon's checkout
ef06b6b fix(storefront): word-boundary truncation on the money page, backfill card_line-only gaps
```

Its acceptance command now exits 1 only because `tools/backfill_listing_copy.py` is dirty again —
a tooling file, not the fix. `prospector/bridge.py` itself is clean (`git status --short` shows no
`prospector/` path). The old objective is retired.

Two further corrections to the spec that produced this report, both re-derived on disk:

- **`thresholds.confidence_floor: 0.4` is no longer uncommitted.** It landed in `e0f6991`
  (`config.yaml:205`, plus lane overrides at `:308/:351/:417/:468`); `git diff --quiet HEAD --
  config.yaml` passes. It is a fixed constant for the duration of the A/B below, not a moving part.
- **`tools/experiments/e16_rerank_ceiling.py` is now tracked**, committed in the same `e0f6991`
  (`git ls-files --error-unmatch` succeeds), not untracked.

---

## 1. THE ONE OBJECTIVE

**Extend `_ENTITY_TEMPLATES` (`prospector/verify.py:223-232`) to cover `incumbency` and
`legality`, make `retrieval.hybrid_entity_checks` fail loudly when it names a check with no
template, and then enable `hybrid_entity_checks: [payer_solvency, incumbency, legality]`.**

### Why this and not the confidence floor

Freshly measured, not quoted from the doc table (`.venv/bin/python
tools/experiments/e12_grounding_yield.py`, read-only over `store/dossiers/*.kill.json`, zero LLM,
zero network; receipts at `tools/experiments/e12_grounding_yield_receipts.json`):

```
dossiers=486, kills=379, since=2026-08-0

grounding-QUALITY kills (moat_ungrounded + source_or_die): 136/379 = 35.9%

DID RETRIEVAL ACTUALLY FAIL ON THOSE?  citations per moat_ungrounded dossier:
    mean=21.3 median=20.0 zero-citation dossiers=0/122

check                   n  unverif%   supp%   ref%   cites   conf retr_fail
payer_solvency        321     60.7%   29.9%   9.3%     4.3   0.57         4
legality              314     55.4%   42.0%   2.5%     4.6   0.57         8
incumbency            231     55.0%   16.9%  28.1%     4.9   0.62         3
```

(The programme doc §18.2 recorded 131/366 = 35.8%, payer_solvency 60.5%, legality 54.8%. The store
moves within minutes; the numbers above are today's and are the ones to beat.)

36% of August kills are lost to grounding **quality**, on candidates that retrieved a mean of 21.3
citations with **zero** zero-citation dossiers. Retrieval worked; the passages did not answer the
question. That is a query-targeting problem, and §18.6 ranks it above the E11 floor for exactly the
reason that matters: **it loosens no gate.** The floor frees 66 of 333 hard-gate kills
(`docs/COMMERCIAL_READINESS_PROGRAM.md:890`) by lowering a bar; the entity arm makes the evidence
actually arrive.

### Why it is a CODE change, not a config change

`_entity_queries` returns `[]` for any check absent from the dict:

```python
# prospector/verify.py:241-243
    tpls = _ENTITY_TEMPLATES.get(check_name, [])
    if not tpls:
        return []
```

and the caller then falls straight through to the LLM chain with no error and no log:

```python
# prospector/verify.py:478-483
    entity = (_entity_queries(cand, check_name, r.queries_per_check or r.fast_queries)
              if check_name in (r.hybrid_entity_checks or []) else [])
    if entity:
        queries, query_source = entity, "entity_template"
    elif precomputed:
        queries, query_source = precomputed, "llm_batched"
```

`_ENTITY_TEMPLATES` has exactly two keys, `payer_solvency` and `distribution`
(`verify.py:223-232`), and `config.yaml:113` is still `hybrid_entity_checks: []`. So the two worst
untemplated checks cannot receive the arm at all, and listing them in config is **silently inert**.
The e12 script confirms this itself:

```
E1 hybrid arm ELIGIBLE checks (have an entity template): ['distribution', 'payer_solvency']
three worst-grounded checks: ['payer_solvency', 'legality', 'incumbency']
  !! ['legality', 'incumbency'] are worst-grounded but have NO entity template
```

Note also that E1's original second target, `distribution`, measures **38.0% unverifiable — the
fifth-best check of ten**. Swapping it for `incumbency` and `legality` moves the arm onto the
checks with headroom.

---

## 2. ACCEPTANCE TEST

An **offline, forward-only A/B on `query_source`**.

1. Engage the half-stop at session start: create `store/scheduler/PAUSE_GENERATION`
   (`run_scheduled.py:407` — a plain file-existence check; the drain keeps running). **Delete it at
   the end.** No `PAUSE*` file exists right now (checked: `ls store/scheduler/PAUSE*` → no matches),
   so a leftover is unambiguously yours.
2. Run the control arm (`hybrid_entity_checks: []`) and the treatment arm
   (`[payer_solvency, incumbency, legality]`) in the same window.
3. Compute per-arm unverifiable rate from `CheckResult.query_source` — `entity_template` vs
   `llm_batched` — for `incumbency` and `legality`.

**Recorded limit (§18.4, verbatim):** "The plan recorded earlier … works **forward only**.
`query_source` exists and is populated (`models.py:213`; set at `verify.py:481-493`, persisted at
`:527/:534/:553/:561`), but no August dossier carries the field, because the code reached the
daemon's checkout only with today's merge. There is no retroactive control arm. Both arms must be
run fresh."

Confirmed live — the e12 sweep of all 486 dossiers finds the field on 59 checks, all one value:

```
query_source present on checks: {'llm_batched': 59}
```

Zero `entity_template`. **There is no historical baseline arm; the control must be collected in the
same window as the treatment.**

**Success bar:** the `incumbency` and `legality` unverifiable share drops below today's freshly
measured baselines — **55.0%** and **55.4%** — with the gate definitions unchanged.

---

## 3. FILES TO TOUCH

| File | Change |
|---|---|
| `prospector/verify.py:223-232` | Add `incumbency` and `legality` entries to `_ENTITY_TEMPLATES`, slot-filled from candidate fields the way the existing two are (`{payer}`, `{aud}`, `{base}` from `_keywords`). `_entity_queries` (`:235-252`) needs no change — the blank-slot skip at `:249-250` already handles a missing slot. |
| `prospector/config.py:74` | `hybrid_entity_checks: list[str]` — add validation against `_ENTITY_TEMPLATES.keys()` so an unknown check raises instead of no-op'ing. |
| `config.yaml:113` | Set `hybrid_entity_checks: [payer_solvency, incumbency, legality]`. |
| new test under `tests/unit/` | (a) an entity-templated `incumbency`/`legality` query is produced for a candidate with a non-blank entity slot; (b) naming an unknown check in `hybrid_entity_checks` **raises** rather than silently returning `[]`. |
| `docs/COMMERCIAL_READINESS_PROGRAM.md` §18 / §16 | Log the result and close the E1 "Still open" bullet. |

---

## 4. RISKS

**(a) The silent-inert trap — a config-only attempt would wrongly retire E1.**
Receipt, §18.3: "**TRAP: `retrieval.hybrid_entity_checks` looks like a general switch and is not.**
Listing `incumbency` or `legality` there is INERT — no error, no log, the arm simply never engages
and the experiment reads as 'no effect'." The config change alone produces a clean null result that
looks like a refuted hypothesis. This is why the loud-failure validation in `config.py:74` is part
of the ship item, not a nicety.

**(b) Measurement contamination in both directions.**
The daemon writes dossiers continuously, so an un-paused run mixes arms. But a `PAUSE_GENERATION`
file left behind is the worse failure: §16 "Still open" — "**Engage it at the START of the
measurement session and delete it at the end** — a pause file left behind for an experiment nobody
is running is the same failure mode as the backlog cap that suppressed generation for six weeks."

**(c) Confounding with the confidence floor — now smaller than the spec assumed.**
The floor is a **KILL-side** lever (`kill_filter.is_hard_fail`); the entity arm is a
**GROUNDING-side** lever (query construction). They are decoupled by construction. The floor is
also no longer in flight: `confidence_floor: 0.4` is committed at `config.yaml:205` in `e0f6991`
and `git diff --quiet HEAD -- config.yaml` passes. **State in the write-up that the floor in force
for both arms was 0.4, and do not touch it for the duration of the A/B.**

**(d) A competing lever exists: reranking (E16). Named, not dropped.**
`tools/experiments/e16_rerank_ceiling.py` (committed in `e0f6991`; receipts in
`e16_rerank_ceiling_receipts.json`, 1481 checks / 5673 passages) measures that bucket-D
best-passage overlap sits close to supported checks':

```
check             n_supported  n_bucketD  supported_median  bucketD_median  bucketD_p90
payer_solvency         62         145          0.333            0.273          0.455
incumbency             23         134          0.308            0.308          0.455
legality              109         110          0.333            0.250          0.417
```

bucket-D p90 (0.455) exceeds the supported median (0.308–0.333), i.e. **some probative passages are
retrieved-but-unselected** and reranking is a real alternative. Recommend the entity arm **first**:
it needs no ~2GB torch install, and it attacks the worse-*targeted* checks rather than the
worse-*ranked* ones. Note `incumbency`'s bucketD median already equals its supported median
(0.308) — the weakest rerank case of the three, and the strongest targeting case.

**(e) The moat fence holds.**
This routes **around** the moat — query construction only — never through the verdict rules. §5
"Fences that do not move": "Verdict-from-retrieval-only; MOAT_PRIMARY only rules; … Everything in
this programme routes AROUND the moat, never through it." No gate definition, threshold or verdict
rule is touched by this ship item.
