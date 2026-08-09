# Portfolio Site — Next Ship Item (broken vitest suite invisible to CI)

> **Note:** this supersedes the previous version of this file (SEO domain drift in
> `astro.config.mjs`). That item is now DONE — verified live via
> `git log --oneline -1` = `f434ba5 fix(seo): correct production site domain to
> haworks-platform.pages.dev`, the current HEAD of `main` as of this analysis
> (2026-08-09). The prior report is preserved at
> `project-next-portfolio-site.prior-analytics-2026-08-07.md`.

---

Repo: `~/Documents/code/portfolio-site` (branch `main`, deploys to Cloudflare
Pages as `haworks-platform`). Read-only inspection — no code changed, no PR
opened.

## Evidence gathered

- `git log --oneline -25`: most recent ~15 commits are a copy/UX honesty pass —
  removing jargon, em dashes, false "zero downtime" claims, unused UI chrome
  (`StatusStrip`, `LiveConsoleDock` feed), fixing demo API paths, then the SEO
  domain fix (now shipped).
- `npx vitest run` (live, 2026-08-09): **8 test files failed / 3 passed, 12
  tests failed / 10 passed** out of 22 total. Failures: `tests/component/
  {CacheInvalidationDemo,CircuitBreakerDemo,ConcurrencyDemo,EventFlowDemo,
  IdempotencyDemo,RateLimiterDemo,VaultRotationDemo}.test.tsx` plus
  `tests/unit/useClusterState.test.ts`.
- Root cause, component tests: assertions still target pre-rewrite copy/labels.
  E.g. `tests/component/CircuitBreakerDemo.test.tsx:26` expects text
  `"Circuit Breaker State"` and `:32` expects a button named `/Send Request/i`;
  neither exists in the component anymore after `e82b201 fix: remove jargon
  from all 13 demo descriptions + fix cryptic UI labels` and `0c87347 fix: UX
  cleanup — single CTA...`. The tests were never updated alongside the copy
  they assert on.
- Root cause, `useClusterState.test.ts`: SignalR's `HttpConnection` can't
  resolve the relative hub URL `/hubs/console` under jsdom (no base URL
  configured for the test environment) — a separate, unrelated failure from
  the copy drift above.
- `.github/workflows/ci.yml`: the `build` job's "Quality gates" step runs
  `bash scripts/check-quality.sh`, which does lint-style greps (`as any`
  casts, raw `${}` in JSX, invalid Tailwind opacity classes, empty catches,
  unguarded clipboard calls) plus `npm run build` — **it never invokes
  `vitest`**. Confirmed live: `grep -rn vitest .github/` returns no hits
  anywhere in the workflow directory. Only Playwright e2e
  (`npx playwright test`) runs in CI, in a separate `e2e` job. `deploy.yml`
  triggers off the `CI` workflow's success via `workflow_run`.
- Net effect: the unit/component regression suite for the site's core feature
  — the 13 interactive distributed-systems demos that are the entire portfolio
  pitch — has been silently red through at least 3 months of copy-rewrite
  commits, and CI/deploy never saw it because nothing in CI runs `vitest`. A
  real behavioral regression in a demo (not just stale copy) would ship to
  production undetected today.

## (1) The one objective

Make the vitest unit/component suite a real, passing regression gate again:
fix the 11 failing tests so they assert against the current (post-rewrite) UI
copy and behavior, fix the `useClusterState` SignalR-in-jsdom failure, and add
a `vitest run` step to `.github/workflows/ci.yml`'s `build` job so this class
of drift is caught automatically instead of rotting silently again.

This is the single highest-leverage item because it's the one gap that lets
every other kind of regression (broken demo, dead button, mis-wired API call)
ship to production unnoticed — the exact failure mode this repo's own test
suite has already demonstrated by going undetected for 3+ months of active
copy work.

## (2) Acceptance test

Read-only, live, self-contained (run from repo root):

```bash
cd ~/Documents/code/portfolio-site && \
  grep -q "vitest run" .github/workflows/ci.yml && \
  npx vitest run --reporter=basic 2>&1 | tail -5 | grep -qE "Test Files\s+[0-9]+ passed \([0-9]+\)" ; \
  echo "EXIT:$?"
```

Exit 0 (`EXIT:0`) == fixed: CI wires in `vitest run` AND every test file
passes live. Exit nonzero == still broken. No network access, no file
mutation; re-derives both the CI config state and the live test result on
every run rather than trusting `playwright-report/` or any cached health
file.

## (3) Files to touch

- `tests/component/CacheInvalidationDemo.test.tsx`
- `tests/component/CircuitBreakerDemo.test.tsx`
- `tests/component/ConcurrencyDemo.test.tsx`
- `tests/component/EventFlowDemo.test.tsx`
- `tests/component/IdempotencyDemo.test.tsx`
- `tests/component/RateLimiterDemo.test.tsx`
- `tests/component/VaultRotationDemo.test.tsx`
- `tests/unit/useClusterState.test.ts` (fix or mock the SignalR hub URL
  resolution — either stub a jsdom base URL in `vitest.config.ts` / a test
  setup file, or mock `@microsoft/signalr` in this test)
- `vitest.config.ts` and/or a test-setup file (only if the SignalR fix needs a
  global jsdom URL/base config rather than a per-test mock)
- `.github/workflows/ci.yml` (add a `vitest run` step to the `build` job,
  alongside the existing `Quality gates` / `Astro build` steps)

No production `src/` changes are expected — the UI copy is already correct;
only the stale test assertions and the missing CI wiring need to change.

## (4) Risks

- **False-fix risk:** rewriting assertions to match whatever the DOM
  currently renders (rather than what it *should* render) makes tests pass
  without verifying real behavior. Each rewritten assertion must be checked
  against the current component source (e.g.
  `src/components/demos/CircuitBreakerDemo.tsx`) for the actual
  button/label text, not copy-pasted from the failure diff.
- **CI-break risk:** adding `vitest run` to `ci.yml`'s `build` job flips CI
  from green to red the instant it merges if even one test is still broken —
  sequence matters: fix all 11 failures first, verify green locally, then add
  the CI step in the same or immediately-following commit so `main` is never
  left broken.
- **SignalR-mock risk:** mocking `@microsoft/signalr` in
  `useClusterState.test.ts` could mask a real connection-handling bug if the
  mock is too permissive; prefer giving jsdom a real base URL so
  `HttpConnection` resolves the relative path exactly as the browser would,
  over stubbing the whole library.
- **Scope-creep risk:** `docs/UI_AND_DEMO_PLAN.md` lists a much larger
  backlog (T1.1 Aspire e2e smoke test, T1.2 backend metrics honesty, Tier 4
  new demos). Those are real but lower-leverage than an invisible-since-May
  test gate — do not fold them into this ship item.
