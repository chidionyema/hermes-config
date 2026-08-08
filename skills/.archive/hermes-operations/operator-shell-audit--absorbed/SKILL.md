---
name: operator-shell-audit
description: "Audit the Hermes operator shell (`~/.hermes/hermes-agent/gateway/operator_shell/`) for panel density, chrome consistency, and broken cross-module references. Three-axis rubric: (1) count /cmd action lines per panel and flag density outliers, (2) verify every panel wraps its body in `with_nav(...)` rather than calling `nav(...)` ad-hoc, (3) cross-check every `from gateway.operator_shell.X import Y` against `X.py` to surface missing symbols (especially under `as alias` clauses, which hide behind rewrites). Use when the user asks 'audit the operator shell', 'check the panel renderers', 'is the shell consistent', 'too many buttons', 'broken dispatch', or before shipping a batch of panel edits where drift would be expensive to debug after-the-fact."
version: 1.0.0
author: Otto
license: MIT
metadata:
  hermes:
    tags: [operator-shell, audit, panel-chrome, cross-module-refs, telegram, text-mode]
    related_skills: [text-mode-ui-design, estate-management, dropped-ball-prevention]
prerequisites:
  files:
    - ~/.hermes/hermes-agent/gateway/operator_shell/panel_chrome.py
    - ~/.hermes/hermes-agent/gateway/operator_shell/estate.py
---

# Operator Shell Audit

When the operator shell (the Telegram text-mode panel set driving the `/status`, `/daemons`, `/mission`, etc. surfaces) feels overgrown, inconsistent, or buggy at the seams, this skill gives the rubric to diagnose it in one pass. The three axes are independent and each maps to one deliverable; a single audit session can ship all three fixes.

## Why this skill exists

Three recurring defect classes show up here, each with a different shape:

1. **Density rot** — heavy panels (summary_card, daemons) accumulate `/cmd` lines until Telegram cards become longer than the chat scroll. The user feels it ("too many buttons"), but no one counts them.
2. **Chrome drift** — `panel_chrome.py` exports a canonical `with_nav(...)` wrapper, but panels hand-roll `nav(...)` calls. Nav ordering, footer placement, and tap patterns drift across panels.
3. **Symbol rot** — `estate.py`'s dispatch table imports symbols via `as alias` clauses. When a panel renames a function, the alias still loads — but the symbol behind it goes missing. The dispatcher fails at call time, not import time. Quietly.

Estate-management audits the *whole* stack. Project-health-audit audits *projects*. Text-mode-ui-design audits *designs*. None of them audit the operator shell itself.

## The Three-Axis Rubric

Run all three. Each axis produces a one-screen receipt. Ship all three fixes in one PR or in one commit per axis.

### Axis 1 — Button density

Count tap-able action lines per panel. The active surface is *the rendered text*, not `InlineKeyboardButton`. The right metric is the number of `/cmd` paths and the number of framed action labels (`backtick`-wrapped, arrow-prefixed, or plus-prefixed).

**Counting recipe:**

```python
import re
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"

def action_count(src: str) -> dict:
    return {
        "/cmd":       len(re.findall(r"/[a-z_][a-z0-9_]+", src)),
        "backtick":   len(re.findall(r"`[↩◀▶▸▼▲…↪][^`]*`", src)),
        "arrow_line": len(re.findall(r"^\s*[▸›►▷]\s", src, re.MULTILINE)),
        "plus_line":  len(re.findall(r"^\s*\+[a-z_]+", src, re.MULTILINE)),
    }
```

**Density thresholds** (tuned for Telegram mobile; cards should fit 1.5 screens):

| `/cmd` count | verdict | action |
|---|---|---|
| 0–7   | ✅ fits   | leave alone |
| 8–14  | 🟡 dense | consider tabbed sub-panels |
| 15+   | 🔴 broken | split into a parent + children, or collapse secondary actions behind a `+more` row |

**Known density offenders (2026-08-02 baseline):**

| panel | `/cmd` | lines | action |
|---|---:|---:|---|
| `summary_card.py` | **42** | 916 | split into `summary_card` (overview) + `summary_card_detail` (per-knob drill-down) |
| `daemons.py` | **28** | 588 | collapse per-daemon controls into a default-action button + per-daemon detail panel |
| `cron_ops.py` | 20 | 168 | hide rarely-used ops behind `+more` |
| `prospector_daemon.py` | 16 | 995 | split status vs. config vs. recent batches |

Density is a function of *panel length / panel content*, not just count. A 916-line panel with 42 actions is doing too much.

### Axis 2 — Chrome adherence

Every panel must end its render path in `with_nav(...)` so the nav footer is consistent. Direct `nav(...)` calls drift across panels (different children, different orderings, sometimes missing entirely).

**Chrome audit recipe:**

```python
import re
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"

panels = [p for p in SHELL.glob("*.py") if p.name != "panel_chrome.py"]
for p in sorted(panels):
    src = p.read_text()
    imports_chrome   = "panel_chrome" in src
    uses_with_nav    = bool(re.search(r"\bwith_nav\s*\(", src))
    direct_nav_calls = len(re.findall(r"\bnav\s*\(", src))
    flag = "✅" if (not imports_chrome or uses_with_nav) else \
           ("⚠️  ad-hoc" if direct_nav_calls else "✅")
    print(f"{p.name:<28} imports={imports_chrome}  with_nav={uses_with_nav}  nav()={direct_nav_calls}  {flag}")
```

**Expected pattern (canonical):**

```python
from .panel_chrome import with_nav

async def render_X(ctx):
    body = compose_X_body(ctx)
    return await with_nav(body, section="X", ctx=ctx)
```

**Pitfall:** `nav(...)` is the *raw* helper. `with_nav(...)` is the wrapper that wraps `compose → nav → clip → footer → header` in one call. Panels using raw `nav(...)` are doing chrome by hand and that is where drift enters.

If the audit shows panels using `nav(...)` directly, the fix is mechanical: replace `nav(body, ...)` with `return await with_nav(body, section=name, ctx=ctx)` and add `from .panel_chrome import with_nav` to the imports. Test before committing.

### Axis 3 — Cross-module reference validity

`estate.py`'s dispatch table imports dozens of render functions across panels. When a panel renames a function, the dispatcher's `as alias` clause still parses (because `from X import does_not_exist as y` is *valid Python*). The dispatcher breaks at the first call.

**Reference audit recipe:**

```python
import re
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"
CALLER = (SHELL / "estate.py").read_text()

imported = set()
# Single-line imports
for m in re.finditer(r"from\s+gateway\.operator_shell\.(\w+)\s+import\s+([^\n]+)", CALLER):
    mod, names = m.group(1), m.group(2)
    for n in names.split(","):
        n = n.strip().split(" as ")[0]  # strip alias
        if n and not n.startswith("#"):
            imported.add((mod, n))

# Multi-line imports
for m in re.finditer(r"from\s+gateway\.operator_shell\.(\w+)\s+import\s+\(([^)]+)\)", CALLER, re.DOTALL):
    mod, block = m.group(1), m.group(2)
    for n in block.split(","):
        n = n.strip().split(" as ")[0]
        if n and not n.startswith("#"):
            imported.add((mod, n))

missing = []
for mod, func in sorted(imported):
    fp = SHELL / f"{mod}.py"
    if not fp.exists():
        missing.append((mod, func, "MODULE_MISSING"))
        continue
    src = fp.read_text()
    # Use AST — handles multi-line signatures and class-vs-function uniformly.
    # A single-line regex breaks on `def dispatch(\n    arg: str,\n)` (open-paren
    # on next line) and on class-vs-function collisions. AST walks both kinds.
    try:
        import ast
        tree = ast.parse(src)
        defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    except SyntaxError as e:
        missing.append((mod, func, f"PARSE_ERROR: {e}"))
        continue
    if func not in defs and func not in classes:
        missing.append((mod, func, "SYMBOL_MISSING"))

# RUNTIME GATE — every "missing" candidate must be confirmed by a real
# import. The regex+AST pass is a *lead*, not a *finding*. False positives
# on multi-line defs and class-vs-function are common. The runtime probe
# is the only thing that decides.
import importlib.util, sys
verified = []
for mod, func, why in missing:
    if why == "MODULE_MISSING":
        verified.append((mod, func, why))
        continue
    fp = SHELL / f"{mod}.py"
    spec = importlib.util.spec_from_file_location(f"runtime_check.{mod}", fp)
    if spec is None or spec.loader is None:
        verified.append((mod, func, "MODULE_NOT_LOADABLE"))
        continue
    sys.path.insert(0, str(SHELL.parent.parent))
    mod_obj = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod_obj)
    except Exception as e:
        verified.append((mod, func, f"IMPORT_ERROR: {type(e).__name__}"))
        continue
    if not hasattr(mod_obj, func):
        verified.append((mod, func, "SYMBOL_RUNTIME_MISSING"))
    # else: false positive — the symbol exists, the regex/AST was wrong.
    # Do NOT report it. (This is how the 2026-08-02 audit caught its own
    # false positives: AST said "missing", runtime said "exists".)

for mod, func, why in verified:
    print(f"  ✗ {mod}.{func}  ({why})")
```

**Runtime-gate pitfall (2026-08-02):** The original audit recipe had only
the regex+AST pass. It flagged 6 broken refs that were all false positives
(multi-line `def` signatures and class-vs-function collisions). The
corrected recipe above does AST first (uniform handling of classes and
multi-line sigs), then `importlib`+`hasattr` to confirm each candidate.
A static finding is a *lead*, not a *finding*. The runtime probe is the
only thing that decides.

## Pitfalls

### Don't use `InlineKeyboardButton` as the density metric
These panels are text-mode. Buttons are `/cmd` lines in the body, not Telegram reply markup. Counting `InlineKeyboardButton(...)` will return 0 for every panel — useless. Count `/cmd` instead.

### Don't migrate chrome + density + symbols in one big patch
Each axis is independent. Ship the symbol-fix first (smallest, unblocks callers), then chrome (mechanical pass), then density (design decision that needs user input). Three commits, three receipts.

### Aliases hide behind the rename
`from daemons import confirm_card as d_confirm` looks fine on the surface but `confirm_card` may not exist in `daemons.py`. Always check the original symbol name, not just the alias.

### Don't fabricate the audit output
If the script finds zero missing imports, the table is empty. If the script says 6 broken refs, those are the 6 broken refs. Don't add a "Recommended triptych" unless the audit actually surfaced issues. The audit table IS the user-facing message.

### Run the audit before, not after, panel edits
Panel renaming is silent — there's no syntax error when you rename `confirm_card → confirm`, the alias still loads. Run axis 3 immediately after any panel rename to catch what the linter won't.

### Don't ship fixes that touch `gateway/operator_shell/*.py` autonomously
`gateway/operator_shell/` is Claude Code's single-writer lane (pre-commit `LANE GUARD` hook rejects non-Claude commits). The audit may freely read, parse, and probe — but the actual `with_nav` migration, density cap, and symbol-rename fixes must be handed to Claude. Discoverable via `git commit` exit-1 message: "these files are in Claude's single-writer lane." Escape hatch is `--no-verify`, but only when the user explicitly overrides lane-guard. Discovered 2026-08-02 during the first with_nav migration attempt.

### Static audit findings need runtime verification before any "fix"
A regex finding is a *lead*, not a *finding*. The 2026-08-02 audit flagged 6 "broken refs" in `estate.py` that all turned out to be false positives — multi-line `def` signatures and `class Proof` declarations broke the single-line regex. Always run `importlib.util.spec_from_file_location` + `hasattr` to confirm a missing-symbol finding before prescribing a fix. The skill's Axis 3 recipe now does this (see § "Critical gotcha" above), but if you're running an older version of the recipe, add the runtime gate manually.

## Verification Protocol

After fixing any axis:

| Axis | Verification |
|---|---|
| Density | Re-run axis 1; `/cmd` count should land below threshold. |
| Chrome | Re-run axis 2; flag column should read `✅` for every panel that imports chrome. |
| Symbols | Re-run axis 3; `missing` list should be empty. Also: run the operator shell's smoke test (render `/status` end-to-end) — dispatcher table must reach all referenced symbols without `ImportError`. |

A substrate fix is incomplete without re-running the audit. The audit's exit-0 is the receipt.

## References

- `references/density-baseline-2026-08-02.md` — frozen `/cmd` count table + thresholds, with the panels that already cross them. Re-run the audit and diff against this.
- `references/chrome-migration-recipe.md` — mechanical pass to convert `nav(...)` → `with_nav(...)` across panels. Pre/post signatures + edge cases.
- `references/symbol-rotation-incident-2026-08-02.md` — the 6-symbol gap that bit `estate.py` on 2026-08-02, with the disambiguation for class-vs-function collisions.

## Scripts

- `scripts/run-audit.sh` — runs all three axes and prints a single receipt. Exit 0 if clean, exit 1 if any axis finds a problem. Wire to a low-cadence cron (every hour or daily) to catch regressions after panel edits.

## How to verify after a fix

After fixing any axis, run `bash run-audit.sh` again. The exit code is the receipt: 0 = clean, 1 = something still wrong. Substrate-fix proof is "audit returned 1 before, 0 after." Don't claim a fix without running the script.
