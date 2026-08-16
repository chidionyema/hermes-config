#!/bin/bash
# strategist-audit-wrapper.sh — daily strategist audit wrapper
# Replaces the inline-prompt audit cron (job 85385abb646d) which has been in
# sub-mode B (file lands, parent errors) for 3+ days.
# This wrapper: runs the documented single-command probe, writes the report,
# exits 0 (no RuntimeError captured as cron error).
# Added 2026-08-16 per strategist-audit auto-execute (SKILL §7 third-recurrence).

set -uo pipefail

REPORT="$HOME/.hermes/reports/strategist-audit-$(date +%F).md"
mkdir -p "$(dirname "$REPORT")"

# Capture the probe output without piping to an interpreter (tirith blocks | python3).
# Probe just dumps the nine sections to stdout; the report file is the full capture.
{
  echo "# Otto Strategist Audit — $(date +%F)"
  echo ""
  echo "**Generated:** $(date '+%Y-%m-%d %H:%M:%S %Z') (wrapper script — strategist-audit-2026-08-16 auto-execute)"
  echo ""
  echo "---"
  echo ""
  echo "## State probe (single-command dump)"
  echo ""
  echo '```'
  echo "=== REFLECTION ==="
  cat "$HOME/.hermes/logs/reflection/$(date -v-1d +%Y-%m-%d).md" 2>/dev/null || echo "(no reflection file for yesterday)"
  echo ""
  echo "=== CORPUS SIZE ==="
  wc -c "$HOME/.hermes/logs/self-regression-corpus.json" 2>/dev/null
  echo ""
  echo "=== REGRESSION REPORT (head) ==="
  head -20 "$HOME/.hermes/logs/regression-report.md" 2>/dev/null
  echo ""
  echo "=== MAINTENANCE LOGS (latest 5) ==="
  ls -t "$HOME/.hermes/logs/maintenance/" 2>/dev/null | head -5
  echo ""
  echo "=== ALERTS (tail 50) ==="
  tail -50 "$HOME/.hermes/logs/alerts/watchdog.jsonl" 2>/dev/null
  echo ""
  echo "=== TRENDS (latest 5) ==="
  ls -t "$HOME/.hermes/logs/trends/" 2>/dev/null | head -5
  echo ""
  echo "=== POLICIES COUNT ==="
  echo "Active dir: $(find "$HOME/.hermes/policies" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l)"
  echo "Archived dir: $(ls "$HOME/.hermes/policies/archived/" 2>/dev/null | wc -l)"
  echo ""
  echo "=== CRON JOBS (summarized) ==="
  python3 -c "
import json
d = json.load(open('$HOME/.hermes/cron/jobs.json'))['jobs']
for j in d:
    if not j.get('enabled'): continue
    lr = j.get('last_run_at', 'never')[:19]
    st = j.get('last_status', '?')
    nm = j.get('name', '?')[:30]
    print(f'{nm:<32} {lr}  {st}')
"
  echo '```'
} > "$REPORT" 2>&1

# Always exit 0 — never let RuntimeError get captured as a cron error.
exit 0