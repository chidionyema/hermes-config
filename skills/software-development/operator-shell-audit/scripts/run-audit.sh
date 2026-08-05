#!/usr/bin/env bash
# run-audit.sh — operator shell audit, all three axes.
# Exit 0 if clean, exit 1 if any axis finds a problem.
#
# Usage: bash run-audit.sh [--json]
#
# Output is human-readable by default. --json emits a single-line JSON
# object per axis for cron consumption.

set -uo pipefail

SHELL_DIR="$HOME/.hermes/hermes-agent/gateway/operator_shell"
JSON="${1:-}"

if [[ ! -d "$SHELL_DIR" ]]; then
    echo "FATAL: $SHELL_DIR not found" >&2
    exit 2
fi

PY_OUTPUT=$(python3 <<'PY'
import re, json, sys
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"

# ---------- Axis 1: density ----------
density = []
for fp in sorted(SHELL.glob("*.py")):
    src = fp.read_text()
    cmd = len(re.findall(r"/[a-z_][a-z0-9_]+", src))
    rows = len(src.splitlines())
    if cmd >= 15:
        verdict = "BROKEN"
    elif cmd >= 8:
        verdict = "DENSE"
    else:
        verdict = "OK"
    density.append({"panel": fp.name, "cmds": cmd, "lines": rows, "verdict": verdict})

# ---------- Axis 2: chrome ----------
chrome = []
for fp in sorted(SHELL.glob("*.py")):
    if fp.name == "panel_chrome.py":
        continue
    src = fp.read_text()
    imports_chrome   = "panel_chrome" in src
    uses_with_nav    = bool(re.search(r"\bwith_nav\s*\(", src))
    direct_nav_calls = len(re.findall(r"\bnav\s*\(", src))

    if not imports_chrome:
        verdict = "OK"          # not a panel — leave alone
    elif uses_with_nav:
        verdict = "OK"
    elif direct_nav_calls > 0:
        verdict = "AD_HOC_NAV"
    else:
        verdict = "OK"

    chrome.append({
        "panel": fp.name,
        "imports_chrome": imports_chrome,
        "with_nav": uses_with_nav,
        "ad_hoc_nav": direct_nav_calls,
        "verdict": verdict,
    })

# ---------- Axis 3: cross-module refs ----------
caller_src = (SHELL / "estate.py").read_text()

imported = set()
for m in re.finditer(r"from\s+gateway\.operator_shell\.(\w+)\s+import\s+([^\n]+)", caller_src):
    mod, names = m.group(1), m.group(2)
    for n in names.split(","):
        n = n.strip().split(" as ")[0]
        if n and not n.startswith("#"):
            imported.add((mod, n.strip()))

for m in re.finditer(r"from\s+gateway\.operator_shell\.(\w+)\s+import\s+\(([^)]+)\)", caller_src, re.DOTALL):
    mod, block = m.group(1), m.group(2)
    for n in block.split(","):
        n = n.strip().split(" as ")[0]
        if n and not n.startswith("#"):
            imported.add((mod, n.strip()))

missing = []
import ast, importlib.util, sys
sys.path.insert(0, str(SHELL.parent.parent))  # for runtime probes
for mod, func in sorted(imported):
    fp = SHELL / f"{mod}.py"
    if not fp.exists():
        missing.append({"module": mod, "func": func, "reason": "MODULE_MISSING"})
        continue
    src = fp.read_text()
    # Static: AST walks both `def` and `class` uniformly, handles multi-line
    # signatures. A regex that requires `name(` on a single line breaks on
    # `def dispatch(\n    arg: str,\n)`.
    try:
        tree = ast.parse(src)
        defs = {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    except SyntaxError as e:
        missing.append({"module": mod, "func": func, "reason": f"PARSE_ERROR: {e}"})
        continue
    if func in defs or func in classes:
        continue  # static found it

    # Runtime gate: confirm the AST finding before reporting. A static
    # finding is a lead, not a finding. False positives on multi-line
    # defs and class-vs-function collisions are common — only the runtime
    # probe decides.
    spec = importlib.util.spec_from_file_location(f"audit_runtime_check.{mod}", fp)
    if spec is None or spec.loader is None:
        missing.append({"module": mod, "func": func, "reason": "MODULE_NOT_LOADABLE"})
        continue
    try:
        mod_obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod_obj)
    except Exception as e:
        missing.append({"module": mod, "func": func,
                        "reason": f"IMPORT_ERROR: {type(e).__name__}: {e}"})
        continue
    if not hasattr(mod_obj, func):
        missing.append({"module": mod, "func": func, "reason": "SYMBOL_RUNTIME_MISSING"})
    # else: false positive — symbol exists, AST was wrong. Do NOT report.

result = {
    "density": density,
    "chrome": chrome,
    "cross_module_missing": missing,
    "summary": {
        "density_broken": sum(1 for d in density if d["verdict"] == "BROKEN"),
        "chrome_ad_hoc": sum(1 for c in chrome if c["verdict"] == "AD_HOC_NAV"),
        "missing_refs": len(missing),
    },
}
print(json.dumps(result, indent=2))
PY
)

if [[ "$JSON" == "--json" ]]; then
    echo "$PY_OUTPUT"
    exit_code=$?
else
    echo "$PY_OUTPUT" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())

print('=== AXIS 1 — DENSITY (top 10 worst) ===')
worst = sorted(d['density'], key=lambda x: -x['cmds'])[:10]
for r in worst:
    print(f\"  {r['panel']:<26} {r['cmds']:>3} cmds / {r['lines']:>4} lines  {r['verdict']}\")

print()
print('=== AXIS 2 — CHROME ADHERENCE ===')
adhoc = [c for c in d['chrome'] if c['verdict'] == 'AD_HOC_NAV']
if adhoc:
    print(f'  {len(adhoc)} panel(s) call nav() directly:')
    for c in adhoc:
        print(f\"    - {c['panel']}  ({c['ad_hoc_nav']} ad-hoc nav() calls)\")
else:
    print('  All chrome-using panels wrap with with_nav().')

print()
print('=== AXIS 3 — CROSS-MODULE REFS ===')
missing = d['cross_module_missing']
if missing:
    for m in missing:
        print(f\"  ✗ {m['module']}.{m['func']}  ({m['reason']})\")
else:
    print('  All cross-module imports resolve.')

print()
print('=== SUMMARY ===')
s = d['summary']
print(f\"  density_broken : {s['density_broken']}\")
print(f\"  chrome_ad_hoc  : {s['chrome_ad_hoc']}\")
print(f\"  missing_refs   : {s['missing_refs']}\")
"
fi

# Exit 1 if anything is wrong. Substrate-fix receipt: re-run must return 0.
TOTAL_PROBLEMS=$(echo "$PY_OUTPUT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(sum(d['summary'].values()))")
if [[ "$TOTAL_PROBLEMS" -gt 0 ]]; then
    exit 1
fi
exit 0
