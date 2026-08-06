# RitualWorks (haworks) — Next Ship Item

Repo: `~/Documents/code/ritualworks` (README calls the product "HaWorks", a .NET 9
e-commerce platform; directory name is `ritualworks`). Branch at inspection time:
`port/queries-sweep`, clean except untracked scratch dirs (`graphify-out/`,
`src/mock-docker/`, `tests/dummy/`) and OS/build noise (`.DS_Store`,
`src/obj/project.assets.json`, `src/obj/project.nuget.cache`).

Inspected: `readme.md`, `CLAUDE.md`, `git log` (last 30 commits), `docs/`,
TODO/FIXME grep across `src` + `tests`, skipped-test grep, and the actual
implementation status of everything the TODOs point at.

## (1) The one objective

**Implement real transactional email (order confirmation + payment receipt) —
currently `IEmailSender` does not exist anywhere in the codebase.**

Evidence this is a genuine, unimplemented gap, not just a stale comment:

- No interface, no class, no DI registration for anything named `IEmailSender`
  anywhere in `src/`:
  - `grep -rn "interface IEmailSender\|class.*EmailSender\|: IEmailSender" src` → **zero matches**.
  - `grep -rln "SendGrid\|MailKit\|SmtpClient\|AmazonSimpleEmail" src` → **zero matches**
    (only a comment mentioning SendGrid as an idea).
  - No `Smtp`/`SendGrid`/`EmailSettings` keys in any `*.json` config, no email
    secrets in `scripts/seed-vault-dev.sh`.
- Three consumers on the core order/payment path have the call **commented out**,
  each behind an identical TODO:
  - `src/Infrastructure/Messaging/Consumers/OrderCreatedConsumer.cs:50`
  - `src/Infrastructure/Messaging/Consumers/OrderCompletedConsumer.cs:51-56`
  - `src/Infrastructure/Messaging/Consumers/PaymentVerifiedConsumer.cs:52,55`
- `CriticalAlertService.cs:205` has the same TODO for ops-facing alert emails
  (secondary, not in scope for this ship item).
- What *does* exist is easy to mistake for this: `IUserEmailService` /
  `UserEmailService` (`src/Application/Interfaces/IUserEmailService.cs`,
  `src/Infrastructure/Identity/UserEmailService.cs`, registered at
  `src/Infrastructure/Extensions/DependencyInjection/BoundedContexts/IdentityBoundedContextExtensions.cs:187`)
  — that's ASP.NET Identity's email-confirmation/lookup service, unrelated to
  transactional commerce email. And `CheckoutNotificationConsumer.cs` only pushes
  SignalR progress events to the browser during checkout — nothing persists or
  reaches the customer's inbox once the tab is closed.
- The domain events already carry everything needed (`CustomerEmail` is present
  on `OrderCreatedEvent`, `OrderCompletedEvent`, `PaymentSessionRequestedEvent`,
  `ReservationConfirmedEvent`, `StockReservedEvent`), so this is a pure gap-fill,
  not a data-model change.

Why this over the alternatives seen in the repo:
- Recent work (`4543b46` Flow B reservation checkout, `2bce234` portfolio demo
  integration, `e9d5d88` "honest metrics") already made checkout/payment the
  active surface — shipping email closes the loop on that work rather than
  opening a new one.
- The microservices decomposition tracked in `docs/microservices-migration/`
  and flagged in `tests/haworks.Tests.Architecture/BoundedContextBoundaryTests.cs:310`
  is explicitly marked "pre-existing violation tracked separately" — it's a
  deliberate, larger, lower-urgency effort, not a dropped ball.
- A live e-commerce platform that takes real payments and sends **zero**
  confirmation or receipt email is a product-trust gap, not a nice-to-have —
  it's the most customer-visible thing currently broken.

## (2) Acceptance test

Ship is complete when:
- `IEmailSender` exists, has a concrete implementation, and is registered in DI.
- `OrderCreatedConsumer`, `OrderCompletedConsumer`, and `PaymentVerifiedConsumer`
  call it (no more commented-out TODO blocks).
- Unit tests cover the new sender and the three consumers' new email-sending path.

Read-only, single command, live-derived, exit 0 = done:

```bash
cd ~/Documents/code/ritualworks && \
grep -rq "interface IEmailSender" --include="*.cs" src && \
grep -rlq ": IEmailSender" --include="*.cs" src && \
! grep -rn "TODO: Add email sending when IEmailSender is implemented\|TODO: Add payment receipt email when IEmailSender is implemented" \
    src/Infrastructure/Messaging/Consumers/OrderCreatedConsumer.cs \
    src/Infrastructure/Messaging/Consumers/OrderCompletedConsumer.cs \
    src/Infrastructure/Messaging/Consumers/PaymentVerifiedConsumer.cs
```
(Exits 0 only once the interface exists, is implemented somewhere, and all three
TODO markers are gone from the consumer files — i.e. the calls were actually wired in.)

## (3) Files to touch

New:
- `src/Application/Interfaces/IEmailSender.cs` — interface, mirroring the shape
  of `src/Application/Interfaces/IUserEmailService.cs`. Methods:
  `SendOrderConfirmationAsync`, `SendPaymentReceiptAsync`, `SendOrderCompletionAsync`
  (or a single generic `SendAsync(template, to, data)` — decide based on how much
  templating is wanted for v1; start minimal).
- `src/Infrastructure/Notifications/SmtpEmailSender.cs` (or `SendGridEmailSender.cs`
  if an API-based provider is preferred over SMTP — no existing config points
  either way, so this is an open choice, not a constraint) — concrete implementation.
- `tests/haworks.Tests.Unit/Notifications/SmtpEmailSenderTests.cs` — new.

Edit:
- `src/Infrastructure/Messaging/Consumers/OrderCreatedConsumer.cs:50` — replace TODO with real call.
- `src/Infrastructure/Messaging/Consumers/OrderCompletedConsumer.cs:51-56` — replace TODO with real call.
- `src/Infrastructure/Messaging/Consumers/PaymentVerifiedConsumer.cs:52,55` — replace TODO with real call + metrics.
- `src/Infrastructure/Extensions/DependencyInjection/BoundedContexts/OrdersServiceExtensions.cs`
  or `PaymentsServiceExtensions.cs` — register `IEmailSender` (mirror the
  `services.AddScoped<IUserEmailService, UserEmailService>()` pattern at
  `IdentityBoundedContextExtensions.cs:187`).
- `tests/haworks.Tests.Unit/Consumers/` — extend existing consumer test files
  (or add new ones alongside `CheckoutNotificationConsumerTests.cs`) to assert
  the email call happens on the happy path and is swallowed/logged on failure
  (match the existing "non-critical, don't block the saga" pattern already used
  for SignalR notifications in `CheckoutNotificationConsumer.cs`'s `NotifySafelyAsync`).
- `scripts/seed-vault-dev.sh` — add dev SMTP/SendGrid secret placeholder if the
  chosen provider needs a credential locally.
- `readme.md` / `.claude/rules/` — one line noting email is now live, if the
  team documents infra additions there (optional, not blocking).

## (4) Risks

- **Provider choice is unmade.** No existing SMTP/SendGrid/SES config exists to
  copy, so the implementer must pick one (dev-friendly options: Mailhog/Mailpit
  via Docker for local dev, matching the existing "everything runs via
  Aspire/Docker locally" pattern in `readme.md`). This is a real decision, not
  just typing — see `human_decision_required` note below only if the estate
  wants to weigh in; otherwise default to SMTP+Mailpit for dev, swappable
  provider behind the interface for prod.
- **Consumers currently treat notification failure as non-critical** (see
  `CheckoutNotificationConsumer`'s `NotifySafelyAsync` swallow-and-log pattern).
  Email should follow the same rule — a flaky email provider must never fail or
  retry-storm the order/payment saga. Get this wrong and it becomes a new
  reliability bug on the checkout path this repo has clearly invested a lot in
  hardening (Flow B, saga stockRace, idempotency TTL work all visible in recent
  git log).
- **PII in logs.** Existing code already masks email in logs
  (`OrderCompletedConsumer.cs:48` uses `@event.CustomerEmail.MaskEmail()`) — the
  new sender must not accidentally log raw addresses or email body content.
- **No test infra for outbound email exists yet** — unit tests can mock
  `IEmailSender`, but there's no integration-test pattern (e.g. Mailpit
  Testcontainer) to verify real send/format; scope for this ship item should
  stay at unit-level + manual local verification, not require new
  integration-test infra as a blocker.
- **Scope creep risk:** `CriticalAlertService.cs:205`'s ops-alert email TODO is
  adjacent but a different concern (ops paging, not customer email) — do not
  fold it into this ship item; it can reuse `IEmailSender` later but isn't part
  of the acceptance test above.
