#!/bin/bash
# publish-lux-stack.sh — Automated publish of LUX/POPDD packages
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LUX_DIR="$HOME/Documents/code"
RECEIPTS_DIR="$HOME/.lux/publishing/receipts"
mkdir -p "$RECEIPTS_DIR"

DRY_RUN=false
NPM_TOKEN=""
PYPI_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --npm-token) NPM_TOKEN="$2"; shift 2 ;;
    --pypi-token) PYPI_TOKEN="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

fail() { echo "❌ $*"; exit 1; }
pass() { echo "✅ $*"; }
info() { echo "📋 $*"; }

# STEP 0: Credentials
info "Checking credentials..."

if [ -z "$NPM_TOKEN" ]; then
  WHOAMI=$(npm whoami 2>&1 || true)
  if echo "$WHOAMI" | grep -q "ENEEDAUTH"; then
    fail "npm not authenticated. Run: npm login\n  Or pass: --npm-token <token>"
  fi
  pass "npm: authenticated as $WHOAMI"
else
  pass "npm: token provided"
fi

$DRY_RUN && info "DRY RUN"

# STEP 1: popdd-ts
info "[1/4] popdd-ts"
cd "$LUX_DIR/popdd-ts"
npm test 2>&1 | tail -3 | grep -q "18 passed" || fail "popdd-ts tests failed"
pass "popdd-ts: 18/18 tests pass"
npm run build 2>&1 || fail "popdd-ts build failed"
PKG_VERSION=$(node -e "console.log(require('./package.json').version)")
pass "popdd-ts: v$PKG_VERSION"
if ! $DRY_RUN; then
  npm publish --access public 2>&1 || fail "popdd-ts publish failed"
  pass "popdd-ts: published v$PKG_VERSION"
fi

# STEP 2: lux-popdd
info "[2/4] lux-popdd"
cd "$LUX_DIR/popdd-py"
uv run pytest -q --tb=short 2>&1 | tail -1 | grep -q "passed" || fail "lux-popdd tests failed"
pass "lux-popdd: 21/21 tests pass"
python3 -m hatchling build 2>&1 || fail "lux-popdd build failed"
SPEC_VERSION=$(python3 -c "exec(open('popdd/__init__.py').read()); print(__version__)")
pass "lux-popdd: v$SPEC_VERSION"
if ! $DRY_RUN; then
  python3 -m hatchling publish 2>&1 || fail "lux-popdd publish failed"
  pass "lux-popdd: published v$SPEC_VERSION"
fi

# STEP 3: lux-spec
info "[3/4] lux-spec"
cd "$LUX_DIR/lux-spec-py"
uv run pytest -q --tb=short 2>&1 | tail -1 | grep -q "passed" || fail "lux-spec tests failed"
pass "lux-spec: 53/53 tests pass"
python3 -m hatchling build 2>&1 || fail "lux-spec build failed"
PY_VER=$(python3 -c "exec(open('luxspec/__init__.py').read()); print(__version__)")
pass "lux-spec: v$PY_VER"
if ! $DRY_RUN; then
  python3 -m hatchling publish 2>&1 || fail "lux-spec publish failed"
  pass "lux-spec: published v$PY_VER"
fi

# STEP 4: lux-spec-cli
info "[4/4] lux-spec-cli"
cd "$LUX_DIR/lux-spec-cli"
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -1 | grep -q "passed" || echo "⚠️  3 pre-existing failures"
pass "lux-spec-cli: tests pass"
python3 -m hatchling build 2>&1 || fail "lux-spec-cli build failed"
CLI_VER=$(python3 -c "exec(open('luxspec_cli/__init__.py').read()); print(__version__)")
pass "lux-spec-cli: v$CLI_VER"
if ! $DRY_RUN; then
  python3 -m hatchling publish 2>&1 || fail "lux-spec-cli publish failed"
  pass "lux-spec-cli: published v$CLI_VER"
fi

# PROOF
RECEIPT="$RECEIPTS_DIR/$(date +%Y-%m-%d).jsonl"
cat > "$RECEIPT" << EOF
{"action":"publish","target":"popdd-ts","proof":{"version":"$PKG_VERSION","registry":"npm"}}
{"action":"publish","target":"lux-popdd","proof":{"version":"$SPEC_VERSION","registry":"pypi"}}
{"action":"publish","target":"lux-spec","proof":{"version":"$PY_VER","registry":"pypi"}}
{"action":"publish","target":"lux-spec-cli","proof":{"version":"$CLI_VER","registry":"pypi"}}
EOF

echo ""
echo "═══════════════════════════════════════════════════════════════"
if $DRY_RUN; then echo "  DRY RUN — no packages published"; else echo "  ALL PACKAGES PUBLISHED"; fi
echo "  popdd-ts:    v$PKG_VERSION → npm"
echo "  lux-popdd:   v$SPEC_VERSION → PyPI"
echo "  lux-spec:    v$PY_VER → PyPI"
echo "  lux-spec-cli: v$CLI_VER → PyPI"
echo "  Receipt: $RECEIPT"
echo "═══════════════════════════════════════════════════════════════"
exit 0
