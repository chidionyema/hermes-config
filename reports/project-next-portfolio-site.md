# Portfolio Site — next ship item

Filed 2026-08-17. Supersedes the 2026-08-09 version of this file (analytics beacon), which is still open and still unshipped — see "Prior item" at the bottom.

Read-only inspection of `~/Documents/code/portfolio-site` @ `5adfffc`, branch `main`, working tree clean except untracked `graphify-out/`.

## State of the repo

The build and test story is healthy. `npx vitest run` exits 0. CI (`.github/workflows/ci.yml`) runs quality gates, vitest, build, bundle budget, then e2e. Deploy fires on CI success to Cloudflare Pages project `haworks-platform`. Only two TODOs exist across `src/` and `scripts/`, both cosmetic.

The last 15 commits are a copy and noise cleanup pass: demos de-jargoned, `StatusStrip` and `LiveConsoleDock` removed, single CTA, vitest repaired. The demos work. The code is not the problem.

## (1) The one objective

**Make the site publish under one identity: one canonical host, one contact email.**

The site tells visitors and search engines three different things about who it is and where it lives.

Domain, split six ways:

| File:line | Value |
|---|---|
| `astro.config.mjs:39` | `https://haworks-platform.pages.dev` — this one wins, it feeds `Astro.site` |
| `src/pages/sitemap.xml.ts:4` | `https://chidionyema.dev` |
| `public/robots.txt:4` | `Sitemap: https://chidionyema.dev/sitemap.xml` |
| `src/layouts/BaseLayout.astro:171` | JSON-LD `Person.url` = `https://chidionyema.dev` |
| `src/layouts/BaseLayout.astro:37,38` | fallbacks to `chidionyema.dev` (dead code, `Astro.site` is set) |
| `scripts/og.svg:46` | renders the text `chidionyema.dev` into the share image |

Contact email, split two ways:

| File:line | Value |
|---|---|
| `src/pages/contact.astro:35,58,60` | `chidi@haworks.dev` — primary CTA, shown as visible text |
| `src/components/system/CommandPalette.tsx:136` | `hello@chidionyema.dev` |

What breaks, concretely. A recruiter shares the site on LinkedIn. The page is served from `haworks-platform.pages.dev` and the canonical tag says `haworks-platform.pages.dev`, but the share card image says `chidionyema.dev`. Google fetches `robots.txt`, is pointed at a sitemap on `chidionyema.dev`, and either fails to fetch it or reads a sitemap listing URLs on a host it did not crawl. Either way the pages.dev pages do not get indexed through that sitemap. Separately, a visitor who opens the command palette gets a different email address from the one on the contact page.

This is the highest-leverage item because the site's whole job is turning search and LinkedIn traffic into contract enquiries. Thirteen working demos earn nothing if the pages are not indexed and some fraction of leads go to a second address. It also has to come before the analytics item: measuring traffic to pages a broken sitemap keeps unindexed measures the wrong thing.

## (2) Acceptance test

Single read-only command. Exit 0 means fixed.

```sh
cd /Users/chidionyema/Documents/code/portfolio-site && \
test "$(rg --no-filename --no-line-number -o -g '!node_modules' -g '!dist' '(chidionyema\.dev|[a-z0-9-]+\.pages\.dev)' src public scripts astro.config.mjs | sort -u | wc -l | tr -d ' ')" = 1 && \
test "$(rg --no-filename --no-line-number -o -g '!node_modules' 'mailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+' src | sort -u | wc -l | tr -d ' ')" = 1 && \
npx vitest run --reporter=basic > /dev/null 2>&1
```

Assertion 1: exactly one distinct site hostname across `src`, `public`, `scripts`, `astro.config.mjs`. Assertion 2: exactly one distinct `mailto:` address in `src`. Assertion 3: the suite still passes. Today it fails assertion 1 (four distinct values) and assertion 2 (two distinct values).

## (3) Files to touch

Canonical host: keep `https://haworks-platform.pages.dev`. It is the host that actually serves the site — commit `f434ba5` verified it live on 2026-08-09, after the prior value `haworks.pages.dev` was found not to resolve. `chidionyema.dev` is not provisioned anywhere in `infra/terraform/modules/cloudflare/`. Once everything derives from one constant, swapping to a custom domain later is a one-line change.

Contact address: keep `chidi@haworks.dev`. It is the primary CTA and the only address rendered as visible text.

1. `astro.config.mjs:39` — leave the value. It becomes the single source of truth; Astro exposes it as `import.meta.env.SITE`.
2. `src/pages/sitemap.xml.ts:4` — replace the hardcoded `SITE` constant with `import.meta.env.SITE`.
3. `public/robots.txt` — delete it. Add `src/pages/robots.txt.ts` emitting `Sitemap: ${import.meta.env.SITE}/sitemap.xml`, so the host cannot drift again.
4. `src/layouts/BaseLayout.astro:37,38` — drop the `?? 'https://chidionyema.dev'` fallbacks, use `Astro.site` directly.
5. `src/layouts/BaseLayout.astro:171` — JSON-LD `Person.url` reads the same value.
6. `scripts/og.svg:46` — replace the literal domain text with a placeholder token, substituted in `scripts/build-og.mjs` from the site value.
7. `src/lib/copy.ts` — add `CONTACT_EMAIL = 'chidi@haworks.dev'`.
8. `src/pages/contact.astro:35,58,60` and `src/components/system/CommandPalette.tsx:136` — import `CONTACT_EMAIL`, leave no literal addresses.
9. `scripts/check-quality.sh` — add the two assertions above so the split cannot come back through a later edit.

## (4) Risks

- **The mailbox may not exist.** The repo cannot prove `chidi@haworks.dev` receives mail. Send a test message before merging. If it bounces, change one constant in `src/lib/copy.ts` — the fix is shaped so that is a one-line reversal, not a rework.
- **OG image regeneration.** `npm run build` runs `scripts/build-og.mjs`, which rasterises `og.svg` through sharp. Editing the SVG can break rasterisation quietly. Check that `dist/` holds a valid OG PNG after the build, not just that the build exits 0.
- **robots.txt route change.** Moving from `public/robots.txt` to `src/pages/robots.txt.ts` changes how the file is produced. Confirm `dist/robots.txt` exists with the right content after `npm run build`. A missing robots.txt is worse than a wrong one.
- **A future domain swap needs a redirect.** Once the pages.dev URLs are indexed, attaching a custom domain later needs a 301 from the pages.dev host, via `public/_redirects` or the Cloudflare custom-domain setting. Not part of this item, but do not attach a domain without it.
- **Low blast radius.** No money rail, no auth, no contracts, no data migration. The change is SEO metadata plus one email constant. The worst realistic outcome is a failed build, caught by CI before deploy.

## Not chosen, and why

- More demos or demo polish — the thirteen that exist already pass their tests. A fourteenth does not fix discoverability.
- `LiveConsoleDock.tsx:210` duplicate-WebSocket TODO — internal tidiness on a component whose sibling was already deleted for being noise.
- Custom domain provisioning — real work, but it is a purchase and a DNS decision, and it sits behind the same single-source-of-truth refactor this item delivers.

## Prior item, still open

The 2026-08-09 report proposed adding a Cloudflare Web Analytics beacon. It has not shipped. Verified 2026-08-17: `rg -i "cloudflareinsights|beacon.min.js|plausible|posthog|gtag|umami|CF_BEACON"` over `src/`, `astro.config.mjs`, `.env.example` and `.github/workflows/deploy.yml` returns nothing, and only one commit (`5adfffc`) has landed since that report was filed.

It stalled because it needs a token from the Cloudflare dashboard, which is a human step outside the repo. Keep it queued behind this item. Fix the indexing and the lead path first, then measure them.
