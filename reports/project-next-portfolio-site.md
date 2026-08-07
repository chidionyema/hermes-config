# Portfolio Site — next move

**Date:** 2026-08-07
**Repo:** `~/Documents/code/portfolio-site` (git root; remote `https://github.com/chidionyema/portfolio-site.git`)
**HEAD:** `5533dc0 remove "zero downtime" claims from portfolio copy` — in sync with `origin/main`, working tree clean except untracked `graphify-out/`
**Note on the ask:** `~/Documents/code` is not a repo (`fatal: not a git repository`); it is the estate parent directory. The Portfolio Site repo is `~/Documents/code/portfolio-site`. Inspected that.

---

## 1. The single highest-leverage next ship item

**Instrument the funnel: add cookieless web analytics + a tracked, non-`mailto` contact capture.**

The site is live and technically healthy. What it cannot do is tell you whether any of it works. The
last 12 commits are, without exception, conversion-oriented UX surgery — and every one of them shipped
blind.

---

## 2. Why — evidence

### 2a. The last 12 commits are all conversion work
`git log --oneline -12`:

```
5533dc0 remove "zero downtime" claims from portfolio copy
6bb4e3f fix: remove flaky interactive demo tests + simplify homepage test
e82b201 fix: remove jargon from all 13 demo descriptions + fix cryptic UI labels
0c87347 fix: UX cleanup - single CTA, remove tech ego, simplify footer
c436bfb remove: StatusStrip cluster health bar (noise, no visitor value)
cd389fa remove: LiveConsoleDock request feed (distracting, no visitor value)
```

Two of those commit messages assert a product judgement in their own text — "no visitor value" — with
no visitor data in the repo to support it.

### 2b. There is zero analytics in the codebase
Grep for `plausible|gtag|googletagmanager|umami|posthog|fathom|analytics|cf-beacon` (case-insensitive)
across `src/` returns **two hits, both English prose in MDX content**:

- `src/content/work/osl-technologies.mdx:15` — "ML-driven analytics"
- `src/content/deep-dives/transactional-outbox.mdx:203` — "best-effort metrics or analytics"

No tag, no beacon, no script. Nothing measures a pageview, a demo interaction, or a CTA click.

### 2c. The only conversion path is an untrackable `mailto:`
`src/pages/contact.astro:35` and `:58` — both are `href="mailto:chidi@haworks.dev"`. There is no form,
no endpoint, no capture. A `mailto:` click emits no event and, when a visitor has no desktop mail
client configured, silently does nothing. The single CTA that commit `0c87347` consolidated the whole
site around is the one element that reports nothing back.

### 2d. The site and its backend are live — so this is not blocked on infra
Probed 2026-08-07 (single run each; `curl` access was withdrawn mid-session, so these were not
re-verified):

| URL | Result |
|---|---|
| `https://haworks-platform.pages.dev` | **HTTP 200** (1.86s) |
| `https://haworks-bffweb.fly.dev/health` | **HTTP 200** (1.13s) |
| `https://chidionyema.dev` | **HTTP 000** (no connection, 0.10s) |
| `https://ritualworks-bffweb.fly.dev/health` | HTTP 000 (stale name from `deploy.yml` comments) |

The product is up and the demo backend is up. The missing piece is the feedback loop, not the stack.

---

## 3. Concrete steps

1. **Analytics — Cloudflare Web Analytics** (free, cookieless, no consent banner needed, same vendor as
   the existing Pages deploy so there is no new account).
   - Cloudflare dashboard → Web Analytics → add site `haworks-platform.pages.dev` → copy the beacon token.
   - Add the beacon `<script>` to `src/layouts/BaseLayout.astro` (the shared layout — `:9` already
     references `/api/demo-client`, so it is the single common head for every page).
   - Gate it on `import.meta.env.PROD` so local dev and CI builds do not emit beacons.

2. **Make the CTA measurable.** Replace the two bare `mailto:` links in `src/pages/contact.astro:35,58`
   with a handler that fires a custom event and *then* navigates. Keep `mailto:` as the fallback href so
   the page still works with JS disabled.

3. **Add a real capture that survives a missing mail client.** A Cloudflare Pages Function
   (`functions/api/contact.ts`) accepting `POST {name, email, message}` and forwarding to email, plus a
   small form on `contact.astro`. This is the step that turns "someone was interested" from an
   unobservable event into a row you can count.

4. **Instrument the demos.** The 13 interactive demos are the site's headline feature
   (`src/lib/api/demo-client.ts` exposes 25+ endpoints). Fire one event on first interaction per demo.
   This answers the question commits `c436bfb` and `cd389fa` guessed at.

---

## 4. Acceptance / verification

- `npm run build` succeeds and the beacon token appears exactly once in `dist/index.html` — and **not**
  in a dev build.
- Cloudflare Web Analytics shows a non-zero pageview for a self-visit within 5 minutes.
- `POST /api/contact` with a test payload returns 2xx and the message arrives.
- A demo interaction on the live site produces a custom event in the dashboard.
- `bash scripts/check-quality.sh` still passes (it is what `ci.yml:24` gates on).

---

## 5. Runners-up, and why they lost

### 5a. Custom domain `chidionyema.dev` is not live — **the #1 founder action, but blocked**
`https://chidionyema.dev` returned **HTTP 000** (no connection). `README.md:97-98` documents the step —
"Cloudflare dashboard → Pages → haworks-platform → Custom domains, add `chidionyema.dev`" — and it has
not been done. The portfolio's only shareable URL is `haworks-platform.pages.dev`, which reads as a
random project rather than a person, and is not a URL you can put on a CV.

This is arguably higher leverage than instrumentation and is genuinely upstream of it — analytics on a
site nobody can find measures zero. **It lost only because it is blocked on registrar/DNS credentials
the estate does not hold, i.e. a founder action.** HTTP 000 cannot distinguish "domain registered but
unconfigured" from "domain never registered" — that needs a `whois`/`dig` check I could not run.
*If the founder has 15 minutes, do this one first.*

### 5b. 11 vitest files never run in CI — real rot, but engineering not product
Proven:
- `package.json:5-10` — scripts are `dev`, `build`, `preview`, `deploy`. **There is no `test` script.**
- `vitest.config.ts:11` includes `tests/unit/**` and `tests/component/**`.
- Those directories contain **11 test files**: `tests/component/` has 10 (`Button`,
  `CacheInvalidationDemo`, `CacheStampedeDemo`, `CheckoutDemo`, `CircuitBreakerDemo`, `ConcurrencyDemo`,
  `EventFlowDemo`, `IdempotencyDemo`, `RateLimiterDemo`, `VaultRotationDemo`), `tests/unit/` has 1
  (`useClusterState.test.ts`).
- Grep for `vitest|npm test|npm run test` across `.github/` → **No matches found.**
- `ci.yml` runs only `check-quality.sh` (`:24`), `npm run build` (`:29`), the bundle budget (`:32`), and
  Playwright (`:64`). `scripts/check-quality.sh:9-82` is greps plus `npm run build`.

⇒ **All 11 unit/component test files are dead weight — they have never gated a merge.**

Worse, `site-quality.yml:27` is literally:

```yaml
      - name: Check Architecture Quality
        run: echo "Architecture checks passed — unit/component/e2e tests run in CI workflow"
```

A green CI step that prints a claim and executes nothing. The claim is false: the CI workflow does not
run the unit or component tests. This is state-asserted-in-prose, in a workflow file.

**Fix (cheap, do it alongside):** add `"test": "vitest run"` to `package.json` and an `npm test` step to
`ci.yml`'s build job; delete or replace the `echo` at `site-quality.yml:27`. Expect first-run failures —
those 11 files have drifted unchecked since they were written, and `6bb4e3f` shows tests were recently
being deleted for flakiness rather than fixed.

### 5c. Non-blocking production e2e
`ci.yml:74-77` — the `e2e-deployed` job carries `continue-on-error: true`. The only check that ever
touches the live site can never fail the pipeline. Low cost to flip once it is trusted; not worth
flipping while it is unproven.

### 5d. Cosmetic drift (noted, not scheduled)
- `package.json:2` — `"name": "haworks-platform"` inside the `portfolio-site` repo.
- `deploy.yml:10-15` comments reference `ritualworks-bffweb.fly.dev` and a default project of
  `"ritualworks"`, while `deploy.yml:66` actually deploys `--project-name=haworks-platform`. The
  `ritualworks` host is dead (HTTP 000). Stale comments only; the executed path is correct.

---

## 6. Unverified — do not treat as fact

- Whether `chidionyema.dev` is **registered**. HTTP 000 proves unreachable, not unregistered.
  Kill-fast check: `dig +short chidionyema.dev` and `whois chidionyema.dev | head -20`.
- Whether the 11 vitest files **currently pass**. `npx vitest run` was denied by the sandbox this
  session; it was never run. Check: `npx vitest run --reporter=basic`.
- Whether the live demos actually function end-to-end. The BFF root `/health` is 200, but the specific
  demo routes (`/api/v1/demo/vault/status`, `/api/health/snapshot`) were denied before probing. Two
  guessed paths — `/api/demo/health` and `/api/demo` — returned 404, but those paths do not appear in
  `src/lib/api/demo-client.ts` and prove nothing. Check: probe the real paths from `demo-client.ts:246-619`.
- Whether the site gets **any traffic at all** today. Unknowable by construction — that is the gap this
  plan closes.
