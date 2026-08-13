# Introduction Exchange — product next-move (read-only diagnosis, 2026-07-31)

**Scope of this pass:** read-only inspection of `~/Documents/code/the-introduction-exchange`
(README, STATUS.md, docs/backlog, DEPLOY-LOG, LAUNCH-DEFERRALS, smoke/settlement source, git log
and branch topology). **No code was changed and no PR was opened.**

**Repo state (live, re-derived):** `main` HEAD = `1e55b55` (2026-06-13, "docs: log tie-web v103
deploy"). The repo has been quiet since 2026-06-13 (~7 weeks). The primary checkout sits on
`feat/e33-004-kycgate`, which is **75 commits behind `main`** (`git rev-list --left-right --count
main...feat/e33-004-kycgate` → `75  3`) — see Risk R3.

---

## 1. The one objective

**Make the connector-payout leg of the money+identity release smoke prove an end-to-end payout —
i.e. close D-155 — so the platform can actually pay a connector.**

Concretely: turn `MoneyLoopSmokeTests.PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles`
from deterministic RED to green (`Failed:0 Skipped:0 Passed:3` on the `deploy.sh` release gate 1/2),
by first making its timeout **self-diagnosing** (dump ledger + bounty state) and then fixing whatever
that dump names.

### Why this and not anything else

The marketplace's economic promise is *money in escrow → introduction happens → **connector gets
paid***. Money **in** is proven; money **out** has never been proven once:

- `docs/backlog/LAUNCH-DEFERRALS.md:164` (D-155): the payout smoke failed **2/2 identical runs** with
  `payout.ValueKind == Undefined` at `MoneyLoopSmokeTests.cs:107` — an auto-settled bounty produced
  **no PAYOUT ledger row**. Filed explicitly as "**deterministic, NOT a flake**"; the D-141
  env-flake hypothesis "was tested and rejected"; and the leg "**has never had a clean pass**".
- `docs/infrastructure/DEPLOY-LOG.md` (2026-06-12, tie-api v40 / tie-web v102) states the
  prod-risk consequence in the founder's own log: "prod settles via the SAME
  `ProcessStripePayoutAsync`, so the payout path is **currently UNVERIFIED end-to-end** … **do NOT
  perform a manual single-operator settlement, and do NOT flip auto-settle ON, until this smoke is
  green**."
- D-155's unblock trigger is marked **"(hard, do BEFORE the next money deploy / any manual
  settlement / any auto-settle flip)"**.

So the cage that keeps prod safe (`Settlement__AutoSettleEnabled` OFF) is simultaneously the thing
that stops a beta introduction from ever completing. **Every other candidate is downstream of this
one:**

| Candidate | Why it loses to D-155 |
|---|---|
| Legal entity + authored ToS copy (`web/src/lib/config.ts:46-51`, still `TODO(launch)` — verified live) | Real gate, but it is **counsel's decision, not an engineering ship item**; it does not become shippable by working harder. |
| E33-006 Pact coverage for onboarding/payouts (`docs/backlog/BUILD-STATUS.md:312`, `todo`) | Contract coverage for a path whose *runtime* is unproven. Wrong order. |
| Two known-red main tests (`WR045_ShadowQueueTests.Market_Heat_Reflects_Peers_And_Active_Briefs`, `PactVerificationTests.Provider_Honours_The_TieMobile_Contract` — both still present on `main`) | Real, but neither blocks a single pound reaching a connector. |
| Unmerged branch backlog (e.g. `worktree-payment-ux-sweep` 13 commits, `docs/d83-d115-launch-runbooks` 11) | Merge hygiene; no marketplace capability is gated on it. |
| GitHub Actions billing block | Founder-only billing fix; documented in DEPLOY-LOG v103. Not agent-shippable. |

### The diagnosis the fix should start from (code-grounded)

D-155 lists two candidate aborts (hold expired vs open Polly circuit) but does not disambiguate.
Reading `dotnet/src/Tie.Infrastructure/Introductions/SettlementActivities.cs` (on `main`), the
existing durable markers already disambiguate **without touching production code** —
`ProcessStripePayoutAsync` (line 75) runs:

- Phase 2 CLAIM → `AutoSettled` committed in its own tx (line 115);
- Phase 2a capture → on `CaptureOutcome.HoldExpired` it calls `CompensateHoldExpiredToVoidAsync`
  and returns (lines 232-241) → **ledger shows VOID, state `Voided`**;
- PR-3 marker → `PAYOUT_INITIATED` (const at line 34) is committed **before** the transfer (line 245);
- Phase 2b transfer, then Phase 3 writes `PAYOUT` + `PLATFORM_FEE` (line 307).

Therefore the timeout ledger is a three-way decision procedure:

| Ledger at timeout | State | Verdict |
|---|---|---|
| `ESCROW_DEPOSIT` + `VOID` | `Voided` | hold expired → capture-side problem |
| `ESCROW_DEPOSIT` + `PAYOUT_INITIATED`, no `PAYOUT` | `AutoSettled` | transfer attempted and threw → Stripe TEST balance / open circuit (D-141 a/b) |
| `ESCROW_DEPOSIT` only | `AutoSettled` | Phase 2a/2b threw before the marker → circuit open at capture |

**HYPOTHESIS (state it as unproven until the dump runs):** the third or second row, driven by an open
Polly breaker, is the likeliest — the escrow PI is funded fresh seconds earlier in
`DriveToBridgeActive`, so a 7-day manual-capture hold expiring mid-run is implausible. Confirm/kill
by running step 1 below; do not pre-commit to a fix.

**Compounding harness defect found while reading (worth fixing in the same change):**
`SmokeApiClient.WaitForLedgerEntryAsync` (`dotnet/tests/Tie.SmokeTests/SmokeApiClient.cs:409-422`)
calls `AdminSweepAsync()` **every 3s for the whole 180s window** (~60 sweeps). D-141
(`LAUNCH-DEFERRALS.md:150`) documents exactly this as harmful: "**Do NOT try to drain the backlog by
driving `/v1/admin/settlement/sweep`** … with the breaker open the sweep CLAIMs terminal state
(Phase-2 commit) but cannot complete Phase-3 … converting stale `BridgeActive` bounties into **real
`AutoSettled-missing-PAYOUT` … recon imbalances**". The diagnostic loop is plausibly manufacturing
the very pollution it then fails on. Add backoff / a sweep cap and stop sweeping once the breaker is
known open.

### Ordered plan

1. **Instrument the failure (test-only).** On `WaitForLedgerEntryAsync` timeout, dump entry types +
   `bounty.state` + the Stripe PI status into the assertion message. Zero production-code change.
2. **Run the gate once** against `tie-smoke` and read the dump → pick the row in the table above.
3. **Fix what the dump names**, keeping the change inside the smoke harness/env if at all possible
   (fresh PI per run; assert the circuit is closed and the TEST *available* balance ≥ £720 as a
   pre-condition that **fails fast** instead of burning a run; isolate/purge smoke-DB state per D-141
   item (2), never via a live sweep).
4. **Re-run to `Failed:0 Skipped:0 Passed:3` twice consecutively**, then flip D-155 to closed and log
   it (BUILD-STATUS row + DEPLOY-LOG entry, per repo CLAUDE.md write-time rule).
5. Only then is a manual single-operator settlement or an auto-settle flip permissible.

**Non-goals:** do not relax the gate, do not `Skip` the payout leg, do not flip
`Settlement__AutoSettleEnabled`, do not run a live `/v1/admin/settlement/sweep` against prod or
smoke to "drain" state.

---

## 2. Acceptance test

The ship item is done when this passes twice consecutively from a checkout of `main`, with the
`tie-smoke` stack rebuilt from that same source:

```bash
cd ~/Documents/code/the-introduction-exchange/dotnet && \
TIE_SMOKE_BASE_URL="$SMOKE_URL" TIE_SMOKE_ADMIN_TOKEN="$SMOKE_ADMIN_TOKEN" \
TIE_SMOKE_STRIPE_SECRET="$STRIPE_SECRET_KEY" TIE_SMOKE_WEBHOOK_SECRET="$SMOKE_STRIPE_WEBHOOK_SECRET" \
TIE_SMOKE_ENABLE_PAYOUT=1 \
dotnet test tests/Tie.SmokeTests \
  --filter "FullyQualifiedName~MoneyLoopSmokeTests|FullyQualifiedName~IdentityKycSmokeTests"
```

Verdict = exit 0 **and** `Failed: 0, Skipped: 0` with the payout leg among the passes (a `Skipped`
payout leg is a FAIL — it means `TIE_SMOKE_ENABLE_PAYOUT`/`PayoutTestAccountId` was unset, which is
how this leg stayed invisible). Equivalent one-shot: `deploy/fly/deploy.sh verify` (release gate 1/2
+ 2/2, `deploy.sh:196-209`). Note: this **is** the mandated gate but it is **not** free or
side-effect-free — ~£720 of Stripe TEST balance per run and it writes to `tie-smoke` — so it is not
a poll-it-every-loop probe.

**Acceptance test for *this* diagnosis pass** (read-only, no network, live-derived):

```bash
f="$HOME/.hermes/reports/project-next-tie.md"; test -f "$f" && grep -q 'D-155' "$f" && \
grep -q 'PayoutBranch_ProvenConnectorSilence_PaysConnector_StripeTransfer_Reconciles' "$f" && \
grep -q '^## 1\. The one objective' "$f" && grep -q '^## 2\. Acceptance test' "$f" && \
grep -q '^## 3\. Files to touch' "$f" && grep -q '^## 4\. Risks' "$f" && \
test -z "$(git -C "$HOME/Documents/code/the-introduction-exchange" status --porcelain -- dotnet web scripts deploy docs)"
```

---

## 3. Files to touch

Expected blast radius is **test-harness only**; production money code should not need to change
unless step 2's dump proves a defect in it (in which case stop and escalate — see R1).

| File | Change |
|---|---|
| `dotnet/tests/Tie.SmokeTests/SmokeApiClient.cs:409-422` | `WaitForLedgerEntryAsync`: return/emit a diagnostic bundle (entry types, bounty state) on timeout; back off the sweep cadence and cap sweeps (D-141 hazard above). |
| `dotnet/tests/Tie.SmokeTests/MoneyLoopSmokeTests.cs:~100-115` | Payout leg: assert on the diagnostic bundle so the failure message names the abort cause; add the fail-fast pre-conditions (circuit closed, TEST available balance ≥ transfer amount). |
| `dotnet/tests/Tie.SmokeTests/SmokeConfig.cs:13-31` | Only if a new knob is genuinely needed (e.g. a balance floor); `SettleWaitSeconds` default 180 and `TIE_SMOKE_ENABLE_PAYOUT` already exist. |
| `dotnet/src/Tie.Api/Smoke/SmokeEndpoints.cs:115+` | Only if isolation needs a `#if SMOKE` purge/reset seam (D-141 item 2 explicitly prefers this over a live sweep). Smoke-only surface. |
| `deploy/fly/deploy.sh:176-181` | Only if the gate invocation itself needs the new pre-condition wiring. |
| `docs/backlog/LAUNCH-DEFERRALS.md` (D-155, D-141 items 1-3), `docs/backlog/BUILD-STATUS.md`, `docs/infrastructure/DEPLOY-LOG.md` | Write-time ledger obligations from the repo's `CLAUDE.md` — flip the rows in the same commit that lands the work. |

**Do NOT touch** (unless step 2 proves a defect there, and then only inside the D-99 Claude fence):
`dotnet/src/Tie.Infrastructure/Introductions/SettlementActivities.cs` — the PR-3 double-pay guard
and the `PAYOUT_INITIATED` marker are load-bearing and already covered by
`tests/Tie.IntegrationTests/Production/PayoutDoublePayGuardTests.cs`.

---

## 4. Risks

- **R1 — the dump may prove a real payout defect, not an env defect.** D-155's triage calls the
  env explanation "most likely", which is a hypothesis, not a result. If the dump shows
  `PAYOUT_INITIATED` present with a *successful* Stripe transfer and no `PAYOUT` row, that is a
  settle-without-ledger divergence on the same path prod uses → stop, escalate (money rail,
  D-99 fence: Claude-owned, Fable-escalation candidate per the routing ladder), do not "fix the
  test".
- **R2 — running the gate is expensive and stateful.** ~£720 of Stripe TEST available balance per
  run, and TEST PaymentIntents land in *pending*, so the balance does not self-replenish
  (D-141 item a). Budget runs; make pre-conditions fail fast **before** money moves.
- **R3 — stale primary checkout.** The working copy is on `feat/e33-004-kycgate`, 75 commits behind
  `main`. Building `tie-smoke` or reading source from it reproduces the v39 hazard the DEPLOY-LOG
  already records ("not the stale primary checkout, which sits on `feat/e33-004-kycgate`"). Work
  from a fresh `main` worktree.
- **R4 — the diagnostic loop can worsen state.** Per D-141, sweeping with the breaker open converts
  stale `BridgeActive` bounties into genuine recon imbalances. Any repeated-sweep instrumentation
  must be capped, and smoke-DB cleanup must be a purge/isolation seam, never a live sweep.
- **R5 — no CI safety net.** GitHub Actions is org-billing-blocked (DEPLOY-LOG v103: checks fail in
  ~2s at runner-start), so this change lands without CI. Run `dotnet test` locally and state the
  counts in the PR; do not infer green from a red-for-billing-reasons run.
- **R6 — no local .NET SDK on this machine.** Verified live: `which dotnet` → not found. Whoever
  executes needs the SDK plus the gitignored `deploy/fly/.env.deploy` creds; this diagnosis pass
  could not and did not run the suite.
- **R7 — 7-week gap.** Nothing has landed since 2026-06-13. Stripe TEST state, the `tie-smoke` app,
  and the prod cage should all be re-probed live before trusting any of the June-dated numbers above
  (the June facts here are cited from files read today, not re-executed).
