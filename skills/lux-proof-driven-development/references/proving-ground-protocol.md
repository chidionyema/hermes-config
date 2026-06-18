# Proving-Ground Protocol — Every Claim Gets a Receipt

## The Problem

This session (2026-06-18) catalogued systemic failures in proof delivery:
1. Packages were claimed "done" but never published to registries (npm/PyPI)
2. Integrations were claimed "working" but test suites were never actually run
3. Fixes were claimed "deployed" but the cron was still firing the old version
4. E2e tests were described but the verification script had bugs that prevented clean execution

**The root cause is not technical incompetence but procedural:** no step exists between "I claim X works" and "here is the signed receipt proving X works." Every statement is treated as true until proven otherwise.

## The Fix: Proving-Ground Protocol

Every claim must produce a verifiable artifact before it's delivered. The artifact must be:

1. **Executable** — another agent can re-run it and get the same result
2. **Transparent** — full output, not summary or highlights
3. **Cross-checked** — the proving ground audits all claims independently
4. **Immediate** — no "I'll verify after I finish this other thing"

## The Infrastructure

### `~/.hermes/scripts/proving-ground.py`

Runs every 2 hours as a no-agent cron job (`proving-ground-audit`). It checks:

| Section | What it tests | Why |
|---|---|---|
| Package tests | Runs every test suite for all 4 packages | Tests pass or package is broken |
| Integration health | Imports correct from Signal Engine, Prospector, LUX | Integration is live |
| Published state | Checks npm + PyPI for published versions | Package is actually shippable |
| E2e chain | Runs `e2e-proof.py` and counts PASSED checks | Full stack works end-to-end |

**Schema:** Output is a JSONL log at `~/.lux/proving-ground/<date>.jsonl` with one entry per check: `{project, check, passed, exit_code, summary, timestamp}`.

### `~/Documents/code/e2e-proof.py`

End-to-end verification script that covers:
- POPDD standalone: create signer, chain, append, save, load, tamper detection
- lux-spec standalone: correct impl PASS, buggy impl FAIL, invariants, edge cases
- lux-spec + POPDD integrated: VerifiedFunction + signed receipts
- Cross-project: Signal Engine + Prospector imports and `popdd_agent.py` shim verification

## How to Use

### When making ANY claim

Before sending the message, run the relevant check:

```bash
# Claim: "all 4 packages work"
python3 ~/.hermes/scripts/proving-ground.py

# Claim: "the full e2e stack works"
cd ~/Documents/code && python3 e2e-proof.py
```

Include the output in the message. If the check fails, do not deliver the claim.

### When a users says "prove it"

Run the proving ground or e2e proof. Do not describe past results — re-run now.

### When fixing a bug

After the fix, do not claim it's fixed. Instead:
1. Run the fix (terminal command, file write, etc.)
2. Run the trigger that previously showed the bug (cron, test, probe)
3. Run proving-ground.py to capture the new state
4. Deliver the receipt

## The Credential Trap

The proving ground checks npm/PyPI registry status. These checks will fail if:
- npm is not authenticated (`npm whoami → ENEEDAUTH`) — needs `npm login`
- hatch is not authenticated for PyPI — needs `hatch auth`

These are the only legitimate failures in the proving ground. Every other failure is actionable.

## Cron Integration

```
Job: proving-ground-audit (id: 3c5a966ee24e)
Schedule: every 2h
Script: proving-ground.py
Mode: no_agent (script output delivered verbatim)
```

The job delivers the full audit to Telegram. Failures are flagged with ❌ and listed explicitly.
