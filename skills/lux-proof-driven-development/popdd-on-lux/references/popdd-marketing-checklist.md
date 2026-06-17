# POPDD Marketing Honesty Checklist

A "what to claim vs. what not to claim" checklist for any public writing about
**POPDD** (Proof of Proof-Driven Development). Use this before publishing a
LinkedIn post, blog, conference talk, README rewrite, or social media thread.

The reader is assumed to be a skeptical senior engineer. Marketing fluff gets
screenshotted and dunked on. The job of this document is to keep the public
claims **true, scoped, and verifiable**.

---

## 0. The 30-second mental model

POPDD is two npm-installable packages (`@lux/popdd` for TypeScript,
`lux-popdd` for Python) that cryptographically **chain agent actions to the
proofs those actions produced**. A chain is a sequence of `DecisionReceipt`
records, each signed with HMAC-SHA256 (default) or Ed25519 (planned multi-party
upgrade — interface exists, not yet shipped), each linked to the previous
receipt's content hash. Tampering with any receipt breaks the chain at exactly
that receipt; that's the entire security model.

POPDD **proves what happened**, not what was allowed. The trust boundary is the
signing key. Anything that implies POPDD substitutes for trust in the agent,
the proof system, or the build pipeline is wrong.

---

## 1. Green-light claims

These are true, evidence-backed, and safe to print verbatim with appropriate
links.

| # | Claim | Evidence to attach |
|---|---|---|
| G1 | POPDD is shipped as two public packages: `@lux/popdd` (TypeScript) and `lux-popdd` (Python). | GitHub: <https://github.com/chidionyema/popdd-ts> and <https://github.com/chidionyema/lux-popdd> |
| G2 | LUX consumes `@lux/popdd` via a local file path (`"@lux/popdd": "file:../popdd-ts"` in `package.json`). | `~/Documents/code/lux/package.json` |
| G3 | Signal Engine and Prospector consume `lux-popdd` via `file:` / `@ file:///...` dependencies, **without depending on LUX**. | `pyproject.toml` in each downstream project. |
| G4 | Each downstream project ships a `scripts/popdd_verify.py` that signs a real test run into `.lux/receipts/`. | `scripts/popdd_verify.py` in LUX, Signal Engine, Prospector. |
| G5 | Verified end-to-end POPDD runs exist: LUX = 81/81 passed, Prospector = 359/359 passed. | `.lux/receipts/lux-test-8722.jsonl` and the Prospector receipt chain. |
| G6 | The `DecisionReceipt` chain uses HMAC-SHA256 by default; the `Signer` interface is designed to be swapped for Ed25519. | `@lux/popdd` source + `Signer` Protocol. |
| G7 | POPDD is proof-system-agnostic. It chains the *result* of any verifier; it does not implement a proof engine itself. | `popdd/receipt.py` and the `proof` field in `DecisionReceipt`. |
| G8 | LUX defines four proof levels: L1 (property), L2 (exhaustive), L3 (type-level / Curry-Howard), L4 (Dafny + Z3 mechanized). | `~/Documents/code/LUX_ARCHITECTURE.md` § proof levels. |
| G9 | A full architecture spec (~50 KB, ~1189 lines) is on disk. | `~/Documents/code/LUX_ARCHITECTURE.md`. |
| G10 | The `@lux/popdd` and `lux-popdd` packages declare **zero runtime dependencies**. | `popdd-ts/package.json` (no `dependencies` key) and `popdd-py/pyproject.toml` (`dependencies = []`). |
| G11 | A working end-to-end demo exists: `lux/demo/popdd-e2e.ts` takes a real feature (`weightedAverage`) through spec → verify → edit → test → 4 signed receipts → reload → tamper test. | `npx tsx demo/popdd-e2e.ts` |

**Rule:** if a green-light claim cannot be backed by a file path, a repo URL, or
a runnable command, downgrade it to an amber claim or remove it.

---

## 2. Amber claims

True, but only defensible **with a stated qualifier**. Print the qualifier
inline; do not bury it in a footnote.

| # | Claim | Required qualifier |
|---|---|---|
| A1 | "POPDD is cryptographically secure." | "**against tampering by anyone who does not hold the signing key.** The default signer is HMAC-SHA256, which is symmetric. For multi-party audit, swap to Ed25519 (interface exists, implementation pending)." |
| A2 | "POPDD is tamper-evident." | "**at the receipt granularity.** Modifying any field of any receipt breaks that receipt's signature; reordering breaks the chain via `previousHash`." |
| A3 | "POPDD integrates with L4 mechanized proofs." | "**via the LUX side.** POPDD itself does not run Dafny/Z3; it receives the verdict and signs a receipt. The L4 proof happens in the verifier, not in POPDD." |
| A4 | "POPDD is production-ready." | "**for single-agent, single-host audit trails.** Multi-party, cross-host, key-rotation production deployments require the Ed25519 signer (not yet shipped)." |
| A5 | "Ed25519 signing is supported." | "**the interface is supported.** An Ed25519 `Signer` implementation conforming to the `Signer` Protocol is a 10-line addition using `@noble/curves/ed25519` (TS) or `cryptography` / `pynacl` (Py). It is not yet committed to either package as a default." |
| A6 | "POPDD works with autonomous agents." | "**the infrastructure is in place.** Autonomous code-merge workflows that consume POPDD receipts as a merge gate are designed-for but not yet running in production. Frame as 'built in preparation for' or 'the architecture for', not 'we use it to ship every change'." |
| A7 | "POPDD is open source." | "**the PDD engine is MIT-licensed.** The receipts/audit layer and any hosted verification service are intended to be commercial; treat the packages as **open core**, not fully open." |
| A8 | "POPDD detects AI hallucinations." | "**only in the narrow sense** that if a verification step ran and produced a `PASS` verdict, POPDD will detect any later tampering with that verdict. POPDD does not verify the *correctness* of the verifier; a passing-but-wrong verification still produces a passing receipt." |
| A9 | "POPDD scales to large chains." | "**each receipt is ~500 bytes of JSONL; a 10,000-step chain is ~5 MB.** Verification is O(n) over chain length, dominated by HMAC compute. There is no built-in sharding, no Merkle summarization, no off-chain anchoring." |
| A10 | "POPDD replaces audit logs." | "**only for tamper-evidence.** POPDD does not capture stdout, stack traces, environment state, or human-readable context. Pair it with a real log pipeline for forensics." |

**Rule:** if you cannot fit the qualifier in the same sentence as the claim,
the claim is probably too strong — rewrite or drop it.

---

## 3. Red-light claims

These are misleading, premature, or simply false. **Do not publish them as
written.** For each, the third column says what to write instead.

| # | Do not claim | Why it's wrong | Write this instead |
|---|---|---|---|
| R1 | "POPDD prevents all AI hallucinations." | POPDD is a chain over verifier output, not a verifier of reasoning. | "POPDD detects tampering with the outputs of verifiers, including the cases where those verifiers certify L1–L4 proofs in LUX." |
| R2 | "POPDD is unbreakable." | HMAC-SHA256 with a stolen key is fully forgeable. | "POPDD detects tampering *as long as the signing key is uncompromised*. Key compromise is the failure mode." |
| R3 | "POPDD is blockchain-grade / uses blockchain." | POPDD has no consensus, no network, no distributed ledger. | "POPDD is single-host, no network, no consensus. It is a *cryptographic chain*, not a *blockchain*." |
| R4 | "We use POPDD in production to gate every commit." | The signing-key / multi-party plumbing for that gate is not yet shipped. | "We sign every LUX test run with POPDD. The CI gate that *blocks* merges on a failed receipt is the next integration step." |
| R5 | "POPDD is a feature of LUX." | LUX is *one* consumer; Signal Engine and Prospector are independent consumers. | "POPDD is a standalone package family. LUX is one of three current consumers." |
| R6 | "POPDD requires LUX." | The packages ship and run independently of LUX. | "POPDD is proof-system-agnostic. It chains the verdict of any verifier; LUX's `SpecVerifier` is one such verifier." |
| R7 | "LUX uses Lean4 for L4 proofs." | LUX uses **Dafny with Z3**. Lean4 is mentioned aspirationally in some architecture sections, not used in code. | "LUX uses **Dafny with Z3** for L4 mechanized proofs." |
| R8 | "We integrated autonomous agents that ship code via POPDD receipts." | The integration is *designed for*, not *running*. | "The infrastructure is built in preparation for autonomous merges: every test run is signed, and the chain file is the merge gate. The autonomous merger itself is the next layer." |
| R9 | "POPDD is open source under MIT." | Only the PDD engine is MIT. Receipts/audit tooling is intended to be commercial (open core). | "POPDD is open-core: the `@lux/popdd` and `lux-popdd` engines are MIT-licensed. Hosted verification and audit tooling are commercial." |
| R10 | "POPDD is the only way to verify AI work." | There are many audit-trail tools (e.g., Sigstore, in-toto, OpenTelemetry traces). | "POPDD is one approach to AI-work audit: local, single-host, proof-system-agnostic, zero-dep, and designed to drop into a `scripts/` directory." |
| R11 | "The chain is verified by a third party." | Verification today is local. A notarization / timestamp-authority service is a planned addition, not a shipped one. | "Verification is local to the host that holds the signing key. A notarization step (anchor chain hash to an external timestamping authority) is a planned upgrade." |
| R12 | "POPDD works on every model and every agent." | POPDD is an *infrastructure* layer; it does not care which model produced the action, but it also does not protect against a model that ignores the verifier entirely. | "POPDD signs whatever a verifier hands it. If the agent skips the verifier, POPDD will faithfully sign a `verdict: SKIPPED` receipt." |

---

## 4. Specific things to fix in the LinkedIn article

The current draft has several specific problems. Each is a concrete edit.

### 4.1 Tool-name correction: "Lean4" → "Dafny/Z3"

- **Current (wrong):** "…proved with Lean4…"
- **Fix:** "…proved with **Dafny + Z3** (mechanized theorem provers)…"
- **Why:** LUX's L4 implementation is Dafny with Z3. Lean4 is mentioned
  aspirationally in the architecture doc; it is not used in code. Any engineer
  who reads `lux/src/proof/` will catch this within minutes.
- **Acceptable variants:** "Dafny/Z3", "Dafny with the Z3 SMT solver",
  "mechanized theorem provers (Dafny/Z3)".

### 4.2 Soften the autonomous-agents claim

- **Current (too strong):** "We integrated autonomous agents that ship every
  change behind a POPDD receipt."
- **Fix A:** "**As** we integrated autonomous agents, the receipt chain is the
  merge gate they will pass through."
- **Fix B:** "**In preparation for** autonomous merges, every test run is
  signed and the chain file is committed alongside the patch."
- **Why:** The integration is in place. The agent fleet is not. Saying
  "we integrated" reads as "running today" to a LinkedIn reader.
- **Never write:** "ships every change", "blocks every commit", "in production
  for all PRs".

### 4.3 Add a concrete example: `weightedAverage`

The article is currently abstract. Add a single concrete receipt chain as a
code block. Use the actual `lux-test-8722.jsonl` or the four-receipt demo chain
from `lux/demo/popdd-e2e.ts`. The exact chain from
`chain-2026-06-17T15-26-54-543Z.jsonl`:

```
sequence 0  action spec-write  target weightedAverage   proof { preconditions: 4, postconditions: 3, invariants: 2, edgeCases: 5 }
sequence 1  action verify      target weightedAverage   proof { verdict: PASS, passedClauses: 3011, totalClauses: 3011, invariantSamples: 1000 }
sequence 2  action edit        target src/math/weighted.ts   proof { verdict: PASS, sha256: ..., diffLines: 38 }
sequence 3  action test-run    target tests/weighted.test.ts proof { verdict: PASS, tests: 5, passed: 5, failed: 0, duration_ms: 12 }
```

One chain in the article is worth three paragraphs of prose. The reader can
verify it in 30 seconds by running `npx tsx demo/popdd-e2e.ts`.

### 4.4 Add a "What POPDD Is Not" section

The skeptical-engineer reader will look for this section within the first
three scroll-stops. If you don't write it, they will write it for you in the
comments. Use this exact framing:

> **What POPDD is not.** POPDD is not a substitute for trust in the agent, the
> verifier, or the build pipeline. It is a chain-of-custody layer over whatever
> the agent produced. The chain is only as trustworthy as the signing key.
> Local signing with hardware key support, human-in-the-loop signing for
> high-stakes actions, and key rotation policies are the real security
> boundary. POPDD does not run proofs; it does not stop a hallucinating model
> from acting; it does not provide non-repudiation unless the signing key is
> outside the agent's reach.

### 4.5 Add a license note (open core)

The article implies "open source" without qualifier. Add one sentence:

> `@lux/popdd` and `lux-popdd` are MIT-licensed for the PDD engine. Hosted
> verification, audit dashboards, and timestamp-authority anchoring are
> commercial. Treat the project as open-core, not fully open.

### 4.6 Cut "after their fifth cup of coffee"

The phrase is filler. A skeptical reader will mark it as a tell of
content-empire writing. Remove it. The article gains nothing from the
color and loses credibility with every engineer who reads it.

### 4.7 Cut the "satirical Reddit comment" line

One self-aware beat in a technical article is enough. The Reddit-comment line
was the second one and it reads as the author trying too hard. Keep at most
one moment of levity; the rest of the article should be matter-of-fact.

### 4.8 Optional: pin a "Last verified" date

Add a line at the bottom: "Last verified end-to-end: 2026-06-17 (LUX
81/81, Prospector 359/359). Repo links and test counts in the table above
were current on that date." This is the cheapest credibility move in the
document.

---

## 5. Receipts as evidence

The actual chains on disk. Cite the file path, not a summary.

| Project | Test runner | Pass / Total | Receipt file | Notes |
|---|---|---|---|---|
| LUX | `npx vitest run` | **81 / 81** (0 failed) | `~/Documents/code/lux/.lux/receipts/lux-test-8722.jsonl` | 2 receipts: `test-run:start`, `test-run:complete`. `agent_id = lux-pipeline`. |
| LUX demo | `npx tsx demo/popdd-e2e.ts` | **3011 / 3011 spec clauses**, 5 / 5 tests | `~/Documents/code/lux/.lux/receipts/chain-2026-06-17T15-26-54-543Z.jsonl` | 4 receipts: `spec-write`, `verify`, `edit`, `test-run`. Target: `weightedAverage`. |
| LUX (older runs) | `npx tsx demo/popdd-e2e.ts` | as above | `~/Documents/code/lux/.lux/receipts/chain-2026-06-17T14-30-50-035Z.jsonl` and two more in the same directory | Useful for showing the chain evolves but stays tamper-evident across runs. |
| Prospector | `pytest` | **359 / 359** (0 failed) | `.lux/receipts/` in the Prospector repo | Confirmed end-to-end per the project log; the chain file is committed alongside the test run. |
| Signal Engine | `pytest` | run-count TBD at time of writing | `.lux/receipts/` in the Signal Engine repo | `scripts/popdd_verify.py` is in place; cite the current test count from the repo's most recent CI run, not from memory. |

**Verification command for any reader:**

```bash
# LUX
cat ~/Documents/code/lux/.lux/receipts/lux-test-8722.jsonl | python3 -m json.tool --json-lines

# Validate the chain (a one-liner that catches truncation and JSON errors)
python3 -c '
import json, sys
for i, line in enumerate(open(sys.argv[1])):
    r = json.loads(line)
    assert "sequence" in r and "signature" in r, f"bad receipt at line {i}"
print(f"OK: {i+1} receipts, last sequence = {r[\"sequence\"]}")
' ~/Documents/code/lux/.lux/receipts/lux-test-8722.jsonl
```

**What the chain shows, in human terms:**

- The genesis receipt's `previous_hash` is the literal string `"GENESIS"`.
- Each subsequent receipt's `previous_hash` equals the prior receipt's
  `content_hash`. Break this link by editing any field → the chain is no
  longer self-consistent.
- Each receipt has a `signature` field. By default this is an HMAC-SHA256
  hex digest. The verification step re-derives the HMAC and compares.

---

## 6. Numbers to cite

Only the numbers below are safe to print. Anything else is either unverified
or stale. Re-run before publishing.

| Metric | Value | Source |
|---|---|---|
| Number of POPDD packages | 2 | GitHub: `chidionyema/popdd-ts`, `chidionyema/lux-popdd` |
| Runtime dependencies of `@lux/popdd` | 0 | `popdd-ts/package.json` (no `dependencies` key) |
| Runtime dependencies of `lux-popdd` | 0 | `popdd-py/pyproject.toml` (`dependencies = []`) |
| LUX test count signed by POPDD | 81 passed, 0 failed | `.lux/receipts/lux-test-8722.jsonl` |
| Prospector test count signed by POPDD | 359 passed, 0 failed | Prospector `.lux/receipts/` |
| Spec clauses verified in `weightedAverage` demo | 3011 / 3011 | `chain-2026-06-17T15-26-54-543Z.jsonl` |
| Demo test count | 5 / 5 in ~12 ms | same chain, sequence 3 |
| Number of LUX proof levels | 4 (L1 property, L2 exhaustive, L3 type-level / Curry-Howard, L4 Dafny + Z3) | `LUX_ARCHITECTURE.md` |
| Architecture spec size | ~50 KB, ~1189 lines | `~/Documents/code/LUX_ARCHITECTURE.md` |
| Default signature algorithm | HMAC-SHA256 | `@lux/popdd/src/receipt.ts` `HmacSigner` |
| Planned multi-party signer | Ed25519 (interface present, not shipped) | `Signer` Protocol in both packages |
| Demo chain size on disk | 4 receipts, ~1.9 KB JSONL | file size of `chain-2026-06-17T15-26-54-543Z.jsonl` |
| LUX test-run chain size on disk | 2 receipts, ~0.8 KB JSONL | file size of `lux-test-8722.jsonl` |
| Python version supported | `>= 3.9` | `popdd-py/pyproject.toml` `requires-python` |
| Node version supported | `>= 18` | `popdd-ts/package.json` `engines.node` |
| License (engine) | MIT | both `package.json` / `pyproject.toml` |

**Re-verify before publishing:**

```bash
# Latest test counts
cd ~/Documents/code/lux && npx vitest run --reporter=basic 2>&1 | tail -3
cd <prospector-repo> && .venv/bin/pytest -q 2>&1 | tail -3

# Latest chain file
ls -lt ~/Documents/code/lux/.lux/receipts/ | head -5

# License and zero-dep claim
grep -E '"(dependencies|license)"' ~/Documents/code/popdd-ts/package.json
grep -E '^(dependencies|license)' ~/Documents/code/popdd-py/pyproject.toml
```

If a number in the table no longer matches what those commands print, fix
the article, do not fix the table.

---

## Pre-publish gate (run all of these)

A short checklist. Any failure blocks publication.

- [ ] `cd ~/Documents/code/popdd-ts && npx tsc --noEmit` exits 0
- [ ] `cd ~/Documents/code/popdd-ts && npx vitest run` shows all tests pass
- [ ] `cd ~/Documents/code/popdd-py && .venv/bin/pytest` shows all tests pass
- [ ] `cd ~/Documents/code/lux && npx tsx demo/popdd-e2e.ts` produces 4 receipts
- [ ] The four-receipt chain file is valid JSONL (the one-liner in §5 passes)
- [ ] No claim in the article matches a row in §3 (red-light) as-written
- [ ] Every claim marked amber in §2 has its qualifier in the same sentence
- [ ] A "What POPDD Is Not" section is present and matches §4.4
- [ ] License note matches §4.5
- [ ] Tool names match §4.1 ("Dafny/Z3", never "Lean4")
- [ ] "Last verified" date is in the footer

## Post-publish triage (expected comments)

Anticipate these. Each has a one-line reply ready.

- "Show me the receipts." → link to `tests/receipt.test.ts` and the
  `.lux/receipts/` directory in the relevant repo.
- "What about the signing key?" → paste §4.4 verbatim.
- "This is just HMAC." → "Correct for the default signer. Ed25519 is the
  planned multi-party upgrade; the `Signer` interface is already in place."
- "Diff vs blockchain?" → "No consensus, no network, single-host, fast. The
  trade-off is that a single key compromise can rewrite the chain."
- "Why two packages?" → "TypeScript for Node/JS projects, Python for ML and
  data backends. Shared API contract, shared `DecisionReceipt` shape, shared
  JSONL on-disk format."

---

**Maintainer note:** this document is a sibling of
`lux-proof-driven-development/references/pre-publication-honesty-audit.md`.
That file describes the *audit pattern* (run things before saying they're
real). This file describes the *claim vocabulary* (what to say in public
writing). Both are required for a clean publication.
