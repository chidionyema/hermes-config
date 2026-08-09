# Portfolio Site — Next Ship Item

**Repo**: `~/Documents/code/portfolio-site` (Astro 4 + React islands, deployed to Cloudflare
Pages at `haworks-platform.pages.dev`)

## Diagnosis

Verified via `README.md`, `git log -25`, `package.json`, full source grep, and a local
`npx vitest run` (22/22 pass, clean — this repo is not in a "fix tests" state).

Re-verified 2026-08-09 23:xx (second independent pass, same conclusion reached fresh):
`git log origin/main..HEAD` / `HEAD..origin/main` both empty (local == remote); `gh run list`
shows the last CI push run and last Deploy run both `success`; the only recurring red runs are
Dependabot "Updates" checks for `sharp`/`astro` failing since 2026-07-21 (unrelated, see Risks).
So the repo is fully green end-to-end — nothing here is a bug fix, it's a product-visibility gap.

The site's sole business purpose is stated in `src/pages/contact.astro:12-13`: land .NET
contract work for Chidi Onyema. The last ~15 commits (`e82b201` jargon removal, `0c87347`
single-CTA UX cleanup, `d9579b5` landing page redesign, `5533dc0` claims cleanup) are all
conversion-optimization changes to copy and CTAs — made **with zero measurement**.

`grep -rniE "plausible|analytics|gtag|posthog|umami|fathom|cloudflareinsights|beacon.min.js"`
across `src/`, `astro.config.mjs`, and every layout returns nothing except two unrelated
prose hits in MDX content. There is no analytics beacon anywhere in `BaseLayout.astro`'s
`<head>` (read in full, `src/layouts/BaseLayout.astro:1-80`) or `astro.config.mjs`. The site
has been live and iterated on for weeks with no visibility into traffic, which pages get
visited, whether the "Email me directly" / LinkedIn CTAs on `contact.astro` get clicked, or
whether any of the recent copy/CTA rewrites changed behavior at all.

This is the single highest-leverage next-move: every future decision on this site (which demo
to lead with, whether the jargon removal helped, whether visitors reach `/contact`) is
currently a guess, and the fix is nearly free — the site already deploys to Cloudflare Pages,
which ships **free, cookie-less Web Analytics** activated by one `<script>` tag with a
site-token, zero npm dependency, zero bundle-budget impact, zero consent-banner requirement
(it's not tracking-cookie based, so no CMP/GDPR-banner work is created).

## 1. Objective

Add Cloudflare Web Analytics (or equivalent privacy-friendly beacon) to every page so pageviews
and the two contact CTAs (`mailto:chidi@haworks.dev`, LinkedIn) are measurable, closing the
feedback loop for the conversion-copy work already shipped.

## 2. Acceptance test

Beacon script tag present in the rendered `<head>` of the built homepage, pointed at a real
Cloudflare token (not a placeholder), for every route (verified via the shared `BaseLayout`):

```bash
grep -q "cloudflareinsights.com/beacon.min.js" ~/Documents/code/portfolio-site/src/layouts/BaseLayout.astro
```

(Exit 0 = beacon wired into the shared layout, i.e. present on every page. This is read-only
against source; swap to `dist/index.html` post-build for a stronger check once implemented.)

## 3. Files to touch

- `src/layouts/BaseLayout.astro` — add the Cloudflare beacon `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token":"..."}'>` inside `<head>`, token sourced from a `PUBLIC_CF_BEACON_TOKEN` env var (pattern matches existing `PUBLIC_API_URL` env convention in `.env.example`).
- `.env.example` — document the new `PUBLIC_CF_BEACON_TOKEN` var.
- `.github/workflows/deploy.yml` — add `PUBLIC_CF_BEACON_TOKEN` to the build env (repo variable, not secret — beacon tokens are public/embedded in every page by design).
- (One-time, outside repo) Cloudflare dashboard → Pages project → Web Analytics → enable, copy token.

## 4. Risks

- **Low technical risk**: script is `defer`, async-loaded, no render-blocking, no measurable bundle-budget impact (`scripts/check-bundle-budget.mjs` unaffected — it's an external URL, not a bundled asset).
- **Token must be a real value before merge** — a placeholder token would silently collect nothing (no error, just an empty dashboard), so the acceptance check above should be tightened post-implementation to assert a non-placeholder token string once the real one is issued.
- **No PII/consent risk**: Cloudflare Web Analytics is cookie-less and does not require a consent banner, so this doesn't introduce compliance work.
- **Does not by itself fix conversion** — it only makes future conversion changes measurable. The actual next-next-move (e.g., "jargon removal increased/decreased contact-page reach") depends on this data existing first.

