# Introduction Exchange — product next-move (read-only diagnosis, 2026-08-13)

**Scope of this pass:** read-only inspection of `~/Documents/code/the-introduction-exchange`
(STATUS.md, docs/backlog, LAUNCH-DEFERRALS, DEPLOY-LOG, smoke/settlement source, CI workflows,
`gh pr list`, `gh run list`) plus a `git fetch` to get true remote state. **No code was changed, no
branch was checked out, no PR was opened.** The only writes were to this report and its archive.

**Prior pass:** `project-next-tie.prior-d155-2026-07-31.md` (archived alongside this file). It named
the same objective. This pass **re-derived it independently and confirms it**, and corrects four of
its facts that have since gone stale — see §0.

**Repo state (re-derived today):** true `origin/main` = `0c77d8b` (2026-06-13 18:30 UTC, "docs: log
tie-web v107 deploy"). **60 days quiet** — zero commits since 2026-06-13. The local clone was
**13 commits behind** the real remote before this pass fetched (it read `1e55b55`/v103 as the tip;
the prior report inherited that error). The primary checkout still sits on `feat/e33-004-kycgate`
@ `1e49f10` — behind `main` and dirty. Live prod per the last deploy log: `tie-api` **v41** ·
`tie-web` **v107**, money cage ON (`Settlement__AutoSettleEnabled` OFF).

---

## 0. What changed since the 2026-07-31 pass (all verified today)

| Prior claim | Status now | Evidence |
|---|---|---|
| R5 "no CI safety net — Actions org-billing-blocked" | **STALE — CI is running and green** | `gh run list --branch main --limit 12` → 12/12 `completed success`, 2026-08-12/13, incl. `golden-journeys` 6m0s and `web-e2e-realstack` 20m9s on 2026-08-13. |
| "e2e harness broken on `main`, 5/5 runs fail identically" (`DEPLOY-LOG.md:814`) | **STALE — that doc line is now wrong** | `web-e2e-realstack (real browser → real backend)` `completed success` `2026-08-13T05:53:20Z`. |
| `main` tip = `1e55b55` (v103) | **Wrong — clone was stale** | true `origin/main` = `0c77d8b` (v107), 13 commits ahead. |
| "repo quiet ~7 weeks" | Now **60 days** | `origin/main` last commit `2026-06-13 18:30 UTC`. |

**The trap this creates, and the single most important line in this report:** an all-green CI
dashboard today is **not** evidence D-155 is fixed. The nightly `golden-journeys` job runs
`--filter "Category=golden&Quarantine!=true"` (`.github/workflows/golden-journeys-ci.yml:98-99`),
and the payout test is a bare `[SkippableFact]` with **no `Category` trait**
(`MoneyLoopSmokeTests.cs:80-81`) — so that filter *cannot* select it. The golden money journey is
explicitly the **void** branch only: `GoldenJourneys.cs:32` — "money / settlement (**void branch** —
always runnable; **payout needs the D-68 seed, covered by MoneyLoopSmokeTests**)" — and
`GoldenJourneys.cs:57` asserts the ledger `.NotContain("PAYOUT")`. **Green CI proves money can be
refunded. Nothing in CI has ever proven money can be paid out.**

---

## 1. The one objective

**Close D-155: make the connector-payout leg of the money+identity release smoke prove an end-to-end
payout, so the platform can actually pay a connector.**

Concretely: turn
`MoneyLoopSmokeTests.PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles`
(`MoneyLoopSmokeTests.cs:81`) from deterministic RED to green (`Failed:0 Skipped:0 Passed:3` on
release gate 1/2), by first making its timeout **self-diagnosing** and then fixing what the dump
names.

### Why this and not anything else

The marketplace's economic promise is *money in escrow → introduction happens → **connector gets
paid***. Money **in** is proven; money **out** has never been proven once.

- `LAUNCH-DEFERRALS.md:164` (D-155): the payout smoke failed **2/2 identical runs** with
  `payout.ValueKind == Undefined` — an auto-settled bounty produced **no PAYOUT ledger row**. Filed
  explicitly as "**deterministic, NOT a flake**"; the D-141 env-flake hypothesis "was tested and
  rejected"; the leg "**has never had a clean pass**".
- Its unblock trigger is marked **"(hard, do BEFORE the next money deploy / any manual settlement /
  any auto-settle flip)"**, and prod risk is stated in the founder's own log
  (`DEPLOY-LOG.md:137`): "prod settles via the SAME `ProcessStripePayoutAsync`, so the payout path is
  **currently UNVERIFIED end-to-end** … **do NOT perform a manual single-operator settlement, and do
  NOT flip auto-settle ON, until this smoke is green**."
- **It is what froze the product.** Every one of the last five deploys (v103, v104, v105, v106,
  v107) is web-only and each log entry says the money gate was *correctly not run*
  (`DEPLOY-LOG.md:40,43,57,71,86,102`). The E31 money-config spine is finished code sitting unmerged
  purely because of this: `E31-money-config-single-source.md:49` — "not merged — **D-155
  money-smoke gate RED blocks the prod deploy, not the code**". D-157 and D-160 are also explicitly
  gated on it. 60 days of zero commits is the shape of a team routing around a red gate.

So the cage that keeps prod safe is simultaneously the thing that stops a beta introduction from
ever completing. Every other candidate is downstream:

| Candidate | Why it loses to D-155 |
|---|---|
| Legal entity + authored ToS (`web/src/lib/config.ts:46-51`, `TODO(launch)` — **still present today**) | Real launch gate, but it is **counsel's decision, not an engineering ship item**. Working harder does not make it shippable. |
| 7 open non-dependabot PRs (#185-#191: XSS, admin-search DoS, auth rate-limiting, N+1, perf) — all opened 2026-06-14, all still open | Genuine hygiene and worth a batch merge, but none is on the path of a pound reaching a connector. Low-risk filler once the gate is green. |
| Two known-red main tests (`WR045_ShadowQueueTests…`, `PactVerificationTests.Provider_Honours_The_TieMobile_Contract`) | Real, but neither blocks settlement. |
| Unmerged branch backlog (`worktree-payment-ux-sweep`, `docs/d83-d115-launch-runbooks`) | Merge hygiene; the money-relevant part of it *is* E31, which is blocked by D-155 anyway. |
| Fix the "broken e2e harness" standing gap | **Already resolved by time** — see §0. Do not spend on it. |

### Diagnosis to start from (code-grounded, re-verified on `origin/main` today)

D-155 names two candidate aborts (hold expired vs open Polly circuit) but does not disambiguate.
`SettlementActivities.ProcessStripePayoutAsync` (line **75**) already leaves durable markers that
disambiguate **without touching production code**:

- Phase 2a capture → on `CaptureOutcome.HoldExpired` (line **232**) it calls
  `CompensateHoldExpiredToVoidAsync` (line **240**, defined line **807**) and returns → ledger shows
  **VOID**, state `Voided`.
- PR-3 → `PayoutInitiatedMarker = "PAYOUT_INITIATED"` (line **34**) committed **before** the transfer
  (line **245**).
- Phase 3 → writes `PAYOUT` + `PLATFORM_FEE` rows (lines **324-325**; D-155 cites 324).

So the timeout ledger is a three-way decision procedure:

| Ledger at timeout | State | Verdict |
|---|---|---|
| `ESCROW_DEPOSIT` + `VOID` | `Voided` | hold expired → capture-side problem |
| `ESCROW_DEPOSIT` + `PAYOUT_INITIATED`, no `PAYOUT` | `AutoSettled` | transfer attempted and threw → Stripe TEST balance / open circuit |
| `ESCROW_DEPOSIT` only | `AutoSettled` | Phase 2a/2b threw before the marker → circuit open at capture |

**HYPOTHESIS (unproven — do not pre-commit to a fix):** row 2 or 3, driven by an open Polly breaker,
is likeliest; the escrow PI is funded fresh seconds earlier, so a 7-day manual-capture hold expiring
mid-run is implausible. Confirm or kill by running step 1.

**Step 1 of D-155's own unblock trigger is still not done** — verified today on `origin/main`:
`SmokeApiClient.WaitForLedgerEntryAsync` (`SmokeApiClient.cs:409-422`) returns the ledger silently at
the deadline (`if (DateTime.UtcNow >= deadline) return ledger;`, line 417-418) with **no dump of
entry types, bounty state, or PI status**. Six weeks on, the cheapest decisive move has not been
taken.

**Compounding harness defect (fix in the same change):** that same loop calls `AdminSweepAsync()`
every 3s for the whole window (line 419) — ~60 sweeps at the 180s default. D-141
(`LAUNCH-DEFERRALS.md:150`) documents exactly this as harmful: with the breaker open a sweep CLAIMs
terminal state (Phase-2 commit) but cannot complete Phase-3, **manufacturing real
`AutoSettled`-missing-`PAYOUT` recon imbalances**. The diagnostic loop is plausibly manufacturing the
very pollution it then fails on.

### Ordered plan

1. **Instrument the failure (test-only, zero production change).** On `WaitForLedgerEntryAsync`
   timeout, dump entry types + `bounty.state` + Stripe PI status into the assertion message.
2. **Run the gate once** against `tie-smoke`; read the dump; pick the row in the table above.
3. **Fix what the dump names**, keeping the change inside the smoke harness/env if at all possible:
   fresh PI per run so the hold cannot be pre-expired; assert the breaker is closed and TEST
   *available* balance ≥ transfer amount as **fail-fast pre-conditions** that abort before money
   moves; isolate/purge smoke-DB state via a `#if SMOKE` seam (D-141 item 2), **never** a live sweep.
4. **Re-run to `Failed:0 Skipped:0 Passed:3` twice consecutively**, then flip D-155 closed and log it
   (BUILD-STATUS row + DEPLOY-LOG entry, same commit — repo `CLAUDE.md` write-time rule).
5. **Then** land E31 (unblocked by definition) and batch-merge the 7 open hygiene PRs.
6. Only after step 4 is a manual single-operator settlement or an auto-settle flip permissible.

**Non-goals:** do not relax the gate, do not `Skip` the payout leg, do not add `Category=golden` to
the payout test to make it appear in the nightly (it needs the D-68 seed and £-real TEST balance —
that would buy a false green), do not flip `Settlement__AutoSettleEnabled`, do not run a live
`/v1/admin/settlement/sweep` against prod or smoke to "drain" state.

---

## 2. Acceptance test

Done when this passes **twice consecutively** from a fresh `main` worktree, with `tie-smoke` rebuilt
from that same source:

```bash
cd ~/Documents/code/the-introduction-exchange/dotnet && \
TIE_SMOKE_BASE_URL="$SMOKE_URL" TIE_SMOKE_ADMIN_TOKEN="$SMOKE_ADMIN_TOKEN" \
TIE_SMOKE_STRIPE_SECRET="$STRIPE_SECRET_KEY" TIE_SMOKE_WEBHOOK_SECRET="$SMOKE_STRIPE_WEBHOOK_SECRET" \
TIE_SMOKE_ENABLE_PAYOUT=1 \
dotnet test tests/Tie.SmokeTests \
  --filter "FullyQualifiedName~MoneyLoopSmokeTests|FullyQualifiedName~IdentityKycSmokeTests"
```

Verdict = exit 0 **and** `Failed: 0, Skipped: 0` with the payout leg among the passes. **A `Skipped`
payout leg is a FAIL**, not a pass — `deploy.sh:136-141` records exactly this lesson: without the
webhook secret both MoneyLoop branches `[SkippableFact]`-skip and `dotnet test` **exits 0 on an
all-skipped run — a SILENT FALSE GREEN that would ship a broken rail**. Equivalent one-shot:
`deploy/fly/deploy.sh verify` (release gate 1/2 + 2/2). This gate is **not** free or side-effect-free
— ~£720 of Stripe TEST balance per run (`DEPLOY-LOG.md:102`) and it writes to `tie-smoke` — so it is
not a poll-every-loop probe. That cost is exactly why step 1 (self-diagnosing timeout) comes before
any rerun.

**Acceptance test for *this* diagnosis pass** (read-only, no network, no cost):

```bash
f="$HOME/.hermes/reports/project-next-tie.md"; test -f "$f" && grep -q 'D-155' "$f" && \
grep -q 'PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles' "$f" && \
grep -q '^## 1\. The one objective' "$f" && grep -q '^## 2\. Acceptance test' "$f" && \
grep -q '^## 3\. Files to touch' "$f" && grep -q '^## 4\. Risks' "$f" && \
test -f "$HOME/.hermes/reports/project-next-tie.prior-d155-2026-07-31.md" && \
test -z "$(git -C "$HOME/Documents/code/the-introduction-exchange" status --porcelain -- dotnet web scripts deploy docs)"
```

---

## 3. Files to touch

Expected blast radius is **test-harness only**. Production money code should not need to change
unless step 2's dump proves a defect in it — in which case **stop and escalate** (see R1).

| File | Change |
|---|---|
| `dotnet/tests/Tie.SmokeTests/SmokeApiClient.cs:409-422` | `WaitForLedgerEntryAsync`: emit a diagnostic bundle (entry types, bounty state, PI status) on timeout instead of returning silently at line 417-418; back off and **cap** the sweep cadence at line 419 (D-141 hazard). |
| `dotnet/tests/Tie.SmokeTests/MoneyLoopSmokeTests.cs:81-118` | Payout leg: assert on the diagnostic bundle so the failure message names the abort cause; add fail-fast pre-conditions (breaker closed, TEST available balance ≥ transfer amount) **before** money moves. |
| `dotnet/tests/Tie.SmokeTests/SmokeConfig.cs` | Only if a genuinely new knob is needed (e.g. a balance floor); `SettleWaitSeconds` and `TIE_SMOKE_ENABLE_PAYOUT` already exist. |
| `dotnet/src/Tie.Api/Smoke/SmokeEndpoints.cs` | Only if isolation needs a `#if SMOKE` purge/reset seam (D-141 item 2 explicitly prefers this over a live sweep). Smoke-only surface, absent from prod by `SmokeShimAbsentFromProdTests`. |
| `deploy/fly/deploy.sh` (`run_money_smoke`, line 130+) | Only if the gate invocation needs the new pre-condition wiring. |
| `docs/backlog/LAUNCH-DEFERRALS.md` (D-155, D-141, D-157), `docs/backlog/BUILD-STATUS.md`, `docs/infrastructure/DEPLOY-LOG.md` | Write-time ledger obligations per the repo's `CLAUDE.md` — flip the rows in the **same commit** that lands the work. Also correct `DEPLOY-LOG.md:814` (the e2e-broken claim is now false — see §0). |

**Do NOT touch** unless step 2 proves a defect there, and then only inside the D-99 Claude fence:
`dotnet/src/Tie.Infrastructure/Introductions/SettlementActivities.cs` — the PR-3 double-pay guard
(line 175-188) and the `PAYOUT_INITIATED` marker (line 34/245) are load-bearing.

---

## 4. Risks

- **R1 — the dump may prove a real payout defect, not an env defect.** D-155 calls the env
  explanation "most likely", which is a hypothesis, not a result. If the dump shows
  `PAYOUT_INITIATED` present with a *successful* Stripe transfer and no `PAYOUT` row, that is a
  settle-without-ledger divergence on the same path prod uses → **stop, escalate** (money rail, D-99
  fence, Claude-owned; Fable-escalation candidate per the routing ladder). Do not "fix the test".
- **R2 — running the gate is expensive and stateful.** ~£720 of Stripe TEST available balance per run
  (`DEPLOY-LOG.md:102`), and TEST PaymentIntents land *pending*, so balance does not self-replenish.
  Budget the runs; make pre-conditions fail fast before money moves. This is why step 1 precedes any
  rerun.
- **R3 — stale, dirty primary checkout.** It sits on `feat/e33-004-kycgate` @ `1e49f10`, behind
  `main`, with modified/untracked `.worktrees/` and `consensus/runs/` entries. `DEPLOY-LOG.md:104`
  already warns: "the primary checkout sits on stale `feat/e33-004-kycgate`, do **not** deploy from
  it." Work from a fresh `main` worktree. Also `git fetch` first — the clone was 13 commits stale
  today and the prior report drew a wrong `main` tip from it.
- **R4 — the diagnostic loop can worsen state.** Per D-141, sweeping with the breaker open converts
  stale `BridgeActive` bounties into genuine recon imbalances. Cap the sweeps; clean up via a
  purge/isolation seam, never a live sweep.
- **R5 — a green CI dashboard will lie to you here.** Nightly `golden-journeys` and
  `web-e2e-realstack` are green (2026-08-13) and cover the **void/refund** branch only
  (`GoldenJourneys.cs:32,57`; workflow filter `Category=golden`, which the payout `[SkippableFact]`
  does not carry). Do not read "all checks green" as "payout works". *(This supersedes the prior
  report's R5, which said CI was billing-blocked — that is fixed.)*
- **R6 — no local .NET SDK on this machine.** Verified today: `which dotnet` → `dotnet not found`.
  Whoever executes needs the SDK plus the gitignored `deploy/fly/.env.deploy` creds. **This pass did
  not and could not run the .NET suite or the smoke gate.**
- **R7 — 60-day gap.** Nothing has landed since 2026-06-13. Stripe TEST balance, the `tie-smoke` app,
  and the prod cage should be re-probed live before trusting any June-dated number here — those are
  cited from files read today, not re-executed. Live prod HTTP probing was **attempted and denied**
  by sandbox permission in this pass; the closest evidence obtained is the
  `recon-uptime-monitor (external dead-man's-switch)` workflow, `completed success` at
  `2026-08-13T05:56:50Z`.
