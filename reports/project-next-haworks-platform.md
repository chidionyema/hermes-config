# Project Next — Haworks Platform

**Inspected:** 2026-08-14 (read-only; this file fully overwrites the 2026-08-06 edition, whose currency had never been re-derived)
**Repo:** `~/Documents/code/haworks-platform`
**Branch:** `main`
**HEAD:** `74a992f5` (2026-07-31, `fix(scripts): unpin the retired claude-sonnet-4 model`)
**Working tree over the affected paths:** clean — `git status --porcelain -- src/Privacy src/Contracts/Privacy tests/Privacy` returns nothing, so no in-flight WIP addresses any of this.

---

## 1. The one objective

**Separate GDPR Export from Erasure in the Privacy saga, so an Export request can never trigger erasure.**

Today a user who exercises their Article 15 right of access — asking for a copy of their data — has their account irreversibly anonymized instead. The type they requested is captured, persisted, then silently dropped on the wire and overwritten with `"Erasure"`. Four receipts, all re-read at HEAD `74a992f5` this run:

1. **The type is dropped at the publish boundary.**
   `src/Privacy/Privacy.Application/Requests/Commands/InitiateRequest/InitiatePrivacyRequestCommand.cs:14` declares `record InitiatePrivacyRequestCommand(Guid UserId, PrivacyRequestType Type, ...)` and line 61 persists it via `PrivacyRequest.Create(request.UserId, request.Type)` — but line 67 publishes `new InitiatePrivacyRequestMessage { RequestId = ..., UserId = ... }` with **no Type**, because `src/Contracts/Privacy/InitiatePrivacyRequestMessage.cs` carries only `RequestId` and `UserId`. The user's choice never leaves the handler.

2. **The saga then hardcodes erasure.**
   `src/Privacy/Privacy.Application/Requests/Sagas/PrivacyRequestStateMachine.cs:38` — `context.Saga.RequestType = "Erasure"; // PR-06` — unconditionally, and line 44 `.PublishAsync(context => context.Init<PrivacyErasureRequested>(...))` fires the erasure fan-out regardless of what was asked for. `src/Privacy/Privacy.Domain/Enums/PrivacyRequestType.cs` defines `{ Export, Erasure }`; the saga honours exactly one of them.

3. **The export path is orphaned.**
   `rg -ln 'PrivacyDataExportRequested' src tests -g '*.cs' | wc -l` returns **1** — the sole hit is its own declaration, `src/Contracts/Privacy/PrivacyDataExportRequested.cs`. Nothing publishes it and nothing consumes it. The three consumers — `src/Identity/Identity.Application/Consumers/PrivacyErasureRequestedConsumer.cs`, `src/Orders/Orders.Application/Consumers/PrivacyErasureRequestedConsumer.cs`, `src/Payments/Payments.Application/Consumers/PrivacyErasureRequestedConsumer.cs` — contain zero occurrences of `Type` or `Export` (`rg -n 'Type|Export'` on each: no matches). They anonymize with no branching whatsoever.

4. **The status API cannot reveal the substitution.**
   `src/Privacy/Privacy.Application/Requests/Queries/GetErasureStatus/GetErasureStatusQuery.cs:69` returns `Type: PrivacyRequestType.Erasure` as a literal. A user polling their "export" sees `Erasure` — or, more likely, is never given a reason to look.

`git log -5 -- src/Privacy src/Contracts/Privacy` shows the most recent touch as `b8434667` (2026-05-22, privacy SQL enum type mismatch). Nothing since. This is not drifting toward a fix on its own.

This is one shippable change, scoped to the conflation bug.

---

## 2. Acceptance test

**The test that must go from absent to passing:** an integration test under `tests/Privacy/Privacy.Integration` asserting that `POST /api/v{version}/privacyrequests` with `Type = "Export"` results in:

- **no `PrivacyErasureRequested` publish** (assert against the MassTransit test harness — `harness.Published.Any<PrivacyErasureRequested>()` must be false), and
- **no anonymization in Identity, Orders or Payments** — the three consumers must not have been invoked, and the corresponding rows must be intact after the saga settles.

Route confirmed at `src/Privacy/Privacy.Api/Controllers/PrivacyRequestsController.cs:14` — `[Route("api/v{version:apiVersion}/[controller]")]` — with `[HttpPost]` at line 28.

Run it with:

```bash
cd ~/Documents/code/haworks-platform
dotnet test tests/Privacy/Privacy.Integration/Privacy.Integration.csproj \
  --filter "FullyQualifiedName~ExportDoesNotTriggerErasure"
```

**No such guard exists today, and that absence is part of the defect.** `tests/Privacy` contains exactly three projects — `Privacy.Architecture`, `Privacy.Integration`, `Privacy.Unit` — and `rg -ln 'ExportDoesNotTriggerErasure' tests` returns nothing (exit 1). The only integration coverage of the saga is `tests/Privacy/Privacy.Integration/PrivacyStateMachineTests.cs`, which exercises the erasure path that the code hardcodes; it therefore passes *because of* the bug, not in spite of it.

---

## 3. Files to touch

| File | Change |
|---|---|
| `src/Contracts/Privacy/InitiatePrivacyRequestMessage.cs` | Add the request `Type` to the wire contract (see Risk (i) on the default) |
| `src/Contracts/Privacy/PrivacyErasureRequested.cs` | Carry the type through the fan-out event |
| `src/Privacy/.../InitiateRequest/InitiatePrivacyRequestCommand.cs:67` | Stop dropping `request.Type` when publishing the message |
| `src/Privacy/.../Sagas/PrivacyRequestStateMachine.cs:38,44` | Branch on `Type`; set `Saga.RequestType` from the message instead of the literal `"Erasure"`; publish `PrivacyDataExportRequested` on the Export branch |
| `src/Privacy/.../Queries/GetErasureStatus/GetErasureStatusQuery.cs:69` | Derive `Type` from the saga; stop hardcoding `PrivacyRequestType.Erasure` |
| `src/Privacy/Privacy.Api/Controllers/PrivacyRequestsController.cs` | Reject `Type = Export` with **501 Not Implemented** until the export path is genuinely wired end-to-end — so that in the interim nothing silently erases |
| `tests/Privacy/Privacy.Integration/` | New test file(s) for the §2 acceptance test |

The 501 is the load-bearing part of the interim state: a rejected export is a bad user experience, an accepted one is an irreversible data loss.

---

## 4. Risks

**(i) In-flight sagas must still deserialize.** Sagas created under the current no-Type contract are already persisted. The new field needs a backward-compatible default of `Erasure`, or an explicit drain step before deploy. A `required` init-only property on the message record would break replay of existing outbox rows.

**(ii) The second CRITICAL in the same controller is deliberately NOT bundled.** `PrivacyRequestsController.cs:40` carries an open `// TODO: enforce privacy:erase claim once claim infrastructure is provisioned (PLATFORM-SEC-12)`, and the scope check below it logs `"IDOR risk: privacy erasure initiated by service {InitiatingService} without privacy:erase scope ... Proceeding (enforcement pending PLATFORM-SEC-12)"` and then proceeds, rather than returning `Forbid`. Fixing it would newly 403 every service caller that lacks the `privacy:erase` scope. That is a cross-service coordination decision, not a code decision — it belongs to whoever can enumerate and update the callers.

**(iii) There is no regression guard on the Privacy service today.** The diff must stay scoped to the conflation bug. No opportunistic saga refactor — there is nothing to catch a mistake if one is introduced alongside.

**(iv) The integration test needs the local Docker/Aspire stack** (Postgres + RabbitMQ) per `docs/GETTING-STARTED.md`. **Not exercised during this read-only inspection** — the acceptance criterion in §2 is specified, not yet run.

---

*This inspection made zero code changes and opened no PR. The only file written this run is this report.*
