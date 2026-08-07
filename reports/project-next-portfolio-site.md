# Portfolio Site — Next Ship Item (astro.config.mjs domain drift)

> **Note:** this supersedes the previous version of this file, which analyzed a different
> top-priority item (analytics/instrumentation). That analysis is preserved verbatim at
> `project-next-portfolio-site.prior-analytics-2026-08-07.md` and is not contradicted by this
> report — both are real, independently-sourced findings; this one is the task currently
> assigned to this report path.

---

## 1. Objective
Correct `astro.config.mjs`'s `site` value so it matches the real Cloudflare Pages deploy
target, so canonical `<link>` tags, `sitemap.xml`, Open Graph/Twitter share-preview URLs, and
the RSS feed resolve to the live domain instead of the currently hardcoded, mismatched
`https://haworks.pages.dev` at `astro.config.mjs:37` (the line even carries its own
`// TODO: confirm production domain. Used for canonical, OG, sitemap.` comment). This matters
because the site's entire purpose is to be shared for opportunities — wrong share-preview and
canonical URLs directly undermine that.

## 2. Acceptance Test
Read-only, fails today, passes once fixed:

```bash
grep -o "site: '[^']*'" ~/Documents/code/portfolio-site/astro.config.mjs
grep -o "project-name=[a-zA-Z-]*" ~/Documents/code/portfolio-site/.github/workflows/deploy.yml
grep -o "PLAYWRIGHT_BASE_URL: https://[a-zA-Z.-]*" ~/Documents/code/portfolio-site/.github/workflows/ci.yml
```

Passes only when the domain embedded in `astro.config.mjs`'s `site:` matches the deployed
project's `<project-name>.pages.dev`. Today it does not — confirmed live 2026-08-07:

```
site: 'https://haworks.pages.dev'                                    # astro.config.mjs:37
project-name=haworks-platform                                        # deploy.yml:66 (also package.json:9)
PLAYWRIGHT_BASE_URL: https://haworks-platform.pages.dev              # ci.yml:98
```

Three independent sources (`package.json:9`, `deploy.yml:66`, `ci.yml:98`) agree the deployed
Cloudflare Pages project is `haworks-platform`; Cloudflare Pages auto-assigns
`<project-name>.pages.dev`, so the real live URL is almost certainly
`haworks-platform.pages.dev`, not `haworks.pages.dev`. Corroborating evidence from the sibling
report (`project-next-portfolio-site.prior-analytics-2026-08-07.md:58`): a live `curl` probe on
2026-08-07 found `https://haworks-platform.pages.dev` returns **HTTP 200**, confirming that is
in fact the reachable domain — while `astro.config.mjs:37` still points at the wrong one.

## 3. Files to touch
- **Primary:** `portfolio-site/astro.config.mjs:37` — the `site:` field. This is the only
  file that needs editing.
- **Source-of-truth to confirm the correct value against (do not edit):**
  `.github/workflows/deploy.yml:66`, `.github/workflows/ci.yml:98`.

## 4. Risks
- The true production domain may be a **custom domain** aliased in the Cloudflare dashboard
  (not visible from repo source) rather than the raw `*.pages.dev` URL. Before changing
  `astro.config.mjs`, confirm the live domain via `npx wrangler pages project list` (requires
  `CLOUDFLARE_API_TOKEN`) or the Cloudflare dashboard — otherwise this fix risks swapping one
  wrong domain for another. Note: the sibling report's §5a found `https://chidionyema.dev`
  returns **HTTP 000** (unreachable) as of 2026-08-07, i.e. not currently live, and
  `README.md:97-98` documents that custom-domain setup as an undone founder step — so
  `chidionyema.dev` is not (yet) a candidate value for `site:`.
- **Secondary, lower priority:** `README.md:45` tells contributors to
  `git checkout feature/ha-portfolio-integration` on `haworks-platform`, a branch that no
  longer exists there (only `fix/analyzer-violations-and-portfolio-deploy` matches). This will
  mislead a fresh contributor following the local-dev instructions.

---

*This task was report-only: no files under `~/Documents/code/portfolio-site` were modified —
confirmed via `git status --short` (only pre-existing, unrelated dirt: a modified
`playwright-report/index.html` and untracked `graphify-out/`, neither touched this session).
No PR was opened.*
