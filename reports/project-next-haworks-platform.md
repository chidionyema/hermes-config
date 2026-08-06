# Haworks Platform — Next Ship Item

**Generated:** 2026-08-06 (read-only inspection of `~/Documents/code/haworks-platform`, branch `main` @ `74a992f5`)

## 1. The one objective

**Fix the GDPR Export→Erasure conflation in the Privacy service: a user who requests a data
*export* currently has their account data silently, permanently erased instead.**

This is not a hypothetical. It was independently diagnosed and then re-validated (0 false positives,
0 downgrades) by the platform's own continuous-review pipeline one day before this inspection:
- `docs/reviews/Privacy/2026-08-05-2222.md` (original, 8 findings, 3 CRITICAL)
- `docs/reviews/Privacy/2026-08-05-2222-validated.md` (independent re-verification, all 8 confirmed)

It is rated the #1 most urgent finding in that review (ahead of the IDOR-on-erasure finding and the
`UseDeveloperExceptionPage()`-in-prod finding, both also CRITICAL and still open). Nothing in
`git log` since `2026-08-05-2222` (HEAD is `74a992f5`, dated `2026-07-31`) touches the Privacy
service, and `git status --short` shows no uncommitted changes under `src/Privacy/` — so this is
still live on disk as of this inspection.

**Root cause (verified by reading the exact lines):**
- `InitiatePrivacyRequestMessage` (`src/Contracts/Privacy/InitiatePrivacyRequestMessage.cs:3-7`) and
  `PrivacyErasureRequested` (`src/Contracts/Privacy/PrivacyErasureRequested.cs:3-7`) both carry only
  `RequestId`/`UserId` — **no `Type` field**, even though `InitiatePrivacyRequestCommand` accepts and
  validates `PrivacyRequestType { Export, Erasure }`.
- `PrivacyRequestStateMachine.cs:38` unconditionally does `context.Saga.RequestType = "Erasure";` and
  line 44 publishes `PrivacyErasureRequested` — regardless of what the user actually asked for.
- All three downstream consumers (Identity, Orders, Payments `PrivacyErasureRequestedConsumer`)
  unconditionally anonymize/delete data on receipt, with zero type branching.
- `PrivacyDataExportRequested` (`src/Contracts/Privacy/PrivacyDataExportRequested.cs`) exists as a
  contract but has **zero** publish/consume references anywhere in `src/` — a real export path was
  never wired up.
- `GetErasureStatusQuery.cs:69` also hardcodes `Type: PrivacyRequestType.Erasure` in the status DTO,
  so even the status API can't reveal the mistake to the caller.

**Why this is the single highest-leverage next ship item** (not a status essay — this is the
concrete comparison): the Privacy service handles GDPR Article 15/17 obligations for a real
marketplace platform. Every other open item in this repo (the review-pipeline tooling churn visible
in the last ~25 commits, the 27-file uncommitted WIP removing a legacy `ResiliencePolicyFactory`, the
sole product-code `TODO` at `PrivacyRequestsController.cs:40`) is either internal tooling or a
narrower blast-radius bug. This one is reachable through the documented public API with no special
privilege, is irreversible (data erasure, not a 500 or a bad response), and is legally load-bearing.
The review pipeline itself already gave this service a 3/10 health score specifically because this
and the related IDOR finding are both open.

## 2. Acceptance test

No automated test currently guards this behavior — that absence is itself part of the bug (per the
review, the export path is "genuinely orphaned"). The acceptance test for the fix is:

```
dotnet test tests/Privacy --filter "FullyQualifiedName~ExportDoesNotTriggerErasure" && \
dotnet test tests/Identity --filter "FullyQualifiedName~PrivacyErasureRequestedConsumer" && \
dotnet test tests/Orders --filter "FullyQualifiedName~PrivacyErasureRequestedConsumer" && \
dotnet test tests/Payments --filter "FullyQualifiedName~PrivacyErasureRequestedConsumer"
```

Concretely, the fix must make a **new** integration test pass:
`POST /api/v{v}/privacyrequests` with `Type: "Export"` must NOT cause
`PrivacyErasureRequestedConsumer` to fire in Identity/Orders/Payments, and must not anonymize any
user row. Until a real export pipeline exists, the fix may instead make the API reject
`Type: Export` with `501 Not Implemented` — either way, the test asserts erasure consumers are
never invoked for an Export request. (This test doesn't exist yet; writing it is part of the fix,
per the review's own recommendation.)

## 3. Files to touch

- `src/Contracts/Privacy/InitiatePrivacyRequestMessage.cs` — add `PrivacyRequestType Type` field.
- `src/Contracts/Privacy/PrivacyErasureRequested.cs` — add `PrivacyRequestType Type` field (or leave
  erasure-only and introduce a real `PrivacyDataExportRequested` publish path instead).
- `src/Privacy/Privacy.Application/Requests/Commands/InitiateRequest/InitiatePrivacyRequestCommand.cs:67`
  — pass `Type` through when publishing `InitiatePrivacyRequestMessage`.
- `src/Privacy/Privacy.Application/Requests/Sagas/PrivacyRequestStateMachine.cs:38,44` — branch on
  `context.Message.Type` instead of hardcoding `"Erasure"`; only publish `PrivacyErasureRequested`
  for `Type == Erasure`.
- `src/Privacy/Privacy.Application/Requests/Queries/GetErasureStatus/GetErasureStatusQuery.cs:69` —
  stop hardcoding `Type: PrivacyRequestType.Erasure`; derive from the real request type.
- `src/Privacy/Privacy.Api/Controllers/PrivacyRequestsController.cs` — until export is genuinely
  implemented end-to-end, reject `Type == Export` at the API layer with `501 Not Implemented` rather
  than letting it flow into the saga.
- New test file(s) under `tests/Privacy/Privacy.Integration/` and the three consumer test projects
  (`tests/Identity`, `tests/Orders`, `tests/Payments`) asserting Export never triggers erasure.

Related but separate (same file, second CRITICAL finding in the same review — worth bundling into the
same PR since it's the same controller and same review cycle, but is a distinct code change):
`PrivacyRequestsController.cs:47-61` — `if (!hasEraseScope)` currently logs a warning and proceeds
anyway instead of `return Forbid()`. Not counted as "the one objective" above because it requires a
product decision (see Risks) on whether service callers lose the ability to erase on behalf of users
until claim infrastructure (`PLATFORM-SEC-12`) ships — but flagging it here since fixing both in one
pass through this controller is the efficient sequencing.

## 4. Risks

- **Behavior change for the "Service" role erasure path is a separate, real tradeoff** (the IDOR
  finding above): making Export properly reject/branch does not itself require touching the
  `hasEraseScope` check, so it can ship independently and with lower risk than the IDOR fix, which
  would newly `403` any service caller that hasn't yet been issued a `privacy:erase` scope — that's
  a coordination risk across whichever services currently call this endpoint with a `Service`-role
  token, not a code risk. Scoping this ship item to Export/Erasure separation avoids that coordination
  cost while still closing the more severe of the two CRITICAL findings.
- **In-flight sagas**: any `PrivacyRequestState` sagas already in progress at deploy time were created
  under the old unconditional-erasure contract and won't have a `Type` on the wire for
  already-published messages — the fix needs the new `Type` field to default sanely (e.g. treat
  missing/absent as `Erasure` for backward compatibility with in-flight messages) or a drain/migration
  step, otherwise in-flight requests could fault on deserialization.
- **No test currently exists to regress against** — the fix is being written into an area the review
  pipeline rated 3/10, so changes here should be scoped tightly (this one conflation bug) rather than
  opportunistically refactoring the saga, to keep the diff reviewable and the blast radius small.
- **Verification dependency**: `dotnet test` requires the local Docker/Aspire stack (Postgres,
  RabbitMQ) per `docs/GETTING-STARTED.md`'s own quick-start — the acceptance test above assumes that
  environment is available; it was not exercised as part of this read-only inspection.
