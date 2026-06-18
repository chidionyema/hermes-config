#!/usr/bin/env bash
# Estate Full Report — runs the entire estate pipeline:
#   1. Inventory snapshot
#   2. Drift detection (compares to last snapshot)
#   3. Optimization analysis (reads pipeline outputs)
#   4. Auto-remediation (dry-run only — preview, don't execute)
# Output: both files written; combined report printed to stdout for cron

set -e
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "=== Estate Pipeline Run: $(date -u) ==="
echo ""

# Step 1: Inventory
echo "── Step 1: Estate Inventory ──"
python3 "$HERMES_HOME/scripts/estate-inventory.py" 2>/dev/null
echo "(inventory written to reports/estate-inventory.md)"
echo ""

# Step 2: Drift detection
echo "── Step 2: Drift Detection ──"
python3 "$HERMES_HOME/scripts/estate-drift-detector.py" 2>&1
echo ""

# Step 3: Optimization scan
echo "── Step 3: Optimization Scan ──"
python3 "$HERMES_HOME/scripts/estate-optimization-scanner.py" 2>&1
echo ""

# Step 4: Auto-remediation (dry-run only — show what would happen)
echo "── Step 4: Auto-Remediation Preview ──"
python3 "$HERMES_HOME/scripts/estate-auto-remediation.py" --dry-run 2>&1
echo ""

echo "=== Estate Pipeline Complete ==="
echo ""
echo "Reports written:"
echo "  - $HERMES_HOME/reports/estate-inventory.md"
echo "  - $HERMES_HOME/reports/estate-drift.md (only if drift detected)"
echo "  - $HERMES_HOME/reports/estate-optimization.md"
echo "  - $HERMES_HOME/logs/remediation/actions.jsonl"
