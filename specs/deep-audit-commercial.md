# Otto Commercial Readiness — Deep Audit
**Date:** 2026-08-02
**Scope:** Full-stack — 1.17M lines Python, 1,574 test files, 112 scripts, 41 panels
**Verdict:** World-class engine. Not yet a product.

---

## 0. Raw Numbers

| Metric | Value | Assessment |
|---|---|---|
| Total Python LOC | 1,173,632 | Massive. Too large for one person to fully understand. |
| Operator shell LOC | 13,723 | Reasonable for the feature set. |
| Scripts | 112 (27K LOC) | Many are single-purpose. Consolidation needed. |
| Test files | 1,574 | Number is misleading — many are in dependencies. |
| Our acceptance tests | 118 | Good coverage of OUR features. Not of the full stack. |
| state.db size | 96MB | 🔴 Critical — needs immediate vacuum/rotation. |
| coordinator.db | 29MB | 🟡 Large. Check for bloat. |
| Logs directory | 53MB | 🟡 Growing. No rotation policy. |
| Disk usage | 85% | 🟡 Getting tight. No monitoring. |
| Running processes | 6 | Gateway, coordinator, prospector, signal engine, control-center, otto-server |
| Python versions in use | 3.12, 3.14 | 🔴 Not standardized. Compatibility risk. |
| Open ports | 6+ | Otto (8802), Ollama (11434), Cursor, VS Code, etc. |

---

## 1. Architecture Audit

### 1.1 Strengths
- **Layered architecture** — Operator shell → estate dispatch → scripts → coordinator → platforms. Clean separation.
- **Self-contained** — Everything lives in ~/.hermes. Single-directory deployment.
- **Telegram-native** — The phone IS the UI. No webapp to maintain.
- **Pluggable health checks** — 9 types, all ~20-line functions. Clean extension point.
- **Policy system** — Structured learning from failures. Good foundation.

### 1.2 Critical Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No API layer** | 🔴 | Everything is CLI or Telegram. No REST API for integration. Cannot be embedded in other products. |
| **No multi-tenancy** | 🔴 | One Otto = one estate. Cannot manage multiple clients. |
| **No authentication** | 🔴 | Telegram chat ID is the only auth. No API keys, no tokens, no OAuth. |
| **No secrets management** | 🔴 | API keys in plaintext config.yaml and env vars. No vault, no encryption at rest. |
| **No database migration system** | 🟡 | Schemas evolve ad-hoc. No versioning. Risk of corruption on upgrade. |
| **Tight coupling to filesystem** | 🟡 | Everything is files on disk. No abstraction. Can't run in cloud without filesystem. |
| **No message queue** | 🟡 | Cron and idle-learning run inline. No async task queue. Gateway blocks on long operations. |
| **No proper plugin system** | 🟡 | otto-inbound is a single 63KB file. Hard to extend without merge conflicts. |

---

## 2. Data & Storage Audit

### 2.1 Current State
- **coordinator.db** (29MB) — SQLite. Task queue, decisions, missions. Grown 10x in 2 months.
- **state.db** (96MB) — SQLite. Sessions, agent state. 🔴 THIS IS THE BIGGEST RISK.
- **sessions.db** (0B) — Empty. Dead file.
- **ticks.jsonl** (375KB) — Prospector run log. Growing ~100KB/day.
- **errors.log** — 5000+ errors. Growing unbounded.
- **No backups** — If any DB corrupts, data is lost.

### 2.2 Required Fixes
1. **state.db vacuum + rotation** — 96MB for session state is absurd. Implement TTL-based cleanup.
2. **coordinator.db archiving** — Tasks older than 90 days should be archived, not deleted.
3. **Automated SQLite backups** — Daily `VACUUM INTO` to backup directory.
4. **Log rotation** — errors.log at 5000 lines. Rotate at 10MB or 30 days.
5. **Database health monitoring** — Add to ops-monitor: check DB size, integrity, fragmentation.

---

## 3. Security Audit

### 3.1 Current State
- API keys in: `config.yaml`, `.env`, environment variables
- No encryption at rest
- No audit log for sensitive operations
- Telegram bot has no rate limiting
- No input validation on chat messages
- No CORS, no CSP (not applicable for Telegram, but matters for any web surface)

### 3.2 Required Fixes
1. **Secrets manager** — Move all API keys to a dedicated encrypted store (age/sops, or at minimum a gitignored `.secrets.yaml`).
2. **API key rotation** — Support rotating keys without downtime.
3. **Audit log** — Every money-adjacent action logged immutably. Already partially done (proof.py).
4. **Rate limiting** — Telegram bot should rate-limit per user. Prevent DoS.
5. **Input sanitization** — Chat messages go through subprocess and SQL. Sanitize.
6. **Principle of least privilege** — Gateway shouldn't run as the user's full account. Containerize.

---

## 4. Reliability & Resilience Audit

### 4.1 Single Points of Failure

| Component | SPOF? | Impact if down |
|---|---|---|
| Gateway | ✅ Yes | No Telegram access. No cron. No idle-learning. |
| Coordinator | ✅ Yes | No task dispatch. No estate management. |
| SQLite DBs | ✅ Yes | All state lost if corrupted. |
| Filesystem | ✅ Yes | Everything is files. |
| Telegram API | ✅ Yes | No user access. (External dependency — acceptable.) |
| Mac host | ✅ Yes | Single machine. No cloud fallback. |

### 4.2 What's Missing
- **No health check endpoint** — Cannot be monitored by external uptime services.
- **No graceful degradation** — If coordinator is down, mission card should still work (reads files directly).
- **No circuit breakers** — If Claude API is down, Otto should fall back to MiniMax without manual intervention.
- **No retry with backoff** — Failed cron jobs retry immediately, compounding the failure.
- **No dead letter queue** — Failed tasks are just logged. No retry mechanism.

---

## 5. Performance Audit

### 5.1 Current Bottlenecks
- **Mission card takes 6s cold** — Reads coordinator DB + ticks file + signal engine probe.
- **st_status takes 64s cold** — Hits Stripe API. Cached on second tap.
- **Prospector panel reads ticks.jsonl 3× per render** — Fixed with cache. Good.
- **No query optimization** — Coordinator DB has no indexes beyond defaults.
- **state.db at 96MB** — Every session query scans a massive table.

### 5.2 Required Fixes
1. **Database indexes** — Add indexes on frequently queried columns (status, created_at, session_key).
2. **state.db cleanup** — Implement session TTL. Delete sessions older than 30 days.
3. **Pre-warm critical paths** — Already partially done (preflight.py). Extend to all cold paths.
4. **Async I/O** — Gateway blocks on DB reads. Use aiosqlite or thread pool.
5. **Panel render budget** — Enforce max 500ms render time. If slower, show cached version + background refresh.

---

## 6. Testing & Quality Audit

### 6.1 What's Good
- 118 acceptance tests for our features. All green.
- Tests exercise real panels, real dispatch, real NL routing.
- Tests are fast (<2s each). Can run on every change.

### 6.2 What's Missing
- **No unit tests** — Only integration/acceptance tests. Individual functions untested in isolation.
- **No performance tests** — No benchmark that panel renders complete within time budget.
- **No chaos testing** — What happens if coordinator.db is deleted mid-query?
- **No regression test for score** — Score should never decrease without a reason.
- **No contract tests** — estate.py dispatch interface has no contract test.
- **No fuzz testing** — What happens with malformed JSON in ticks.jsonl? With emoji in chat?
- **Test coverage unknown** — No coverage tool configured.

---

## 7. UI/UX Audit

### 7.1 What's Good
- Command palette (just built) — `?` shows all 77 actions.
- Smart suggestions (just built) — Context-aware next actions.
- Usage-adaptive home (just built) — Shows your most-used commands.
- Unified help (just built) — "I want to…" grouped by intent.
- Natural language — 100+ phrases route to correct actions.

### 7.2 What's Still Broken
- **No onboarding flow** — `otto setup` wizard exists in code but user doesn't know to run it.
- **Panel consistency** — Some panels are 100 chars, some 1400. No compact/expanded pattern.
- **No search within panels** — Can't search for "moat" within the prospector panel.
- **No dark/light mode** — Telegram handles this, but panel formatting doesn't adapt.
- **No accessibility** — Emoji-heavy. No alt text. Screen readers get garbage.
- **No undo for most actions** — Undo exists for pause/resume only. Not for config changes.
- **No confirmation for destructive actions** — "Restart coordinator" has confirm, but "stop signal engine" might not.
- **Error messages are raw** — `cursor_cli: ProviderExhaustedError: cursor cli failed after 2 attempts` — this is noise to a CEO.

### 7.3 The "Blank Slate" Problem
A new user opens Otto for the first time. They see:
- A pinned mission card with "🟡 BLOCKED — 2 need you"
- Jargon: "BLOCKED c1d2a4dd failure: probe relay latency self-test"
- Buttons: ♻️ Restart GW, 🔄 Restart Coord, 📊 Status, 📝 Assign, ❓ Help

This is terrifying. They don't know what any of this means. They don't know what to do first. They close the app and never come back.

**The fix:** First-run experience. Detect new user → show "👋 Welcome to Otto! I monitor your estate. Here's what I found: 3 projects, 2 healthy, 1 needs attention. Type `?` to see what I can do, or `status` for a quick overview."

---

## 8. Operations & DevOps Audit

### 8.1 Current State
- **Deployment:** Manual. `git pull` + restart gateway.
- **Monitoring:** Self-monitoring only. No external health check.
- **Alerting:** Telegram only. No escalation to email/SMS/phone.
- **Backup:** Manual git pushes. No automated DB backups.
- **CI/CD:** None. No automated test runs on push.
- **Versioning:** Git tags? Unclear.
- **Changelog:** Feature registry exists. Not automated.

### 8.2 What a Commercial Product Needs
1. **One-command install** — `curl | bash` or `pip install otto`.
2. **Automated backups** — Daily DB dumps to cloud storage.
3. **Health check endpoint** — `GET /health` returns 200 + estate status.
4. **CI/CD pipeline** — Tests run on every push. Deploy on main merge.
5. **Versioned releases** — Semantic versioning. Release notes auto-generated from feature registry.
6. **Rollback capability** — `otto rollback` reverts to last known good state.
7. **Telemetry** — Anonymous usage stats to guide development. Opt-in.

---

## 9. Business/Commercial Audit

### 9.1 What's Missing for a Sellable Product

| Requirement | Status |
|---|---|
| **Pricing model** | ❌ None. No way to charge money. |
| **License key** | ❌ No license enforcement. |
| **Free tier → paid conversion** | ❌ No tiered feature set. |
| **Documentation site** | ❌ No docs.ottonomy.ai or equivalent. |
| **Landing page** | ❌ None. |
| **Customer onboarding** | ❌ No guided setup. |
| **Support system** | ❌ No ticketing, no SLAs. |
| **SLA guarantees** | ❌ No uptime commitment. |
| **Data residency** | ❌ Everything on one Mac. No regional deployment. |
| **GDPR/privacy** | ❌ No data processing agreement. No right-to-delete. |
| **SOC2/ISO27001** | ❌ Not even close. No audit trail, no access controls. |
| **White label** | ❌ Hardcoded "Otto" branding everywhere. |

### 9.2 Competitive Positioning

| Competitor | Otto vs Them |
|---|---|
| **PagerDuty** | Otto is proactive (predicts + fixes), PD is reactive (alerts only). Otto's advantage. |
| **Datadog** | DD has dashboards. Otto has actions + self-healing. Different category. |
| **GitHub Actions** | CI-focused. Otto is operations-focused. Complementary. |
| **Self-built scripts** | Otto is unified + self-improving. Clear upgrade path. |

**Otto's unique value proposition:** The only estate manager that detects, diagnoses, fixes, verifies, and LEARNS — with zero configuration for common stacks. You type `?` and it works.

---

## 10. The Gap-to-Product Matrix

This is the prioritized list of everything needed to go from hobby to product:

### 🔴 Phase 1: Can't Ship Without These (2-4 weeks)

| # | Fix | Effort |
|---|---|---|
| P1-1 | **Secrets management** — Move API keys out of plaintext. age/sops encryption. | 2 days |
| P1-2 | **Database health** — Vacuum state.db, add TTL cleanup, add indexes, daily backups. | 2 days |
| P1-3 | **First-run experience** — Detect new user, show welcome card, guide to `?`. | 1 day |
| P1-4 | **One-command install** — `pip install otto` + `otto init`. Working in 60 seconds. | 2 days |
| P1-5 | **Health check endpoint** — `GET /health` on a port. Uptime monitor compatible. | 1 day |
| P1-6 | **Error message humanization** — Map raw errors to plain English. "Cursor credits exhausted → Top up at cursor.sh/account ($20/mo)." | 1 day |
| P1-7 | **Documentation site** — docs.otto.sh with: install guide, command reference, estate.yaml schema, health check types. | 3 days |
| P1-8 | **Landing page** — otto.sh with: what it does, how it works, pricing. | 2 days |

### 🟡 Phase 2: Commercial Viability (4-8 weeks)

| # | Fix | Effort |
|---|---|---|
| P2-1 | **REST API** — Wrap estate actions as HTTP endpoints. Enable integrations. | 1 week |
| P2-2 | **Multi-tenant** — One Otto instance, multiple estates. Namespaced configs. | 1 week |
| P2-3 | **Authentication** — API keys with scoped permissions. Read-only vs admin. | 3 days |
| P2-4 | **CI/CD pipeline** — GitHub Actions: test → lint → deploy on main merge. | 2 days |
| P2-5 | **Telemetry** — Anonymous usage stats. Which commands used, panel latency, score trends. | 3 days |
| P2-6 | **Pricing page** — Free: 1 project, 1 operator. Pro: unlimited projects, 5 operators. Enterprise: multi-estate, SSO, SLA. | 1 day |
| P2-7 | **License enforcement** — License key validates on startup. Graceful degradation on expiry. | 2 days |
| P2-8 | **Email/Slack alerting** — Already built (alert_router.py). Needs end-to-end testing. | 1 day |

### 🟢 Phase 3: Enterprise Ready (8-16 weeks)

| # | Fix | Effort |
|---|---|---|
| P3-1 | **Containerized deployment** — Docker image. Kubernetes Helm chart. | 1 week |
| P3-2 | **Cloud storage backend** — S3/Postgres instead of local files. | 2 weeks |
| P3-3 | **Audit log compliance** — Immutable append-only log. SOC2 evidence. | 1 week |
| P3-4 | **RBAC with SSO** — OAuth/OIDC. Google/GitHub/Okta login. | 1 week |
| P3-5 | **SLA monitoring** — Track uptime. Generate compliance reports. | 3 days |
| P3-6 | **White label** — Configurable branding. Custom bot name, custom emoji. | 3 days |

---

## 11. Score: Hobby → Product Readiness

| Dimension | Score | Notes |
|---|---|---|
| **Core Engine** | 9/10 | Self-monitoring, self-healing, self-improving. Best-in-class. |
| **UI/UX** | 7/10 | Command palette fixed discoverability. Still has blank-slate problem. |
| **Security** | 3/10 | No secrets management. No auth. No audit trail. |
| **Reliability** | 5/10 | Single machine. No backups. No HA. Graceful degradation partial. |
| **Operations** | 3/10 | Manual deploy. No CI/CD. No health checks. No backup automation. |
| **Testing** | 6/10 | 118 acceptance tests green. No unit tests. No coverage. No chaos. |
| **Documentation** | 2/10 | Specs exist. No user docs. No API docs. No website. |
| **Commercial** | 1/10 | No pricing. No license. No multi-tenant. No support. |

**Overall: 4.5/10 — Hobby project with a world-class engine inside.**

---

## 12. Immediate Actions (This Week)

1. **Fix state.db (96MB)** — Add TTL cleanup. This is a ticking time bomb.
2. **Secrets encryption** — Move all API keys to encrypted store. This is a security incident waiting to happen.
3. **First-run experience** — A new user must see a welcome, not a terrifying error card.
4. **Documentation site** — At minimum: one page with install + `?` + estate.yaml example.
5. **One-command install** — `pip install otto` must work.

**With these 5 fixes, Otto goes from "impressive hobby project" to "early-stage product that someone could actually pay for."**
