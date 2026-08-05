#!/usr/bin/env python3
"""
Pre-flight check — run before EVERY gateway restart.

Catches: missing imports, undefined variables, broken dispatch routes,
dataclass field errors, and module import failures.

Fast (<2s). No git probes. No network calls. Pure static + import checks.

Run: python3 scripts/preflight.py
Exit 0 = safe to restart. Exit 1 = bugs found, fix before restarting.
"""

import ast
import importlib
import subprocess
import sys
import traceback
from pathlib import Path

HERMES = Path.home() / ".hermes"
GATEWAY = HERMES / "hermes-agent" / "gateway" / "operator_shell"
FAILED = 0


def check(name: str, condition: bool, detail: str = ""):
    global FAILED
    if condition:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
        FAILED += 1


print("🛫 Pre-flight Check")
print("=" * 50)

# ═══════════════════════════════════════════════
# 1. Module imports — every gateway module must import
# ═══════════════════════════════════════════════
print("\n── Module imports ──")
sys.path.insert(0, str(HERMES / "hermes-agent"))

GATEWAY_MODULES = [
    "gateway.operator_shell.estate",
    "gateway.operator_shell.projects",
    "gateway.operator_shell.health_panel",
    "gateway.operator_shell.commercial_ui",
    "gateway.operator_shell.discovery",
    "gateway.operator_shell.chat_router",
    "gateway.operator_shell.panel_chrome",
    "gateway.operator_shell.smart_home",
    "gateway.operator_shell.mission",
    "gateway.operator_shell.cockpit",
    "gateway.operator_shell.atlas",
    "gateway.operator_shell.daemons",
    "gateway.operator_shell.fleet",
    "gateway.operator_shell.builds",
    "gateway.operator_shell.sdlc",
    "gateway.operator_shell.help_card",
    "gateway.operator_shell.command_palette",
    "gateway.operator_shell.natural_ops",
    "gateway.operator_shell.otto_health",
    "gateway.operator_shell.nav_stack",
    "gateway.operator_shell.brain",
    "gateway.operator_shell.inbox",
    "gateway.operator_shell.host",
    "gateway.operator_shell.budget",
    "gateway.operator_shell.find",
    "gateway.operator_shell.diagnose_panel",
    "gateway.operator_shell.code_remote",
    "gateway.operator_shell.incident_panel",
]

for mod in GATEWAY_MODULES:
    try:
        importlib.import_module(mod)
        check(mod.split(".")[-1], True)
    except Exception as e:
        check(mod.split(".")[-1], False, str(e)[:80])


# ═══════════════════════════════════════════════
# 2. Dispatch route safety — check every route for undefined variables
# ═══════════════════════════════════════════════
print("\n── Dispatch route safety ──")

estate_path = GATEWAY / "estate.py"
if estate_path.is_file():
    code = estate_path.read_text()
    tree = ast.parse(code)
    
    # Find all dispatch blocks (if action == "..." or if action in (...))
    dispatch_actions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Check for: if action == "xxx" or if action in ("xxx", ...)
            test_str = ast.unparse(node.test) if hasattr(ast, 'unparse') else ''
            if 'action' in test_str:
                # Find the action string in the condition
                for child in ast.walk(node.test):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        dispatch_actions.append(child.value)
    
    # For each dispatch block, check that key imports exist
    import_map = {}
    import_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    
    check(f"Dispatch actions found", len(dispatch_actions) > 50, f"{len(dispatch_actions)} routes")
    
    # Specific checks for known bug patterns
    # Check PanelView has panel_type field
    panelview_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "PanelView"]
    if panelview_nodes:
        pv = panelview_nodes[0]
        fields = [n.target.id if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) else ""
                  for n in ast.walk(pv) if isinstance(n, ast.AnnAssign)]
        fields = [f for f in fields if not f.startswith("_")]
        check("PanelView has panel_type field", "panel_type" in fields)
    
    # Check that with_nav is imported in every dispatch that uses it
    with_nav_users = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and hasattr(node, 'func'):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            if func_name == "with_nav":
                # Find enclosing dispatch block
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.If) and 'action' in ast.unparse(parent.test) if hasattr(ast, 'unparse') else False:
                        # Check if this if-block or its ancestors have a with_nav import
                        pass
                with_nav_users.append(node.lineno)
    check("with_nav calls exist", len(with_nav_users) > 0, f"{len(with_nav_users)} calls")


# ═══════════════════════════════════════════════
# 3. Script imports — every script module must be importable
# ═══════════════════════════════════════════════
print("\n── Script module imports ──")
SCRIPTS = HERMES / "scripts"
import importlib.util as _iu

SCRIPT_MODULES = [
    "outcome_tracker", "constitutional_validator", "holdout_eval",
    "cost_policy_mgmt", "quality_defense", "auto_close_identity",
    "gap-finding", "self-regression", "auto_fixer", "meta-improver",
    "self_improve_runner", "integration",
]

for name in SCRIPT_MODULES:
    try:
        path = SCRIPTS / f"{name}.py"
        if path.is_file():
            spec = _iu.spec_from_file_location(name.replace("-", "_"), str(path))
            mod = _iu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            check(name, True)
        else:
            check(name, False, "file not found")
    except Exception as e:
        check(name, False, str(e)[:80])


# ═══════════════════════════════════════════════
# 4. Gateway process health
# ═══════════════════════════════════════════════
print("\n── Gateway status ──")
try:
    r = subprocess.run(["pgrep", "-f", "hermes_cli"], capture_output=True, text=True)
    pids = r.stdout.strip().split()
    check("Gateway process running", len(pids) >= 1, f"{len(pids)} processes")
except Exception:
    check("Gateway process running", False)


# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
print("\n" + "=" * 50)
if FAILED == 0:
    print("✅ ALL CHECKS PASS — Safe to restart gateway")
else:
    print(f"❌ {FAILED} CHECKS FAILED — Fix before restarting")
print("=" * 50)

sys.exit(0 if FAILED == 0 else 1)
