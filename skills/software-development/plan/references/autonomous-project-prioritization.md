# Autonomous Project Prioritization

Use this when working across multiple independent projects in autonomous mode. The goal is to ship the closest-to-launch project first, not to distribute work evenly.

## The Priority Heuristic

When holding two projects with different launch-readiness:

| Project A | Project B | Decision |
|-----------|-----------|----------|
| Engine proven, storefront exists, gaps are config/hardening | Still proving core utility, no revenue path | **Focus on A.** B gets health-checks and monitoring only. |
| Engine proven, but no storefront/payment path | Engine proven, gaps are small config items | **Focus on the one with fewer remaining gaps.** Ship it. |
| Both have similar readiness | Pick the one where the next hour of work produces the most value | **Tiebreaker:** which has the clearer launch criteria? |

## The Stale-Docs Trap

Handover documents drift faster than code. In this session, two sets of documents were 1-2 days old and claimed features were missing that were actually built:

- `GO_LIVE_SPEC.md` (2026-06-16): said API tests were broken → **actually passing** (13/13)
- `GO_LIVE_SPEC.md`: said fulfilment chain absent → **actually fully built** (Orders, Entitlements, delivery endpoints, R2 upload, magic-link email)
- `HANDOVER_BRIDGE_TO_LAUNCH.md`: claimed port mismatch → **bridge.py already used correct port**, only Next.js client needed fixing

**The cost of trusting stale docs:** you'd spend time rebuilding features that already exist. Always run a parallel audit first.

## The Prove-Everything Rule

Every claim ("CORS is now wired", "ContentVersion fixed", "CI pipeline created") must be backed by tool output. Use this checklist:

- [ ] Did I run the test suite to verify no regressions?
- [ ] Did I grep the codebase to verify the change actually landed?
- [ ] Did I check that the change I made doesn't break anything else?
- [ ] Did I save the approach as a skill update if it's a reusable pattern?

## Batching Decisions

When a user decision is genuinely needed (irreversible, high-cost, or affects money):

1. List all pending decisions in one message
2. For each: state the options, the recommendation, and the cost of getting it wrong
3. Never ask "what do you think?" without providing your recommended answer

Example from this session:
```
DECISIONS NEEDED:
1. Content storage: R2 vs S3? (Recommend R2 — no egress fees)
2. Hosting: Fly.io vs others? (You mentioned Fly already)
3. Signal Engine launch definition? (What does "launch" mean for a research tool?)
```
