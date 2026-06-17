# Pre-Publication Honesty Audit

Use this whenever the user asks "is this real?", "is this accurate?", or is about to publish/market something. **The job is to push back on claims that aren't backed by running code.**

## The Pattern

When the user is about to publish, ship, or claim something publicly:

1. **Do NOT summarise capability** — execute it and show output
2. **Run the actual end-to-end test** before answering "is this real?"
3. **Find the real bugs** before the public does
4. **Surface every limitation honestly** — don't soften to make the claim sound better
5. **Use the "What X Is Not" section** in any serious write-up

## Why This Matters

The user has high quality standards and treats the work as a real product. They explicitly asked "is this actually true" before publishing a LinkedIn article about POPDD. The test surfaced a real bug (4/3011 spec clauses failed on baseline inputs). Better to find this in private than have someone find it in public.

## The Audit Steps (Run Before Saying "Yes, You Can Publish")

```bash
# 1. The code compiles cleanly
cd ~/Documents/code/lux && npx tsc --noEmit src/proof/receipt.ts

# 2. The tests pass
npx vitest run tests/receipt.test.ts tests/popdd-e2e.test.ts

# 3. The e2e demo runs end-to-end
npx tsx demo/popdd-e2e.ts

# 4. The chain file is valid JSONL
cat .lux/receipts/chain-*.jsonl | python3 -m json.tool --json-lines

# 5. The repo is staged for first commit (if linking from the article)
git status --porcelain | head -5
```

If any of these fail, do not publish. Report what failed and fix it first.

## The "What X Is Not" Section (Mandatory for Serious Write-ups)

Every public claim about POPDD / LUX should include a "What This Is Not" section. The user's framing should be:

> POPDD is not a substitute for trust in the agent — it is a chain-of-custody layer over whatever the agent produced. The chain is only as trustworthy as the signing key. Local signing with hardware key support, human-in-the-loop signing for high-stakes actions, and key rotation policies are the real security boundary.

This pre-empts the obvious objections ("what about the signing key?", "is this just HMAC?", "what's the diff vs blockchain?") and signals technical credibility to a sophisticated reader.

## The "Lean4 vs Dafny" / "Tooling vs Architecture" Traps

When a public claim mentions specific tools:

- **Verify the tool is actually used** in the source. The LUX product uses **Dafny with Z3** for L4 mechanized proofs, not Lean4. Architecture docs may mention Lean4 aspirationally — production code is what counts.
- **Verify the autonomy claim**. POPDD is the *infrastructure* for autonomous code-merging. It exists. **Autonomous merges are not yet in production.** Frame as "built in preparation for" or "the architecture for" — not "we use it to ship every change".
- **Verify the marketing claim against the test count**. "73/73 tests passing" is real. "We use POPDD for every commit" is not.

## Failure Mode to Avoid

**Don't say "yes, publish" when you haven't run it.** This is the most common failure mode. The right answer to "is this real?" is:

1. Run it.
2. Show the output.
3. Surface what failed (often something will).
4. Fix it.
5. Then say yes.

Saying "yes" without running it is a one-line response that costs the user their credibility when a sharp reader checks.

## Real Example From This Pattern

**Claim**: "POPDD works end-to-end on a real feature."
**Audit**: ran `npx tsx demo/popdd-e2e.ts`.
**Found**: 4/3011 spec clauses failed on baseline inputs (preconditions throwing on `undefined`).
**Fix**: hardened preconditions with `Array.isArray(i?.[N])` guards.
**Result**: 3011/3011 PASS, 4 signed receipts, tamper detection verified.
**Article published with receipts** that survived any technical challenge from readers.

Without the audit, the article would have claimed "POPDD works" and a reader running the demo would have found the bug first. That's a credibility hit. With the audit, the bug is fixed in private and the public claim is bulletproof.
