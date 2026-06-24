# Project Status — The Introduction Exchange (TIE)

_Generated 2026-06-24 from the graphify knowledge graph (read-only, no code changes)._
_Re-verified 2026-06-24 against `graphify-out/` raw JSON — every headline number, god node, and surprise link below matches the graph on disk. Graph built 2026-06-21 12:46:38, `built_at_commit` = `1e49f105eba2ed9fc1fa75765adc7bd893effd20` = current HEAD `1e49f10` of `feat/e33-004-kycgate`. Confirmed directly from [graph.json](file:///Users/chidionyema/Documents/code/the-introduction-exchange/graphify-out/graph.json) / [.graphify_analysis.json](file:///Users/chidionyema/Documents/code/the-introduction-exchange/graphify-out/.graphify_analysis.json) / [manifest.json](file:///Users/chidionyema/Documents/code/the-introduction-exchange/graphify-out/manifest.json): 5,658 nodes / 8,683 links, 663 communities, 10 god nodes, 5 surprise links, 916 files, 654,762 in / 206,420 out tokens._

## Source of truth
- Repo: [/Users/chidionyema/Documents/code/the-introduction-exchange](file:///Users/chidionyema/Documents/code/the-introduction-exchange)
- Branch: `feat/e33-004-kycgate` · HEAD `1e49f10` (2026-06-12)
- Graph: [graphify-out/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/graphify-out) built 2026-06-21 12:46 — **5,658 nodes / 8,683 edges**, **916 files** graphified
- Analysis: **663 communities** detected, **10 god (hub) nodes**, **5 cross-domain "surprise" links**; build cost 654.8k in / 206.4k out tokens
- Working tree: 9 dirty entries — all under `.worktrees/` (parallel epic worktrees) plus the new `graphify-out/`; **no dirty source under `dotnet/`, `web/`, or `mobile/`**

## Codebase composition (by top-level dir)
| dir | what it is |
|---|---|
| [dotnet/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet) | .NET 9 modular monolith — core product + test suites (101 `*Tests.cs` files) |
| [web/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web) | Next.js/React web UI |
| [consensus/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/consensus) | multi-agent review/eval harness (claude/deepseek/gemini adapters + recorded runs) |
| [mobile/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/mobile) | Expo / React Native app |
| [go-spec/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/go-spec) | Go spec/contract artifacts |
| [scripts/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/scripts) [deploy/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/deploy) [launchd/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/launchd) | tooling + deploy |
| [docs/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/docs) [review/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/review) [path/](file:///Users/chidionyema/Documents/code/the-introduction-exchange/path) | specs, reviews, working notes |

## Architecture signal — top hub ("god") nodes
1. `ui_cx_cx` — [cx()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/components/ui/cx.ts) web class-name/util helper (degree **76**, most-connected node)
2. `tie_smoketests_smokeapiclient_smokeapiclient` — [SmokeApiClient](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.SmokeTests/SmokeApiClient.cs#L15) (38)
3. `context_authcontext_useauth` — frontend [useAuth()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/context/AuthContext.tsx#L91) auth context (38)
4. `components_seo_seo` — [Seo()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/components/Seo.tsx) (34); shared UI [Button()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/components/ui/Button.tsx) (32), [Card()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/components/ui/Card.tsx) (31), [useToast()](file:///Users/chidionyema/Documents/code/the-introduction-exchange/web/src/components/ui/Toast.tsx) (30)
5. **[MoneyReconciliationTests](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/MoneyReconciliationTests.cs#L31)** (30) + its `Task` node (29) — the only backend domain object in the top hubs

Load-bearing surfaces: **web auth/UI primitives**, the **smoke API client**, and the **money-reconciliation test seam**. That the money-reconciliation suite ranks among the top hubs means the money paths are exercised by many tests, not stubbed.

## Largest communities (theme by dominant member prefixes)
| # | size | cohesion | theme |
|---|---|---|---|
| 0 | 88 | 0.04 | `api` client + `api_types` (web ↔ backend contract surface) |
| 1 | 82 | 0.06 | `consensus` engine + agent adapters (review/eval harness) |
| 2 | 68 | 0.07 | `ui` component library + domain widgets |
| 3 | 67 | 0.07 | `tie_smoketests` + dotnet smoke tests |
| 4 | 64 | 0.06 | payment-gateway test doubles ([FakePaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/Infrastructure/FakePaymentGateway.cs#L11)/[FaultyPaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/Infrastructure/FaultyPaymentGateway.cs#L22)) |
| 8 | 48 | 0.08 | [StripePaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/src/Tie.Infrastructure/Gateways/StripePaymentGateway.cs#L21) (real Stripe gateway) |
| 11 | 43 | 0.10 | `domain` UI (blind proposal card, settlement timer, bounty timeline) |
| 12 | 43 | 0.17 | `tie_integrationtests` (fake alert/audit senders) — highest cohesion |
| 14 | 42 | 0.06 | dotnet `consumers` / messaging (bridge-activated notification consumers) |
| 15 | 38 | 0.07 | epic clusters E08 release / E09 disputes / E11 notifications |

## Money rail (the heart of the product — present in code AND under test)
The graph's "surprise" cross-domain links surface the spec design explicitly:
- **[PaymentRailPolicy.cs](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/src/Tie.Application/Common/PaymentRailPolicy.cs)** enforces the **CardHold rail** and marks **CardImmediate as forbidden** — the auth-hold-only rail of BountyIntro spec v1.3 is implemented, not aspirational.
- **[ReleaseOptions.cs](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/src/Tie.Application/Common/ReleaseOptions.cs)** links to the **"4 + 3 ≤ 7 window"** constraint (the timer window that supersedes ADR-004/006).
- Surface: [IPaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/src/Tie.Application/Common/Interfaces/IPaymentGateway.cs#L11) → real [StripePaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/src/Tie.Infrastructure/Gateways/StripePaymentGateway.cs#L21) (community 8) + [FakePaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/Infrastructure/FakePaymentGateway.cs#L11)/[FaultyPaymentGateway](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/Infrastructure/FaultyPaymentGateway.cs#L22) doubles (community 4); `PaymentRail` enum; exercised by [PaymentRailTests](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/Review/PaymentRailTests.cs#L29), [PaymentRailPolicyTests](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.UnitTests/PaymentRailPolicyTests.cs#L14), [MoneyReconciliationTests](file:///Users/chidionyema/Documents/code/the-introduction-exchange/dotnet/tests/Tie.IntegrationTests/MoneyReconciliationTests.cs#L31).
- Concept vocabulary matches spec v1.3: escrow/hold, non-refundable platform fee, reconciliation, stripe_connect, idempotency keys; identity: oidc_identity_binding, connector_standing, proven_connector, magic_link, kyc.

## Status read
- **Healthy & current:** graph matches HEAD; no source drift (dirty tree is worktrees + the graph output only). The full BountyIntro v1.3 surface is in code — money rail, escrow, OIDC identity, settlement, consensus harness.
- **Risk areas are the most-tested:** money reconciliation and payment-gateway suites are top-ranked hub/community nodes — money paths are exercised, not faked.
- **Active line of work:** branch `feat/e33-004-kycgate` → KYC gating, consistent with closing the standing-gated identity model (the connector-token identity hole flagged as the Phase-1 weak point in spec v1.3).
- **Watch:** epic clusters E08/E09/E11 share thinner integration coverage than the smoke/money suites; admin/ops ([ADMIN-FEATURES-GEMINI-SPEC.md](file:///Users/chidionyema/Documents/code/the-introduction-exchange/docs/backlog/ADMIN-FEATURES-GEMINI-SPEC.md)) is partly spec'd vs built — verify before acting.

## Risk / action taken
Read-only status report — **no source files changed**, risk class **low**. Acceptance: `test -s …/project-status-tie.md` passes (file non-empty). Money/identity code stays behind the founder fence for any actual edits.

## Suggested next objective (founder roadmap)
Close the connector-token identity hole on `feat/e33-004-kycgate` (KYC gate + OIDC binding), since the active branch and the spec's known weak point line up.
