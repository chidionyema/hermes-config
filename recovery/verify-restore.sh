#!/bin/bash
# verify-restore.sh — PROVE a restored estate is sound. Exits non-zero on any failure.
#   Usage: verify-restore.sh [TARGET_DIR]   (default ~/.hermes)
# Checks the things that actually matter for the estate to come back to life:
# repos present, coordinator.db opens with its tables, critical code compiles, the agent
# imports, hooks installed, launchd plists lint.
set -uo pipefail
T="${1:-$HOME/.hermes}"
SUB="$T/hermes-agent"
fails=0
ok(){   printf '  \033[1;32mPASS\033[0m %s\n' "$*"; }
bad(){  printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; fails=$((fails+1)); }
sys_py(){ command -v python3.14 || command -v python3; }

echo "== Verifying restored estate at: $T"

# 1. repos present
[ -d "$T/.git" ]   && ok "config repo present"           || bad "config repo missing"
[ -d "$SUB" ]      && ok "agent code present"             || bad "agent code missing"

# 2. coordinator.db opens + has the expected tables
DB="$T/coordinator.db"
if [ -f "$DB" ]; then
  tbls=$("$(sys_py)" - "$DB" <<'PY' 2>/dev/null
import sqlite3,sys
c=sqlite3.connect(sys.argv[1]);
print(",".join(sorted(r[0] for r in c.execute("select name from sqlite_master where type='table'"))))
PY
)
  echo "    tables: ${tbls:-<none>}"
  miss=""; for need in tasks events missions milestones meta telemetry; do
    case ",$tbls," in *",$need,"*) :;; *) miss="$miss $need";; esac; done
  [ -z "$miss" ] && ok "coordinator.db has all core tables" || bad "coordinator.db missing tables:$miss"
else
  bad "coordinator.db missing (estate state not restored)"
fi

# 3. critical code compiles (system python is fine for a syntax check)
for f in "$SUB/gateway/platforms/telegram.py" "$T/scripts/coordinator.py"; do
  if [ -f "$f" ]; then
    "$(sys_py)" -c "import py_compile,sys; py_compile.compile(sys.argv[1],doraise=True)" "$f" 2>/dev/null \
      && ok "compiles: ${f#$T/}" || bad "does NOT compile: ${f#$T/}"
  else bad "missing file: ${f#$T/}"; fi
done

# 4. agent actually imports from the restored venv (the real proof it can run)
if [ -x "$SUB/venv/bin/python" ]; then
  ( cd "$SUB" && ./venv/bin/python -c "import gateway.platforms.telegram" ) 2>/dev/null \
    && ok "agent imports from restored venv (gateway.platforms.telegram)" \
    || bad "agent FAILS to import from restored venv"
else
  printf '  \033[1;33mSKIP\033[0m venv not built (run restore without --skip-venv to prove import)\n'
fi

# 5. hooks installed + executable
for repo in "$T" "$SUB"; do
  h="$repo/.git/hooks/pre-commit"
  [ -x "$h" ] && ok "pre-commit hook installed: ${repo#$HOME/}" || bad "pre-commit hook missing/!exec: ${repo#$HOME/}"
done

# 6. launchd plists present + valid
for plist in "$T"/recovery/launchd/*.plist; do
  [ -f "$plist" ] || { bad "no launchd plists"; break; }
  plutil -lint "$plist" >/dev/null 2>&1 && ok "plist valid: $(basename "$plist")" || bad "plist invalid: $(basename "$plist")"
done

# 7. frozen deps present
fr="$T/recovery/requirements-frozen.txt"
[ -s "$fr" ] && ok "frozen deps present ($(wc -l < "$fr" | tr -d ' ') pkgs)" || bad "frozen deps lockfile missing/empty"

echo ""
if [ "$fails" -eq 0 ]; then printf '\033[1;32m== ALL CHECKS PASSED — estate is provably recoverable.\033[0m\n'; exit 0
else printf '\033[1;31m== %d CHECK(S) FAILED.\033[0m\n' "$fails"; exit 1; fi
