# PDD vs POPDD — How They Relate

A frequent source of confusion. These are two independent layers that complement each other.

## Short Version

| Layer | What it proves | Fail mode | Metaphor |
|---|---|---|---|
| **PDD** (LUX) | The code is *correct* for all valid inputs | A test fails → bug found | An inspector checks the blueprint |
| **POPDD** | The proof *actually happened* and wasn't tampered with | The hash chain breaks → audit trail compromised | A notary stamps the inspector's report |

**PDD** is the methodology. **POPDD** is the chain-of-custody for that methodology's output.

## Independence

- **POPDD doesn't need PDD.** You can sign receipts for any action ("ran 309 tests, 309 passed") without any formal specification layer.
- **PDD doesn't need POPDD.** You can write specs and run the verifier without ever saving a receipt.
- **Together they're stronger.** PDD proves the code is right; POPDD proves you can prove it was right *yesterday* and that no one changed the record since.

## What Each Package Does

| Package | Implements | Language | Lives at |
|---|---|---|---|
| `@lux/popdd` / `lux-popdd` | POPDD only | TypeScript + Python | `~/Documents/code/popdd-ts/`, `~/Documents/code/popdd-py/` |
| `lux-engine` (LUX) | PDD + POPDD consumer | TypeScript | `~/Documents/code/lux/` |

LUX imports `@lux/popdd` as a dependency. The Signal Engine and Prospector import `lux-popdd` directly without LUX at all.

## When the User Asks

| If they ask | Answer |
|---|---|
| "Do we have PDD?" | Yes — LUX implements it. Write specs, run `lux verify`, get proof across the entire input space. |
| "Do we have POPDD?" | Yes — two packages (TS + Py), three projects signed. Cryptographic chain-of-custody for verifications. |
| "How do they relate?" | PDD proves code is correct. POPDD proves the proof exists and wasn't tampered with. They're independent but complementary. |
| "Do I need both?" | No. Use POPDD alone for audit trails. Use PDD alone for correctness proofs. Use both for maximum confidence. |
