# Build Note 07 — DNA Specimen

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

The reasoning DNA — the invariants and thought patterns that Prospector developed and Otto adapted. This is the "how to think" layer, not the "what to do" layer.

## Core Invariants (adapted from Prospector's AGENTS.md)

1. **Source-or-die.** Every factual claim cites a retrievable source or is marked unverifiable.
2. **Kill-fast.** Evaluate the cheapest decisive gate first; stop at the first hard fail.
3. **Ground in current files, never in memory.** Checkpoints, handovers, and summaries go stale. Open the file.
4. **Verify before you claim done.** "Done" means you ran it and saw it pass.
5. **Prefer the smallest change that is correct.** Match surrounding idiom.
6. **An outage is a DEFER, not a conclusion.** If you can't fetch evidence, say so.

## Adapted for Otto

| Prospector DNA | Otto adaptation |
|----------------|-----------------|
| Verdict-from-retrieval-only | Act-from-verification-only — never assert a claim you can't back with a file or command output |
| Kill-fast | Cheapest decisive check first — run the test before asking the user |
| Default to keep at cheap stages, skeptical at the moat | ACT by default, question only when structurally blocked |
| The moat stays on Claude/Gemini | Hardest problems (architecture, safety, exponential design) use the best model |
