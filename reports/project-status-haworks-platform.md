# Project Status — Haworks Platform

_Generated 2026-06-22 · Source: `graphify-out/` knowledge graph (built 2026-06-21) + git evidence_
_Repo: `~/Documents/code/haworks-platform` · branch `main` · HEAD `e87d2581`_
_Read-only status report — no code changes made._

## Current State

Haworks Platform is a **large .NET 9 microservices estate** (Clean Architecture, MassTransit EF Core
Inbox/Outbox, financial-grade rules). The graph indexed **14,922 nodes / 22,657 edges across 1,527
communities** at 99% extraction confidence — a mature, heavily-built codebase.

**26 services** under `src/`: Ai, Analyzers, Audit, BffWeb, BuildingBlocks(.Testing), Catalog,
CheckoutOrchestrator, Contracts, Identity, Localization, Location, Media, Merchant, Notifications,
Orders, Payments, Payouts, Pricing, Privacy, Realtime, RulesEngine, Scheduler, Search, Shipping,
Webhooks.

**Core abstractions (god nodes, most-connected):** `PlatformGuardTests` (137 edges — the
architectural-guard suite is the central enforcement point), `Haworks.BuildingBlocks` (83) and
`Haworks.BuildingBlocks.Testing` (66 — shared testing/container infra is the cross-cutting spine),
`Haworks.Contracts` (47 — integration contract layer), `Payments Service` (39), `AuditableEntity`
(38), `Settings` (38). Healthy shape for the domain: shared building-blocks + a strong
architectural-guard test layer hold service boundaries together.

**Recent git activity is CI/review-pipeline hardening, not feature work.** Last 6 commits (newest
2026-06-19) are all `fix(...)`: removed Polly v7-compat `ResiliencePolicyFactory`; bash 4+ re-exec
for launchd runners; review-runner quoting + LOW-severity inclusion; smoke tests moved post-deploy
against live Fly; BffWeb checkout line-item mapping; Audit partition/idempotency test fixes. The
project is in a **stabilization / autonomous-review phase**, not active feature delivery.

**Uncommitted working-tree drift (45 paths) — in-progress refactor, not a clean tree.** 26 modified
`.cs` files concentrated in Application command/query layers (Catalog, Identity, Orders, Payments
PayPal, Search) plus `BuildingBlocks/Common/Error.cs` and Vault wiring; 1 deleted test
(`StripeCheckoutResilienceTests.cs` — consistent with the Polly-removal commit); 18 untracked paths
including new `Catalog.Domain/Errors/`, `Vault/VaultErrors.cs`, the `graphify-out/` artifacts, and
9 new dated review reports under `docs/reviews/` (Audit, BffWeb, Catalog, CheckoutOrchestrator,
Identity, Realtime, RulesEngine, Scheduler). This reads as a typed-domain-`Errors` error-handling
refactor mid-flight.

## Top 3 Next Actions

1. **Resolve the 45-path uncommitted refactor.** A typed-domain-`Errors` refactor (new
   `Catalog.Domain/Errors/`, `VaultErrors.cs`, edits across Identity/Orders/Payments/Search
   Application layers) plus a deleted resilience test sit uncommitted on `main`. Per repo policy
   (branch + PR, never push main, max 3 services/PR, mandatory pre-push build+test), triage it:
   build + test the touched services, then split into PRs — or revert if it is stray
   autonomous-pipeline output. Uncommitted work on `main` is the highest-risk drift.

2. **Decide the fate of `graphify-out/`** (currently untracked, ~15 MB `graph.json`). Track it as a
   deliverable or add it to `.gitignore` so the knowledge graph stops surfacing as drift on every
   status check.

3. **Close out the autonomous review backlog.** 9 new `docs/reviews/*` reports (2026-06-19→06-22)
   were generated but their findings aren't folded back / committed. Land the validated fixes and
   archive the reports so the review pipeline's output is captured rather than accumulating as
   untracked noise.

## Blockers

- **No hard code blocker identified from the graph.** Extraction was clean (99%); no functional
  defect is visible from graph + git alone.
- **Structural-debt signals (not blocking):** the graph flags **4,950 isolated nodes** — notably the
  entire `Content.*` service (Api/Application/Domain/Infrastructure/Unit) is weakly connected,
  possibly orphaned or undocumented — plus **232 thin communities**. Community cohesion is low
  (0.03–0.12), expected for a 26-service estate but worth a modularity pass. Two self-loop import
  cycles in `src/Ai/app/` (`main.py`, `recommendation_service.py`).
- **Verification gap:** this report is graph + git only — it does **not** assert build/test green.
  Before the uncommitted refactor (Action 1) is committed, the repo's mandatory pre-push gate
  (`dotnet build HaworksPlatform.sln` + filtered `dotnet test`) must pass; the current pass/fail
  state of the working tree is unknown.

---
_Evidence: `graphify-out/GRAPH_REPORT.md` (God Nodes, Knowledge Gaps, Communities); `git log
--oneline -20`; `git status --short` (45 paths). No files in the Haworks Platform repo were
modified._
