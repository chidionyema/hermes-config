# Broken-Policy Resurrection Vectors — Timeline & Diagnostic

Tracks every observed resurrection path for a policy moved to `policies/archived/`. The 2026-08-08 audit documented one gate; 2026-08-15 added two more; 2026-08-17 found a fourth that bypassed all three. The pattern: each new gate was correctly designed but the assumption that "near-miss-analyzer is the only auto-creator" turned out wrong.

---

## Timeline

| Audit date | Vector | Gate prescribed | Outcome |
|---|---|---|---|
| 2026-08-08 | `idle-consolidation.py:promote_candidates` — auto-promoted provisional policies based on hits/helped without reading rule text | Gate 1: `rule_quality(p)` pre-promotion | ✅ Demoted 6 broken policies; gate works |
| 2026-08-15 | `near-miss-analyzer.py:auto_create_policies` — recreated demoted policies by id (skeleton-dedup was missing) | Gate 2 (skeleton dedup) + Gate 3 (write-collision vs `archived/`) | ✅ Both gates present in code; verified silent on subsequent runs |
| 2026-08-17 | `auto_close_identity.py:_auto_promote` at line 170-173 — bypassed Gates 1+2+3 entirely because it never touched those scripts | NONE YET (demotion only) | ❌ Structural fix prescribed but unapplied |

---

## Why each gate missed its successor vector

**Gate 1 vs. near-miss-analyzer (2026-08-15):** Gate 1 sat in the promotion path of `idle-consolidation`. The near-miss analyzer never calls `promote_candidates` — it auto-CREATES new provisional policies from scratch with new ids. Gate 1 was structurally invisible to it.

**Gates 1+2+3 vs. auto_close_identity (2026-08-17):** All three gates sit in scripts `idle-consolidation.py` and `near-miss-analyzer.py`. `auto_close_identity.py` has its own policy-write at `_auto_promote` line 173, plus a `_check_invariants` gate at line 344 that **fails open** — `except Exception: return True` means a missing validator allows every policy through.

**General pattern:** gates are scoped to the script that contains them. They protect the path they were added to, not the *class* of action. To block a class of action you must:
1. Find every code path that performs the action
2. Add the same gate (or a shared helper) to each path
3. Verify by triggering each path independently — not just one

---

## Diagnostic — exhaustive writer-probe

Run this to enumerate every script that can write to `~/.hermes/policies/*.json`:

```bash
grep -rln 'policies.*\.json' ~/.hermes/scripts/ \
  | grep -v '__pycache__\|\.bak' \
  | xargs grep -l 'json.dump\|write_text\|copy2\|copytree'
```

For each file returned, read the surrounding 30 lines and confirm whether the write is:
- (a) protected by a gate (rule_quality / id-collision / skeleton dedup / scope)
- (b) unconditional (a vulnerability if the source data is bad)
- (c) user-mediated (safe — user must explicitly trigger)

This audit (2026-08-17) found:
- `auto_close_identity.py` — **(b) unconditional** in `_auto_promote`; `_check_invariants` fail-open. **Vulnerability.**
- `near-miss-analyzer.py` — (a) protected (Gates 2+3 applied 2026-08-15).
- `idle-consolidation.py` — (a) protected (Gate 1 applied 2026-08-08).

---

## Fail-open audit pattern

For any gate function in the codebase, find fail-open returns:

```bash
grep -rn 'except.*:.*return True\|except.*:.*pass' ~/.hermes/scripts/*.py
```

Every match must have:
- A written justification in a comment, OR
- Be patched to fail-closed

For `_check_invariants` specifically, the fix is one character:

```python
def _check_invariants(self, policy: dict) -> bool:
    try:
        ...
        return report.passed
    except Exception:
        return False   # was: return True — fail-open bypasses the gate
```

A missing `constitutional_validator` should block the policy write, not silently allow it. If the validator is genuinely unavailable in this deployment, fix the import path or install the module — do not let the gate vanish.

---

## Layer-verification reflex (encoded as a check, not a rule)

When the same resurrection recurs after a fix is applied, do NOT immediately add another gate. Instead:

1. Run the writer-probe above — list every writer.
2. For each writer, ask: "did the previous fix touch this path?" If no, this is your vector.
3. Re-read the gate logic of the script that bypassed the fix — look for `try: ... except Exception: return True` patterns.
4. Only after identifying the bypass mechanism, add the gate to the correct path.

The temptation is to assume "the previously-fixed script is the only relevant one" because the previous audit identified it. That assumption is false for any class of action that has more than one writer.

---

## Verification of full fix

After applying the patches:

```bash
# 1. Confirm collision count is 0
python3 -c "
import json, glob
active = {p.split('/')[-1].replace('.json','') for p in glob.glob('/Users/chidionyema/.hermes/policies/*.json')}
archived = {p.split('/')[-1].replace('.json','') for p in glob.glob('/Users/chidionyema/.hermes/policies/archived/*.json')}
print(f'collisions: {len(active & archived)}')
"
# Expect: collisions: 0

# 2. Run one idle-learning cycle
~/.hermes/scripts/idle-learning-run.sh

# 3. Re-run collision check
# Expect: collisions: 0 (no resurrection)

# 4. Inline test of the fail-closed invariant
python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('aci', '/Users/chidionyema/.hermes/scripts/auto_close_identity.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
i = m.AutoCloseIdentity.__new__(m.AutoCloseIdentity)
# Pathological: validator raises
class BadValidator:
    def __init__(self): pass
    def __call__(self): raise RuntimeError('no validator')
i.validate = BadValidator()
p = {'id':'test-policy','rule':'Handle test issues proactively.'}
print('fail-closed blocks:', i._check_invariants(p) == False)  # must be True
"
```

If step 4 returns `False`, the gate is fail-open and the fix is incomplete. Repeat the patch.