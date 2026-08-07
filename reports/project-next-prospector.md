# Prospector — next ship item (2026-08-07, afternoon update)

Source: live inspection of `~/Documents/code/prospector`, branch `fix/durable-ledger-fence`,
HEAD **`e651f63`** (`2026-08-07 13:36:08 +0100`, "store: say what actually sets a price, and
disclose the pipeline on /about") — one commit ahead of the `e0f6991` HEAD the prior version of
this report was pinned to. Read-only inspection except where noted; tests were **run**, nothing
was committed, pushed, or published.

**This supersedes the morning entry only on ranking, not on content.** The morning entry's
objective (E1 entity-template extension) is **re-verified still open** below — nothing in it was
wrong, and nothing has shipped it since. But new, independently-completed and already-tested work
appeared on the working tree after that report was written (file mtimes 13:56 and 14:09, i.e.
after `e651f63` and after the morning report), and it dominates E1 on leverage because its
engineering cost is already sunk. It goes first.

---

## 1. THE ONE OBJECTIVE (revised): commit the auth-hijack fix + Q4 admissibility gate

This is **not new engineering** — it is capturing value that already exists on disk, untracked
and unprotected, ahead of starting the (still-valid, still-open) E1 work below.

### Evidence this is done and safe to ship

- **Tests green.** `.venv/bin/python3 -m pytest tests/unit/test_admissibility.py
  tests/unit/test_cli_auth.py -q` → `34 passed` in 1.79s.
- **Full suite unaffected.** `.venv/bin/python3 -m pytest tests/unit -q` → `956 passed, 2
  skipped, 0 failed` in 131s (run against the working tree, i.e. inclusive of these uncommitted
  changes — they do not regress anything).
- **Small, self-contained diff** (`git diff --stat`): `config.yaml` +18, `prospector/claude_cli.py`
  +12/-4, `prospector/config.py` +41, `prospector/verify.py` +32/-3, plus 4 new files
  (`prospector/admissibility.py` 185 lines, `prospector/cli_auth.py` 112 lines,
  `tests/unit/test_admissibility.py` 155 lines, `tests/unit/test_cli_auth.py` 158 lines).
- **Documented with receipts already**: `docs/COMMERCIAL_READINESS_PROGRAM.md` §21
  (lines 1137–1215, written today) records both changes as "SHIPPED" — but git disagrees;
  nothing under `prospector/` in this set is committed. The doc is ahead of the repo.

### Why this beats starting E1 right now

1. **Zero remaining engineering cost.** E1 (below) needs new dict entries, a config validator,
   new tests, and a forward-only A/B measurement window before its own success bar can even be
   evaluated. This item needs `git add && git commit && git push`.
2. **It closes a moat-integrity hole, not a cosmetic bug.** §21.1 (matched-control test, same
   shell/binary, only `~/.config/llm/secrets.sh` swapped): an exported `ANTHROPIC_API_KEY`
   outranks the claude.ai OAuth login for every `claude` child process. Worse than the billing
   symptom: a leaked `ANTHROPIC_BASE_URL` would let a non-Anthropic model rule a verdict while
   still reporting provider `claude_cli`, silently defeating `MOAT_PRIMARY`
   (`prospector/operator.py:889`) — the one fence `CLAUDE.md` names as absolute ("Verdicts are
   ruled ONLY by `MOAT_PRIMARY`"). `prospector/cli_auth.py:57`
   (`SUBSCRIPTION_HIJACK_VARS = {ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL}`),
   applied at every spawn via `claude_cli.py:145,185`.
3. **It is currently unprotected.** `git status --short` shows 53 uncommitted paths total on this
   checkout, and `CLAUDE.md`'s own working-in-a-worktree section states the checkout "is often
   shared by two concurrent sessions" — a stash/reset/clobber risk with no git history to recover
   from (per house rule: never `stash drop` without inspecting first; the stronger version of
   that rule is not to leave proven work un-committed at all).

### Files to commit — exactly these 9, nothing else

The other 44 of the 53 uncommitted paths (`store/scheduler/*.jsonl*`, `store/listings_archive/*`,
`store/pricing/rationale/*`, `store_platform/src/Store.Web/*`, `tools/backfill_*`) are runtime
state or unrelated in-flight work and must not be bundled — confirmed by `git diff --stat` scope
above matching only these paths:

```
prospector/admissibility.py          (new)
prospector/cli_auth.py               (new)
prospector/claude_cli.py             (modified)
prospector/config.py                 (modified)
prospector/verify.py                 (modified)
config.yaml                          (modified — admissibility.policy: P1_check_aware, config.yaml:186-201)
tests/unit/test_admissibility.py     (new)
tests/unit/test_cli_auth.py          (new)
docs/COMMERCIAL_READINESS_PROGRAM.md (modified — §17-21)
```

```bash
cd ~/Documents/code/prospector
git add prospector/admissibility.py prospector/cli_auth.py \
        prospector/claude_cli.py prospector/config.py prospector/verify.py \
        config.yaml \
        tests/unit/test_admissibility.py tests/unit/test_cli_auth.py \
        docs/COMMERCIAL_READINESS_PROGRAM.md
git status --short   # confirm exactly these 9 paths staged, nothing else
git commit -m "fix(auth): stop ambient ANTHROPIC_* vars hijacking the subscription login; ship Q4 admissibility gate (P1_check_aware)"
git push
```

**Post-commit verification (re-run, don't trust the commit message):**
```bash
.venv/bin/python3 -m pytest tests/unit/test_admissibility.py tests/unit/test_cli_auth.py -q
.venv/bin/python3 -m prospector.cli_auth   # exits 1 if a hijack var is present in the ambient env
```

**Not touched, on purpose:** a sensitive-but-true catalogue item (§20.4, tattoo-trade dossier) is
flagged for a founder editorial call and was correctly left unchanged by the agent that found it —
do not fold it into this commit or any automated one. `~/.config/llm/secrets.sh` was inspected
(confirmed already fixed — key present but no longer `export`ed) and not modified; its content is
a live secret and is deliberately not restated here.

**human_decision_required for the push step**, per the "confirm before outward-facing/hard-to-
reverse actions" rule: this push is to `origin/fix/durable-ledger-fence`, a shared branch — the
commit itself is low-risk (isolated diff, fully tested) but pushing to a branch another session may
be working on is the one step in this plan an operator should eyeball first.

---

## 2. THE OBJECTIVE AFTER THAT (unchanged from the morning report, re-verified still open)

**Extend `_ENTITY_TEMPLATES` (`prospector/verify.py:223-232`) to cover `incumbency` and
`legality`, make `retrieval.hybrid_entity_checks` fail loudly when it names a check with no
template, then enable `hybrid_entity_checks: [payer_solvency, incumbency, legality]`.**

**Re-verified NOT shipped** (this session, against current HEAD `e651f63`):
```
$ sed -n '223,232p' prospector/verify.py
_ENTITY_TEMPLATES: dict[str, list[str]] = {
    "payer_solvency": [...],
    "distribution": [...],
}
$ grep -n hybrid_entity_checks config.yaml
113:  hybrid_entity_checks: []
```
Still only 2 of 3 target checks templated, config still empty — the morning report's objective and
reasoning stand unchanged. Full rationale (36% of August kills lost to grounding *quality* not
*availability*, the silent-inert config-only trap, the offline forward-only A/B design, the
confidence-floor and E16-rerank decoupling) is preserved verbatim below from the prior version of
this file rather than re-derived, since re-deriving would just reproduce the same measurements —
the doc pointers (`docs/COMMERCIAL_READINESS_PROGRAM.md` §18, §16) are static.

Full prior write-up (unchanged, still the correct plan for objective #2):

> ### Why this and not the confidence floor
>
> `.venv/bin/python tools/experiments/e12_grounding_yield.py` (read-only over
> `store/dossiers/*.kill.json`, zero LLM, zero network):
> ```
> dossiers=486, kills=379
> grounding-QUALITY kills (moat_ungrounded + source_or_die): 136/379 = 35.9%
> citations per moat_ungrounded dossier: mean=21.3 median=20.0 zero-citation dossiers=0/122
> payer_solvency  321  60.7% unverifiable, 4.3 cites
> legality        314  55.4% unverifiable, 4.6 cites
> incumbency      231  55.0% unverifiable, 4.9 cites
> ```
> Retrieval worked (mean 21.3 citations, zero zero-citation dossiers); the passages did not answer
> the question. Query-targeting problem, not an availability problem.
>
> ### Why it is a CODE change
> `_entity_queries` (`verify.py:241-243`) returns `[]` silently for any check absent from
> `_ENTITY_TEMPLATES`, and the caller (`verify.py:478-483`) falls through to the LLM chain with no
> error, no log. Listing `incumbency`/`legality` in `config.yaml` alone is **silently inert** — the
> e12 script confirms: `E1 hybrid arm ELIGIBLE checks: ['distribution', 'payer_solvency']`,
> `!! ['legality', 'incumbency'] are worst-grounded but have NO entity template`.
>
> ### Acceptance test
> Offline, forward-only A/B on `CheckResult.query_source` (`entity_template` vs `llm_batched`).
> No retroactive control arm exists — confirmed, all 59 dossiers carrying the field today read
> `llm_batched` only. Engage `store/scheduler/PAUSE_GENERATION` at the start, delete it at the end.
> Success bar: `incumbency`/`legality` unverifiable share drops below 55.0%/55.4%.
>
> ### Files to touch
> `prospector/verify.py:223-232` (add template entries) · `prospector/config.py:74` (validate
> `hybrid_entity_checks` against `_ENTITY_TEMPLATES.keys()`, raise on unknown) ·
> `config.yaml:113` (`hybrid_entity_checks: [payer_solvency, incumbency, legality]`) · new test ·
> `docs/COMMERCIAL_READINESS_PROGRAM.md` §18/§16 (log result).
>
> ### Risks
> (a) silent-inert trap if the config change ships without the loud-failure validator — read as a
> refuted hypothesis instead of an untested one. (b) a leftover `PAUSE_GENERATION` file suppresses
> generation for whoever forgets to delete it. (c) confidence_floor (0.4, committed `config.yaml:205`
> in `e0f6991`) is a KILL-side lever, decoupled by construction from this GROUNDING-side lever — hold
> it fixed for the duration. (d) reranking (E16) is a named, not dropped, competing lever — entity
> templates go first because they need no ~2GB torch install and attack targeting, not ranking.
> (e) the moat fence holds: this routes around query construction only, never through verdict rules.

---

## What I did in this session

Ran (did not just read): `pytest tests/unit` twice (system python3.14 — false `mistune` import
error, an environment-selection mistake not a repo defect; then `.venv/bin/python3`, green),
`pytest tests/unit/test_admissibility.py tests/unit/test_cli_auth.py`, `git status`, `git diff
--stat`, `git log`, file-mtime checks to establish ordering against the morning report, and a grep
of `~/.config/llm/secrets.sh` to confirm the interactive-shell half of the auth fix (not repeated
here — it returned a live API key in output, which is not restated anywhere in this file or
committed anywhere). Did not commit, push, or modify any source file.
