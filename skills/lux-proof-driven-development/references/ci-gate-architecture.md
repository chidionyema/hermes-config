# CI Gate Architecture — Cross-Language POPDD Enforcement

## Design

A single self-contained Python+shell script (`scripts/ci-gate.sh`) that runs in any language repo (Python, TypeScript, C#):

```
git diff --name-only HEAD <ref>
        │
        ▼
Extract function/class names from modified files
  (.py → def/class, .ts → function/class/const arrow, .cs → class/method)
        │
        ▼
Load all POPDD receipts from .lux/receipts/*.jsonl
        │
        ▼
Check every modified function has a matching PASS receipt
        │
        ├── All covered → exit 0
        └── Any missing  → exit 1 (list printed)
```

## Key Properties

- **Language-agnostic**: regex extraction per file extension, same receipt format
- **No external deps**: stdlib `json`, `subprocess`, `os`, `re`, `pathlib`
- **Merge-base aware**: compares against `git merge-base HEAD <ref>` (default: main)
- **Receipt tolerance**: scans ALL `.lux/receipts/*.jsonl`, not just today's — permits pre-verified functions

## Usage

```bash
# Check current branch against main
cd /path/to/repo && sh scripts/ci-gate.sh

# Check against a specific ref
sh scripts/ci-gate.sh origin/main
```

## Pre-commit Hook Integration

Each repo's `.lux/hooks/pre-commit` calls `scripts/ci-gate.sh` before every commit:

- **LUX** (TS): runs `npx tsx src/cli.ts check` (native LUX check command)
- **Signal Engine** (Python): runs `sh scripts/ci-gate.sh`
- **Prospector** (Python): runs `sh scripts/ci-gate.sh`

Install via: `ln -sf ../../.lux/hooks/pre-commit .git/hooks/pre-commit`

## Coverage Note

The gate checks *function-level* coverage. A single test-run receipt (from `popdd_verify.py`) for the whole suite does NOT satisfy it — each modified function needs its own receipt from `lux spec verify` or equivalent inline attestation.

This means the workflow is:
1. `lux spec create myFunction`
2. Edit spec + implement code
3. `lux spec verify myFunction` → appends receipt
4. Commit (gate passes)

The `popdd_verify.py` scripts are for *batch test runs*, not individual function coverage.
