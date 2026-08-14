# RitualWorks — Next Ship Item (rewritten 2026-08-14)

**Headline: there is no product ship item in this repo. `~/Documents/code/ritualworks`
is the frozen reference monolith for `haworks-platform`, not an active product.**
The highest-leverage move is to stop filing product work against it, and to make the
45 local-only commits durable before this laptop is the only copy.

This report supersedes the 2026-08-06 version, which recommended implementing
`IEmailSender` (transactional order/receipt email) in this repo. That recommendation
was wrong on both premises — see "Why the previous plan is retired" below.

## Evidence gathered (all re-derived live on 2026-08-14)

| Fact | Source |
|---|---|
| `ritualworks` and the archived `haworks` repo share root commit `c6fcf1558d7a` — same monolith lineage | `git -C ~/Documents/code/{ritualworks,haworks} rev-list --max-parents=0 HEAD` |
| `haworks` is already `status: archived`, "Original Haworks repo — superseded by haworks-platform"; `ritualworks` is still `status: active` with description "Ritual/ceremony planning platform" | `~/.hermes/projects.json` |
| Monolith HEAD `9b90bd9`, dated **2026-05-09** — no commits in 3 months | `git -C ~/Documents/code/ritualworks log -1 --format=%ci` |
| `haworks-platform` HEAD `74a992f5`, dated **2026-07-31**, 985 commits, 16 services, CI + Fly.io deploy | `git -C ~/Documents/code/haworks-platform log -1`; `haworks-platform/README.md:3` |
| **ADR-0009 (Accepted 2026-05-02): "The existing monolith is a reference, not a source… It stays in its current repo, untouched, never modified, never imported from."** | `docs/microservices-migration/adr/0009-monolith-as-reference-not-source.md:12` |
| **ADR-0008 (Accepted 2026-05-02): "The existing monolith is a portfolio prototype with no live users, no traffic, and no rollback urgency."** | `docs/microservices-migration/adr/0008-clean-slate-greenfield.md:12` |
| HEAD is 45 commits ahead of `origin/main` on branch `port/queries-sweep`, and that branch **has no remote** — the work exists only on this machine | `git rev-list --count origin/main..HEAD` → 45; `git branch -r --list 'origin/port*'` → empty |
| Email/notifications already ship in the live platform | `haworks-platform/src/Notifications/Notifications.Infrastructure/Channels/Email/SendGrid/SendGridEmailProvider.cs`, `.../Email/EmailChannelGateway.cs` |

## Why the previous plan is retired

The 2026-08-06 report proposed building `IEmailSender` + order-confirmation/receipt
email in `src/Infrastructure/Messaging/Consumers/*.cs`. Its gap analysis was correct —
those TODOs are real (`OrderCreatedConsumer.cs:50`, `OrderCompletedConsumer.cs:51`,
`PaymentVerifiedConsumer.cs:52`) — but both of its justifying premises are false:

1. It argued "a live e-commerce platform that takes real payments and sends zero
   confirmation email is a product-trust gap." ADR-0008 records the opposite in the
   founder's own words: **no live users, no traffic**. There is no customer to fail.
2. It planned edits to `src/` in a repo ADR-0009 declares **untouched, never modified**.
   Doing that work would have violated an accepted ADR.
3. The capability it proposed building already exists in the product that ships:
   the Notifications service with a SendGrid provider and email channel gateway.

Building it here would have cost real hours and shipped nothing to a user.

## (1) The one objective

**Retire `ritualworks` as an active product line and make its unpushed history durable —
one push, one registry edit — so every future product cycle lands on `haworks-platform`.**

Two parts, one objective:

- **Durability.** Push `port/queries-sweep` (45 commits: Flow B reservation checkout
  `4543b46`, portfolio integration `2bce234`, distributed-tracing demo `f45c3de`,
  stage-1 VPS deploy `9e43afb`, testing rules `9b90bd9`) to `origin`. ADR-0009 says the
  monolith "stays in its current repo" as a reference — a reference that exists on one
  laptop and nowhere else is not a reference. This is a `git push` of existing commits:
  **no source file is edited, no ADR is violated.**
- **Routing.** Flip the `ritualworks` entry in `~/.hermes/projects.json` to
  `status: "archived"` with an accurate description, matching the treatment its own
  sibling `haworks` already has. Its `objectives` array (currently the recurring
  "product next-move" prompt) is what caused this repo to be re-diagnosed monthly and
  produced the wrong email plan; emptying it stops the loop at the source.

Do **not** create a replacement objective on `haworks-platform` — it already has its own
active entry and its own `~/.hermes/reports/project-next-haworks-platform.md`.

## (2) Acceptance test

Single read-only command; exit 0 == done:

```sh
sh -c 'R="$HOME/Documents/code/ritualworks"; \
  git -C "$R" ls-remote --exit-code --heads origin port/queries-sweep >/dev/null 2>&1 && \
  [ "$(python3 -c "import json;print([p for p in json.load(open(\"$HOME/.hermes/projects.json\"))[\"projects\"] if p[\"key\"]==\"ritualworks\"][0][\"status\"])")" = "archived" ] && \
  [ -z "$(git -C "$R" diff --name-only -- "*.cs")" ]'
```

Three live checks, no cached logs: the branch exists on the remote; the registry says
archived; not one `.cs` file was modified in the process.

## (3) Files to touch

| File | Change |
|---|---|
| `~/.hermes/projects.json` — `ritualworks` entry | `status: "active"` → `"archived"`; `description` → "Reference monolith for haworks-platform (ADR-0009) — frozen 2026-05-09, superseded"; empty the `objectives` array |
| `~/Documents/code/ritualworks` | **`git push -u origin port/queries-sweep` only.** Zero file edits. |
| `~/.hermes/reports/project-next-ritualworks.md` | This file — final entry for this project |

Explicitly **not** touched: any `src/**` or `tests/**` file in the monolith (ADR-0009),
`haworks.sln`, and every `IEmailSender` TODO — those stay as reference markers.

## (4) Risks

- **Losing the 45 commits by acting in the wrong order.** Push *first*, archive second.
  If the registry is archived while the branch is still local-only, the repo drops off
  the estate's radar with three months of unbacked work on one disk. *Mitigation:* the
  acceptance test checks the remote branch before it checks the registry.
- **Pushing a branch may trigger CI.** `.github/` workflows exist in this repo and have
  not run since May; a push could fire a workflow against a stale toolchain and page on
  a red build. *Mitigation:* expect that failure and don't treat it as a regression — the
  repo is a reference and its CI gates nothing that ships. `dotnet` is not on PATH in
  this estate's non-interactive shell (`which dotnet` → not found), so no local build
  gate is available either.
- **Someone later re-reads the monolith's TODOs and rebuilds shipped capability.** This
  already happened once (the email plan). *Mitigation:* the description change names
  ADR-0009 in the registry itself, where the next agent reads it before opening the repo.
- **Low risk of being wrong about the product boundary.** If `haworks-platform` were ever
  abandoned and the monolith revived, this is reversible in one JSON edit — nothing is
  deleted, no history is rewritten.
- **Out of scope by instruction:** this run made no code changes and opened no PR. The
  push and the registry edit above are the *plan*, awaiting execution.
