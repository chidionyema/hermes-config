# Portfolio Site — next-move plan (2026-08-06, read-only inspection)

## Evidence gathered
- Repo: `~/Documents/code/portfolio-site`, branch `main`, HEAD `5533dc0` ("remove
  'zero downtime' claims from portfolio copy"), last commit ~2 months ago per
  `git log -1 --date=relative`.
- `npx vitest run` (2026-08-06, this repo, `node_modules` already installed):
  **8 of 11 test files fail, 12 of 22 tests fail.** Full run:
  `cd ~/Documents/code/portfolio-site && npx vitest run`
- CI (`.github/workflows/ci.yml`) never invokes `vitest` at all — its only
  gates are `scripts/check-quality.sh` (grep-based lint rules + `astro build`)
  and Playwright e2e. Confirmed: `grep -rn vitest .github/workflows/` returns
  nothing but the `package.json` devDependency lines.
- `.github/workflows/site-quality.yml:200` even prints the string
  `"Architecture checks passed — unit/component/e2e tests run in CI workflow"`
  — which is false for unit/component tests today; only e2e runs.
- Root cause of the failures, confirmed by direct diff (not inferred): copy
  was rewritten in `e82b201` ("remove jargon from all 13 demo descriptions +
  fix cryptic UI labels") and `5533dc0`, but the component tests' exact-text
  assertions were never updated. Example —
  `src/components/demo/RateLimiterDemo.tsx:113` renders `"Token Bucket
  Limiter"`; `tests/component/RateLimiterDemo.test.tsx:25` still asserts
  `screen.getByText('Token Bucket')` (exact match) → fails. Same pattern for
  button names (`/Send Request/i`, `/Test Query/i`, `/Single Update/i`) and
  headings across `VaultRotationDemo`, `RateLimiterDemo`, `IdempotencyDemo`,
  `EventFlowDemo`, `ConcurrencyDemo`, `CircuitBreakerDemo`,
  `CacheInvalidationDemo`. `tests/unit/useClusterState.test.ts` fails for an
  unrelated reason (SignalR hub URL `/hubs/console` doesn't resolve under
  jsdom — needs a base URL / mock).
- Because CI never runs these tests, this breakage has been invisible for at
  least the last several commits — the suite has been silently rotting.

## (1) The one objective
Wire `vitest run` into `.github/workflows/ci.yml` as a required job, and fix
the 8 broken test files so the suite is green — restoring real regression
coverage on the 13 interactive demo components, which are the site's
headline differentiator per the README ("Live Checkout Demo", "Circuit
Breaker Demo", etc.). This is the single highest-leverage item because right
now a genuine component regression (broken button, wrong state transition)
would ship straight to production undetected — the CI gate that's *supposed*
to catch it (per `site-quality.yml`'s own claim) doesn't exist.

## (2) Acceptance test
Single, self-contained, read-only, live-re-deriving command (exit 0 = fixed):

```bash
cd ~/Documents/code/portfolio-site && grep -lq "vitest run" .github/workflows/ci.yml && npx vitest run
```

- `grep -lq "vitest run" .github/workflows/ci.yml` fails (non-zero) until the
  CI job is actually wired in — no relying on a stale claim.
- `npx vitest run` re-executes the real suite live; its own exit code is 0
  only when all tests pass. No network calls, no mutation of repo state.

## (3) Files to touch
- `.github/workflows/ci.yml` — add a `unit` job (or step in `build`) running
  `npx vitest run`, gating merge like `check-quality.sh` already does.
- `.github/workflows/site-quality.yml:200` — fix the misleading echo once
  unit tests actually run in CI (either remove the claim or point it at the
  new job).
- `tests/component/RateLimiterDemo.test.tsx`,
  `tests/component/VaultRotationDemo.test.tsx`,
  `tests/component/IdempotencyDemo.test.tsx`,
  `tests/component/EventFlowDemo.test.tsx`,
  `tests/component/ConcurrencyDemo.test.tsx`,
  `tests/component/CircuitBreakerDemo.test.tsx`,
  `tests/component/CacheInvalidationDemo.test.tsx` — update stale
  exact-text/button-name assertions to match current copy (prefer
  `getByRole`/partial matchers over brittle exact `getByText` so the next
  copy pass doesn't re-break them).
- `tests/unit/useClusterState.test.ts` + `src/lib/cluster-store.ts:199` —
  give the SignalR `HubConnectionBuilder` a resolvable base URL in test env
  (or mock `signalR.HubConnectionBuilder` at the module boundary) so the hub
  build doesn't throw under jsdom.

## (4) Risks
- Fixing assertions instead of behavior could paper over a real regression
  if any of the 12 failures turn out to be a genuine component bug rather
  than a stale string — each failing test must be individually diffed
  against current component output before its assertion is changed, not
  bulk-updated.
- Adding `vitest run` as a required CI gate will turn CI red on the very
  next push until the 8 files are fixed — sequence the assertion fixes
  before (or in the same PR as) the CI wiring change, not after.
- `useClusterState`/SignalR fix touches `src/lib/cluster-store.ts`, which is
  shared by the live `LiveConsoleDock`/status UI — verify the mock doesn't
  mask a real prod connection issue (the component itself has an open
  `TODO: consolidate with cluster-store to avoid duplicate WebSocket` at
  `src/components/system/LiveConsoleDock.tsx:210`, a related but separate
  cleanup, not in scope here).
- None of this is money/identity/contract-risk — it's test/CI infra only.

---
*Inspection was read-only: no source files were modified, no branch created,
no PR opened. `npx vitest run` was executed to observe current test state;
it does not write to the repo (no coverage flag used).*
