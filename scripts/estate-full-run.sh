#!/usr/bin/env bash
# Estate Full Report — runs the entire estate pipeline:
#   1. Inventory snapshot
#   2. Drift detection (compares to last snapshot)
#   3. Optimization analysis (reads pipeline outputs)
#   4. Auto-remediation (dry-run only — preview, don't execute)
# Output: both files written; combined report printed to stdout for cron

# NO `set -e`: this is a best-effort REPORT aggregator. Under morning load any single
# sub-scan can transiently exit non-zero (or hit the cron cap); with `set -e` that aborted
# the WHOLE pipeline and marked the daily cron errored — which then sticks as a FALSE
# "failure: health-watchdog" for ~24h (the job only re-runs at 06:00). Instead, run every
# step, record per-step failures inline, and exit 0 if the pipeline RAN. The reports are the
# deliverable; a failed sub-step is surfaced in the output, not by wedging the whole audit.
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec 2>&1  # fold sub-step stderr into the cron report (tracebacks stay visible)
FAILED_STEPS=()

run_step() {  # run_step "<label>" <cmd...>; never aborts the pipeline
    local label="$1"; shift
    if ! "$@"; then
        echo "(⚠️  step failed: $label — continuing; see output above)"
        FAILED_STEPS+=("$label")
    fi
}

echo "=== Estate Pipeline Run: $(date -u) ==="
echo ""

# Step 1: Inventory
echo "── Step 1: Estate Inventory ──"
run_step "inventory" python3 "$HERMES_HOME/scripts/estate-inventory.py"
echo "(inventory written to reports/estate-inventory.md)"
echo ""

# Step 2: Drift detection
echo "── Step 2: Drift Detection ──"
run_step "drift" python3 "$HERMES_HOME/scripts/estate-drift-detector.py"
echo ""

# Step 3: Optimization scan
echo "── Step 3: Optimization Scan ──"
run_step "optimization" python3 "$HERMES_HOME/scripts/estate-optimization-scanner.py"
echo ""

# Step 4: Auto-remediation (dry-run only — show what would happen)
echo "── Step 4: Auto-Remediation Preview ──"
run_step "remediation" python3 "$HERMES_HOME/scripts/estate-auto-remediation.py" --dry-run
echo ""

if [ ${#FAILED_STEPS[@]} -gt 0 ]; then
    echo "⚠️  ${#FAILED_STEPS[@]} step(s) failed this run: ${FAILED_STEPS[*]} (pipeline still completed)"
    echo ""
fi

echo "=== Estate Pipeline Complete ==="
echo ""
echo "Reports written:"
echo "  - $HERMES_HOME/reports/estate-inventory.md"
echo "  - $HERMES_HOME/reports/estate-drift.md (only if drift detected)"
echo "  - $HERMES_HOME/reports/estate-optimization.md"
echo "  - $HERMES_HOME/logs/remediation/actions.jsonl"
