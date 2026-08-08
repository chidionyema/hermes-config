# Symbol-Rotation Incident — 2026-08-02
# Symbol-Rotation Incident — 2026-08-02

> **STATUS: CORRECTED 2026-08-02.** The original audit reported 6 broken
> cross-module references. Runtime verification proved all 6 resolve
> cleanly. The audit recipe's regex required single-line `def name(`,
> but `dispatch(` is multi-line in `estate_pd/se.py` and `Proof` is a
> class (not a `def`). The audit was a static-AST false positive. See
> § "Correction" below for the full disambiguation and the lesson every
> future audit must internalize.

## The original 6 "broken" refs (revised status)

| import in `estate.py` | expected symbol | original audit | runtime check |
|---|---|---|---|
| `from .daemons import confirm_card as d_confirm` | `daemons.confirm_card` | missing | **EXISTS** (daemons.py:449) |
| `from .daemons import render_logs as d_logs` | `daemons.render_logs` | missing | **EXISTS** (daemons.py:391) |
| `from .daemons import run_op as d_run` | `daemons.run_op` | missing | **EXISTS** (daemons.py:528) |
| `from .estate_pd import dispatch as _pd_dispatch` | `estate_pd.dispatch` | missing | **EXISTS** (estate_pd.py:10) |
| `from .estate_se import dispatch as _se_dispatch` | `estate_se.dispatch` | missing | **EXISTS** (estate_se.py:10) |
| `from .proof import Proof` | `proof.Proof` | missing | **EXISTS as class** (proof.py:44) |

All 6 import successfully at runtime. The dispatcher table is intact.

## Why each "missing" finding was wrong (the regex mistake)

The original audit recipe used:

```python
if not re.search(rf"^(?:async\s+)?def\s+{re.escape(func)}\s*\(", src, re.MULTILINE):
    is_class = bool(re.search(rf"^class\s+{re.escape(func)}\b", src, re.MULTILINE))
    if not is_class:
        missing.append((mod, func, "SYMBOL_MISSING"))
```

Two failure modes the regex did not catch:

1. **Multi-line signatures.** `dispatch(` in `estate_pd.py:10` and
   `estate_se.py:10` is the start of a multi-line `def` signature. The
   audit only matched `^def name(`. `^def dispatch\s*\(` did not match
   because the open-paren is on the next line.

2. **Class imports without `class` keyword check happening first.** The
   recipe ran `is_class` *inside* the `if not re.search(...)` branch —
   so a `class Proof` declaration would only be checked AFTER the
   function regex missed. It did check `Proof` against `^class Proof\b`,
   but the audit at the time ran the regex on a *different* slice of
   text, and the dispatch signatures in `estate_pd/se.py` were not
   re-verified. The audit was wrong twice on the same day.

The correct detection order is: check `class` AND `def` AND multi-line
signatures in one pass, then verify each match by **actually importing
the symbol at runtime**.

## Correction

Audit re-run on 2026-08-02 with both static + runtime checks:

```bash
# Static: regex + AST
python3 -c "
import ast
from pathlib import Path
for mod in ['daemons', 'estate_pd', 'estate_se', 'proof']:
    src = Path(f'{mod}.py').read_text()
    tree = ast.parse(src)
    defs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    print(f'{mod}: defs={defs} classes={classes}')
"

# Runtime: real import
python3 -c "
import sys
sys.path.insert(0, '/Users/chidionyema/.hermes/hermes-agent')
from gateway.operator_shell.daemons import confirm_card, render_logs, run_op
from gateway.operator_shell.estate_pd import dispatch as _pd_dispatch
from gateway.operator_shell.estate_se import dispatch as _se_dispatch
from gateway.operator_shell.proof import Proof
print('OK: all 6 symbols import cleanly')
"
```

Result: **all 6 symbols resolve at both AST and runtime. The "broken refs"
table is wrong and the fix work it prescribed is not needed.**

## Lesson: every static-audit finding needs a runtime probe

The skill body's audit recipe (Axis 3 — Cross-module reference validity)
**must add a runtime verification step** before reporting any symbol as
missing. The original recipe trusted the regex. The regex was wrong on
multi-line signatures and class-vs-function collisions.

**Updated recipe:** after the static regex pass, run a real import for
each missing candidate:

```python
# After the static regex pass, verify the candidates are actually missing:
import importlib.util, sys
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"
sys.path.insert(0, str(SHELL.parent.parent))

verified_missing = []
for mod, func, why in missing:
    if why == "MODULE_MISSING":
        verified_missing.append((mod, func, why))
        continue
    # Real import to confirm the static finding
    spec = importlib.util.spec_from_file_location(
        f"runtime_check.{mod}", SHELL / f"{mod}.py"
    )
    if spec is None or spec.loader is None:
        verified_missing.append((mod, func, "MODULE_NOT_LOADABLE"))
        continue
    mod_obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod_obj)
    if not hasattr(mod_obj, func):
        verified_missing.append((mod, func, "SYMBOL_RUNTIME_MISSING"))
    # else: false positive — the symbol exists, the regex was wrong
```

**The rule:** a static finding is a *lead*, not a *finding*. The finding
is only confirmed when runtime says so. Before reporting "6 broken refs,"
the audit must show the runtime output for each one.

## Pitfalls (now with the runtime-verification correction)

### Don't infer fixes from the import line alone

These 6 cases required actually reading `daemons.py`, `proof.py`,
`estate_pd.py`, and `estate_se.py` to know whether to define a missing
symbol or repoint the alias. The audit's table is the *alarms*, not the
*fixes*.

### Don't trust a regex-only audit for class-vs-function collisions

`class Proof` declares a class. `def Proof(` is a function. A regex that
only matches `^def name(` will miss classes. A regex that only matches
`^class name` will miss functions. **Run both, AND verify at runtime.**

### Multi-line `def` signatures break single-line regexes

`def dispatch(\n    arg: str,\n) -> ...:` will not match `^def dispatch\(`
because the open-paren is on the next line. Either use AST (`ast.walk`)
or allow whitespace between the name and the paren in the regex:
`^def\s+{name}\s*\(`. Same for `class`.

### The audit recipe in SKILL.md needs the runtime gate

The current Axis 3 code in the SKILL.md recipe does not have a runtime
verification step. It SHOULD — every "missing symbol" finding must be
confirmed by `importlib.util.spec_from_file_location` + `hasattr` before
being reported to the user. Future audits must add this gate.
