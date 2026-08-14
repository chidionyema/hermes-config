# Introduction Exchange — product next-move (read-only diagnosis, 2026-08-14)

**Scope:** read-only inspection of `~/Documents/code/the-introduction-exchange`. Every claim below
was re-derived **today** against the fetched `origin/main` (via `git show origin/main:<path>`, not
the dirty working tree), plus live `gh run list` / `gh pr list`. **No code changed, no branch
checked out, no PR opened.** The only writes were this report and its archive
(`project-next-tie.prior-d155-2026-08-13.md`).

**Prior passes:** `project-next-tie.prior-d155-2026-07-31.md`, `project-next-tie.prior-d155-2026-08-13.md`.
Both named the same objective. This pass **independently re-verified it from source** and confirms
it — no fact below is carried over on trust.

**Repo state (verified today):** `origin/main` = `0c77d8ba4b3f92e12df5b5495201278e406273f9`,
`2026-06-13 18:30:35 UTC` — **61 days quiet**, zero commits. Primary checkout still on
`feat/e33-004-kycgate` @ `1e49f10`, behind `main`; tracked source paths are clean
(`git status --porcelain -- dotnet web scripts deploy docs` → 0 lines; the dirt is `.worktrees/`
and `consensus/runs/`). 33 open PRs, 7 non-dependabot (#185–#191). CI is green and running.

---

## 0. The trap: green CI is not evidence the money rail works

| Claim | Verified today | Receipt |
|---|---|---|
| CI is alive and green on `main` | **True** | `gh run list --workflow=golden-journeys-ci.yml --limit 3` → 3/3 `completed success` (2026-08-11/12/13, 5m10s–6m0s); `web-e2e-realstack` `success` 2026-08-13T05:53:20Z. |
| The nightly selects tests by trait | **True** | `.github/workflows/golden-journeys-ci.yml:99` → `--filter "Category=golden&Quarantine!=true"`. |
| The payout test carries **no** `Category` trait | **True** | `MoneyLoopSmokeTests.cs` grep for `Trait` returns **nothing**; only `[SkippableFact]` at `:29` and `:80`. The nightly filter therefore **cannot** select it. |
| The golden money journey is the **void** branch only | **True** | `GoldenJourneys.cs:32` — "money / settlement (**void branch** — always runnable; **payout needs the D-68 seed, covered by MoneyLoopSmokeTests**)"; `GoldenJourneys.cs:57` asserts `EntryTypes(ledger).Should().Contain("VOID").And.NotContain("PAYOUT")`. |
| No smoke-harness work has landed since the freeze | **True** | `git log --all --oneline --since=2026-06-13 -- dotnet/tests/Tie.SmokeTests/` → **empty**. |

**Therefore: every green run proves money can be *refunded*. Nothing in CI has ever proven money can
be *paid out*.** An all-green dashboard is precisely what makes this easy to miss.

---

## 1. The one objective

**Close D-155: make the connector-payout leg of the money+identity release smoke prove an end-to-end
payout, so the platform can actually pay a connector.**

Concretely: turn
`MoneyLoopSmokeTests.PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles`
(declared `MoneyLoopSmokeTests.cs:80-81`) from deterministic RED to green
(`Failed: 0  Skipped: 0`, ≥3 passed on release gate 1/2) — by first making its timeout
**self-diagnosing**, then fixing what the dump names.

### Why this and not anything else

TIE's economic promise is *money in escrow → introduction happens → **connector gets paid***. Money
**in** is proven. Money **out** has never been proven once.

- `LAUNCH-DEFERRALS.md:164` (D-155, verbatim): release gate 1/2 **FAILED 2/2 identical runs** — an
  auto-settled bounty produced **no PAYOUT ledger row** (`payout.ValueKind == Undefined`). Filed as
  "**deterministic, NOT a flake**"; the D-141 env-flake hypothesis "was tested and **rejected**";
  the leg "has **never** had a clean pass".
- Its unblock trigger is marked **"(hard, do BEFORE the next money deploy / any manual settlement /
  any auto-settle flip)"** — verified verbatim in the same row.
- Prod runs the **same code path**: `SettlementActivities.ProcessStripePayoutAsync` (`:75`) is
  reached by both the auto-settle sweeper and the manual admin sweep, and `:324` is the sole
  `EntryType = "PAYOUT"` write. So the payout rail is unverified **in production**, not just in test.
- **It is what froze the product.** 61 days, zero commits on `main`. That is the shape of a team
  routing around a red money gate, not of a finished product.

Every other candidate is downstream of a pound reaching a connector:

| Candidate | Why it loses to D-155 |
|---|---|
| Legal entity + authored ToS (`web/src/lib/config.ts:46`, `:50` — `TODO(launch): confirm the registered Ltd` / `confirm` **still present on `origin/main` today**) | A real launch gate, but it is **counsel's decision, not an engineering ship item**. Engineering effort does not move it. |
| 7 open non-dependabot PRs — #185 DoS (admin search), #186 XSS (JSON-LD), #187 N+1, #188 auth rate-limiting, #189/#190 mass-comms perf, #191 wizard visual test | Genuine hygiene, worth a batch merge — but none is on the path of a pound reaching a connector. Correct **filler after** the gate is green. |
| "e2e harness is broken" (a standing belief in the docs) | **Dead — resolved by time.** `web-e2e-realstack` `success` 2026-08-13. Do not spend on it; correct the doc line instead. |

### Diagnosis to start from (code-grounded, verified on `origin/main` today)

D-155 names two candidate aborts (hold expired vs open Polly circuit) but does **not** disambiguate
them. `ProcessStripePayoutAsync` already leaves durable markers that disambiguate **without touching
production code**:

- `SettlementActivities.cs:232` → `if (captureOutcome == CaptureOutcome.HoldExpired)` →
  `:240` `CompensateHoldExpiredToVoidAsync` (defined `:807`) → ledger shows **VOID**, state `Voided`.
- `SettlementActivities.cs:34` → `PayoutInitiatedMarker = "PAYOUT_INITIATED"`, written at `:259`
  **before** the Stripe transfer.
- `SettlementActivities.cs:324` → the `EntryType = "PAYOUT"` row (what the smoke waits for).

So the ledger at timeout **is** a three-way decision procedure:

| Ledger at timeout | Bounty state | Verdict |
|---|---|---|
| `ESCROW_DEPOSIT` + `VOID` | `Voided` | hold expired → capture-side problem |
| `ESCROW_DEPOSIT` + `PAYOUT_INITIATED`, no `PAYOUT` | `AutoSettled` | transfer attempted and threw → Stripe TEST balance / open circuit |
| `ESCROW_DEPOSIT` only | `AutoSettled` | aborted before the marker → circuit open at capture |

**HYPOTHESIS (unproven — do not pre-commit to a fix):** row 2 or 3, driven by an open Polly breaker,
is likeliest; the escrow PI is funded fresh seconds earlier, so a 7-day manual-capture hold expiring
mid-run is implausible. **Confirm or kill by running step 1** — do not skip to a fix.

**Step 1 of D-155's own trigger is still not done** — verified today:
`SmokeApiClient.WaitForLedgerEntryAsync` (`SmokeApiClient.cs:409-422`) returns the ledger **silently**
at the deadline (`:417-418` → `if (DateTime.UtcNow >= deadline) return ledger;`) with **no dump** of
entry types, bounty state, or PI status. Nine weeks on, the cheapest decisive gate has not been run.

**Compounding harness defect (fix in the same change):** that same loop calls `AdminSweepAsync()`
every 3s for the whole window (`SmokeApiClient.cs:419-420`) — ~60 sweeps at a 180s default. D-141
documents exactly this as harmful: with the breaker open, a sweep CLAIMs terminal state (Phase-2
commit) but cannot complete Phase-3, **manufacturing real `AutoSettled`-missing-`PAYOUT` recon
imbalances**. The diagnostic loop is plausibly manufacturing the very pollution it then fails on.

### Ordered plan

1. **Instrument the failure (test-only, zero production change).** On `WaitForLedgerEntryAsync`
   timeout, dump entry types + `bounty.state` + Stripe PI status into the assertion message.
2. **Run the gate once** against `tie-smoke`; read the dump; pick the row in the table above.
3. **Fix what the dump names**, keeping the change inside the smoke harness/env if at all possible:
   fresh PI per run so the hold cannot be pre-expired; assert breaker-closed and TEST **available**
   balance ≥ transfer amount as **fail-fast pre-conditions that abort before money moves**;
   isolate/purge smoke-DB state via a `#if SMOKE` seam (D-141 item 2), **never** a live sweep.
4. **Re-run to `Failed: 0  Skipped: 0` twice consecutively**, then flip D-155 closed and log it
   (BUILD-STATUS row + DEPLOY-LOG entry **in the same commit** — repo `CLAUDE.md` write-time rule).
5. **Then** land E31 (unblocked by definition) and batch-merge the 7 hygiene PRs (#185–#191).
6. Only after step 4 is a manual single-operator settlement or an auto-settle flip permissible.

**Non-goals:** do not relax the gate; do not `Skip` the payout leg; do **not** add `Category=golden`
to the payout test to make it appear in the nightly (it needs the D-68 seed and real TEST balance —
that buys a **false green**); do not flip `Settlement__AutoSettleEnabled`; do not run a live
`/v1/admin/settlement/sweep` against prod or smoke to "drain" state.

---

## 2. Acceptance test

**Ground truth for the objective.** Done when this passes **twice consecutively** from a fresh
`main` worktree, with `tie-smoke` rebuilt from that same source:

```bash
cd ~/Documents/code/the-introduction-exchange/dotnet && \
TIE_SMOKE_BASE_URL="$SMOKE_URL" TIE_SMOKE_ADMIN_TOKEN="$SMOKE_ADMIN_TOKEN" \
TIE_SMOKE_STRIPE_SECRET="$STRIPE_SECRET_KEY" TIE_SMOKE_WEBHOOK_SECRET="$SMOKE_STRIPE_WEBHOOK_SECRET" \
TIE_SMOKE_ENABLE_PAYOUT=1 \
dotnet test tests/Tie.SmokeTests \
  --filter "FullyQualifiedName~MoneyLoopSmokeTests|FullyQualifiedName~IdentityKycSmokeTests"
```

Verdict = exit 0 **and** `Failed: 0, Skipped: 0` with the payout leg among the passes. **A `Skipped`
payout leg is a FAIL, not a pass** — `deploy/fly/deploy.sh:138-142` records exactly this lesson:
without the webhook secret the money journeys `[SkippableFact]`-skip and `dotnet test` **exits 0 on
an all-skipped run — "a SILENT FALSE GREEN"** (WR-053); `:191` hard-fails the gate on
`skipped != 0`. Equivalent one-shot: `deploy/fly/deploy.sh verify` (release gate 1/2 + 2/2).

This gate is **not** free or side-effect-free — it consumes Stripe TEST balance and writes to
`tie-smoke` — so it is not a poll-every-loop probe. That cost is exactly why step 1 (self-diagnosing
timeout) must come before any re-run.

**Acceptance test for *this* diagnosis pass** (read-only, no network, no cost):

```bash
f="$HOME/.hermes/reports/project-next-tie.md"; test -f "$f" && grep -q 'D-155' "$f" && \
grep -q 'PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles' "$f" && \
grep -q '^## 1\. The one objective' "$f" && grep -q '^## 2\. Acceptance test' "$f" && \
grep -q '^## 3\. Files to touch' "$f" && grep -q '^## 4\. Risks' "$f" && \
test -f "$HOME/.hermes/reports/project-next-tie.prior-d155-2026-08-13.md" && \
test -z "$(git -C "$HOME/Documents/code/the-introduction-exchange" status --porcelain -- dotnet web scripts deploy docs)"
```

---

## 3. Files to touch

Expected blast radius is **test-harness only**. Production money code should not need to change
unless step 2's dump proves a defect in it — in which case **stop and escalate** (see §4 R1).

| File | Change |
|---|---|
| `dotnet/tests/Tie.SmokeTests/SmokeApiClient.cs:409-422` | `WaitForLedgerEntryAsync`: emit a diagnostic bundle (entry types, bounty state, PI status) on timeout instead of returning silently at `:417-418`; back off and **cap** the sweep cadence at `:419-420` (D-141 hazard). |
| `dotnet/tests/Tie.SmokeTests/MoneyLoopSmokeTests.cs:80-118` | Payout leg: assert on the diagnostic bundle so the failure message names the abort cause; add fail-fast pre-conditions (breaker closed, TEST available balance ≥ transfer amount) **before** money moves. |
| `dotnet/tests/Tie.SmokeTests/SmokeConfig.cs` | Only if a genuinely new knob is needed (e.g. a balance floor); `SettleWaitSeconds` and `TIE_SMOKE_ENABLE_PAYOUT` already exist. |
| `dotnet/src/Tie.Api/Smoke/SmokeEndpoints.cs` | Only if isolation needs a `#if SMOKE` purge/reset seam (D-141 item 2 prefers this over a live sweep). Smoke-only surface, kept out of prod by `SmokeShimAbsentFromProdTests`. |
| `deploy/fly/deploy.sh` (`run_money_smoke`, ~`:130-193`) | Only if the gate invocation needs the new pre-condition wiring. Do not weaken the `skipped != 0` die at `:191`. |
| `docs/backlog/LAUNCH-DEFERRALS.md` (D-155, D-141, D-157), `docs/backlog/BUILD-STATUS.md`, `docs/infrastructure/DEPLOY-LOG.md` | Write-time ledger obligations per the repo's `CLAUDE.md` — flip the rows **in the same commit** that lands the work. Also correct the stale "e2e harness broken" line (§0 proves it false). |

**Do NOT touch** unless step 2 proves a defect there, and then only inside the D-99 Claude fence:
`dotnet/src/Tie.Infrastructure/Introductions/SettlementActivities.cs` — the double-pay guard
(`:188`, `:196`) and the `PAYOUT_INITIATED` marker (`:34`, `:259`) are load-bearing.

---

## 4. Risks

- **R1 — the dump may indict production code, not the harness.** If the diagnostic names a defect in
  `ProcessStripePayoutAsync`, this stops being a test fix and becomes a **money-rail change**:
  Claude-owned inside the D-99 fence, founder-visible, per the routing ladder. Stop and escalate;
  do not patch through.
- **R2 — the gate costs real Stripe TEST balance and mutates `tie-smoke`.** Re-runs are not free and
  not idempotent-by-default. This is why instrumentation precedes re-running; budget the runs.
- **R3 — false green is the dominant failure mode here, not red.** Two documented mechanisms already
  exist: `[SkippableFact]` all-skip exiting 0 (WR-053, `deploy.sh:138-142`) and a nightly filter that
  structurally cannot select the payout test (§0). Any "fix" that makes the gate pass without a
  `PAYOUT` ledger row is worse than the current red.
- **R4 — the diagnostic loop may be manufacturing its own failure.** ~60 `AdminSweepAsync()` calls
  per run against an open breaker is the exact D-141 pollution mechanism; if the sweep cadence is not
  capped in the same change, step 2's dump may describe damage the harness caused.
- **R5 — 61 days of drift.** `main` has not moved since 2026-06-13 while 33 PRs accumulated. Expect
  merge friction on E31 and #185–#191 **after** the gate is green; do not attempt them first to
  "build momentum" — they do not move a pound to a connector.
- **R6 — the legal gate is still open in parallel** (`web/src/lib/config.ts:46,50` `TODO(launch)`).
  A green money rail does not make the product launchable on its own; that item needs counsel and
  should be started on the founder's clock, not engineering's.

---

*Generated 2026-08-14. All file:line references verified against `origin/main` @ `0c77d8b` on that
date via `git show origin/main:<path>`; CI/PR facts via `gh run list` / `gh pr list`.*
