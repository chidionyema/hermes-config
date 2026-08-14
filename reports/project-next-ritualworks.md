# RitualWorks — Next Ship Item (re-verified 2026-08-14, third filing)

**Headline: unchanged from the 02:35 filing today, and now re-derived live.
`~/Documents/code/ritualworks` is the frozen reference monolith for `haworks-platform`,
not an active product. The plan below is still UNEXECUTED.** The highest-leverage move
is to make the 45 local-only commits durable and stop this repo from being re-diagnosed
every cycle.

This is the third product-next-move diagnosis filed against this repo. The first
(2026-08-06) proposed building `IEmailSender`; that was retired as wrong on its premises.
The second (2026-08-14 02:35) proposed the plan below. Nothing in it has been done —
which is itself the strongest evidence that the *objective*, not the *repo*, is the bug.

## Evidence — every line re-derived live on 2026-08-14, nothing from cache

| Fact | Live source |
|---|---|
| Monolith HEAD `9b90bd9`, dated **2026-05-09 21:11:35** — no commits in 3 months | `git -C ~/Documents/code/ritualworks log -1 --format='%ci %h %s'` |
| No commits on ANY branch in the last 14 days | `git -C … log --oneline --all --since=14.days` → empty |
| **45 commits ahead of `origin/main`** | `git -C … rev-list --count origin/main..HEAD` → `45` |
| **`port/queries-sweep` still has NO remote** — 7 remote heads exist (`main`, `compiling`, `refactor`, `feature/ha-portfolio-integration`, 3 dependabot); the current branch is not among them | `git -C … ls-remote --heads origin` |
| `ritualworks` is still `"status": "active"` in the registry, description `"Ritual/ceremony planning platform"`, with the recurring next-move prompt in `objectives[0]` | `~/.hermes/projects.json` |
| Sibling `haworks` is already `"status": "archived"`, `"archived_at": "2026-07-31"`, `"superseded_by": "haworks-platform"` — the precedent exists | `~/.hermes/projects.json` |
| `ritualworks` and `haworks` share root commit `c6fcf1558d7a` — literally the same lineage | `git -C {ritualworks,haworks} rev-list --max-parents=0 HEAD` |
| `haworks-platform` HEAD `74a992f5`, **2026-07-31**, 985 commits — that is the product that moves | `git -C ~/Documents/code/haworks-platform log -1; rev-list --count HEAD` |
| **ADR-0009 (Accepted): "The existing monolith is a reference, not a source. It stays in its current repo, untouched, never modified, never imported from."** | `docs/microservices-migration/adr/0009-monolith-as-reference-not-source.md`, `## Decision` |
| **ADR-0008: "The existing monolith is a portfolio prototype with no live users, no traffic, and no rollback urgency."** | `docs/microservices-migration/adr/0008-clean-slate-greenfield.md:12` |
| The three `IEmailSender` TODOs are real but are reference markers, not a backlog | `src/Infrastructure/Messaging/Consumers/OrderCreatedConsumer.cs:50`, `OrderCompletedConsumer.cs:51`, `PaymentVerifiedConsumer.cs:52` |
| No local build/test gate is available | `which dotnet` → not found |

Note the repo name is a legacy label: `readme.md:1` reads **"HaWorks - E-Commerce Platform"**,
not a ritual/ceremony platform. The registry description is stale on top of everything else.

## (1) The one objective

**Retire `ritualworks` as an active product line and make its unpushed history durable —
one push, one registry edit — so every future product cycle lands on `haworks-platform`.**

Two parts, one objective, in this order:

1. **Durability first.** `git push -u origin port/queries-sweep` — 45 commits that exist
   on exactly one disk: Flow B reservation checkout (`4543b46`), portfolio integration
   (`2bce234`), distributed-tracing demo (`f45c3de`), stage-1 VPS deploy (`9e43afb`),
   testing rules (`9b90bd9`). ADR-0009 says the monolith "stays in its current repo" as a
   reference; a reference that exists only on this laptop is not a reference. **This is a
   push of existing commits — no source file is edited, no ADR is violated.**
2. **Routing second.** Flip the `ritualworks` entry in `~/.hermes/projects.json` to
   `status: "archived"` (matching what the founder already did to `haworks` on 2026-07-31),
   fix the description, and **empty the `objectives` array** — that array is what has now
   caused three diagnoses of a frozen repo and one wrong plan.

Do **not** create a replacement objective on `haworks-platform`; it already has an active
entry and its own `~/.hermes/reports/project-next-haworks-platform.md`.

## (2) Acceptance test

Single read-only command; exit 0 == done. Three live checks — remote branch, registry
state, and no `.cs` file touched:

```sh
sh -c 'R="$HOME/Documents/code/ritualworks"; \
  git -C "$R" ls-remote --exit-code --heads origin port/queries-sweep >/dev/null 2>&1 && \
  python3 -c "import json,sys;d=json.load(open(\"$HOME/.hermes/projects.json\"));p=[x for x in d[\"projects\"] if x[\"key\"]==\"ritualworks\"][0];sys.exit(0 if p[\"status\"]==\"archived\" and not p.get(\"objectives\") else 1)" && \
  [ -z "$(git -C "$R" diff --name-only -- "*.cs")" ]'
```

## (3) Files to touch

| File | Change |
|---|---|
| `~/.hermes/projects.json` — `ritualworks` entry | `status: "active"` → `"archived"`; add `"archived_at": "2026-08-14"`, `"superseded_by": "haworks-platform"`; description → `"Reference monolith for haworks-platform (ADR-0009) — frozen 2026-05-09, superseded"`; `objectives: []` |
| `~/Documents/code/ritualworks` | **`git push -u origin port/queries-sweep` only. Zero file edits.** |
| `~/.hermes/reports/project-next-ritualworks.md` | This file — final entry for this project |

Explicitly **not** touched: any `src/**` or `tests/**` file (ADR-0009), `haworks.sln`, and
every `IEmailSender` TODO — those stay as reference markers. The working tree's existing
dirt (`.DS_Store`, `src/obj/*.json`, untracked `graphify-out/`, `src/mock-docker/`,
`tests/dummy/`) must **not** be committed as part of the push.

## (4) Risks

- **Losing the 45 commits by acting in the wrong order.** Push *first*, archive second. If
  the registry is archived while the branch is local-only, the repo drops off the estate's
  radar with three months of unbacked work on one disk. *Mitigation:* the acceptance test
  checks the remote branch before it checks the registry.
- **The push is outward-facing.** It publishes 45 commits to GitHub. Confirm the remote is
  the intended repo before pushing, push the branch only — never `--force`, never to `main`.
- **A push may fire stale CI.** `.github/` workflows exist and have not run since May; a
  push could page on a red build against a stale toolchain. *Mitigation:* expect it; this
  repo's CI gates nothing that ships. `dotnet` is not on PATH here, so no local gate exists
  either — do not attempt a build as a pre-push check.
- **Someone re-reads the monolith TODOs and rebuilds shipped capability.** Already happened
  once (the 2026-08-06 email plan; `haworks-platform` already ships email via its
  Notifications service). *Mitigation:* the new description names ADR-0009 in the registry,
  where the next agent reads it before opening the repo.
- **Low risk of being wrong about the product boundary.** If `haworks-platform` were ever
  abandoned and the monolith revived, this is reversible in one JSON edit — nothing is
  deleted, no history rewritten.
- **Out of scope by instruction:** this run made no code changes and opened no PR. The push
  and the registry edit are the *plan*, awaiting execution.
