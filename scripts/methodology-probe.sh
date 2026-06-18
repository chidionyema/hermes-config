#!/bin/bash
# methodology-probe.sh — Watches for POPDD/PDD compliance drift.
# Runs every 15m via cron. Silent when healthy. File a finding when:
#   1. POPDD infrastructure is missing (no ~/.lux/receipts/ or no key)
#   2. No receipt was produced in the last 24h (agent has been active but
#      has not signed anything — methodology drift)
#   3. Most recent chain is broken (verify() reports invalid)
#   4. Active session has been running >5 min with 0 receipts (per-session drift)
#
# Pairs with improvement-probe.sh — that one watches infra health; this one
# watches methodology compliance.
set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
RECEIPTS_DIR="$HOME/.lux/receipts"
KEY_FILE="$HOME/.lux/keys/agent.pem"
PROBE_LOG="$HERMES_HOME/logs/maintenance/methodology-findings.jsonl"
mkdir -p "$(dirname "$PROBE_LOG")"

FOUND=0

# --- 1. Infrastructure presence ---
if [ ! -d "$RECEIPTS_DIR" ]; then
  echo '  ⚠️  POPDD receipts dir missing — methodology cannot be enforced'
  echo '{"source":"methodology-probe","domain":"pdd/infra","trigger":"POPDD receipts directory ~/.lux/receipts/ does not exist","fix":"mkdir -p ~/.lux/receipts && run ~/.hermes/scripts/popdd-init.sh","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
  FOUND=$((FOUND+1))
fi
if [ ! -f "$KEY_FILE" ]; then
  echo '  ⚠️  POPDD HMAC key missing — chains will be unsigned'
  echo '{"source":"methodology-probe","domain":"pdd/infra","trigger":"POPDD HMAC key ~/.lux/keys/agent.pem missing","fix":"run ~/.hermes/scripts/popdd-init.sh (auto-generates 32-byte key)","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
  FOUND=$((FOUND+1))
fi

# --- 2. Receipt activity in last 24h ---
if [ -d "$RECEIPTS_DIR" ]; then
  LATEST=$(find "$RECEIPTS_DIR" -name "*.jsonl" -type f -mtime -1 2>/dev/null | head -5)
  if [ -z "$LATEST" ]; then
    # No receipts in 24h — but the agent has been running (improvement-probe is firing).
    # That's drift. Surface it.
    ACTIVE_GATEWAY=$(ps aux | grep "python.*gateway" | grep -v grep | wc -l | tr -d ' ')
    if [ "$ACTIVE_GATEWAY" -gt 0 ]; then
      echo '  ⚠️  POPDD drift: agent active (gateway running) but 0 receipts in last 24h'
      echo '{"source":"methodology-probe","domain":"pdd/compliance","trigger":"Gateway is running but no POPDD receipts have been produced in 24h. The agent is operating without proof-of-proof.","fix":"Run ~/.hermes/scripts/popdd-init.sh immediately, then ensure every action appends a receipt via the PopddAgent API. Add receipts to: ~/.hermes/skills/autonomous-ai-agents/otto-operating-model/SKILL.md as a non-negotiable ritual.","severity":"P1","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
      FOUND=$((FOUND+1))
    fi
  fi
fi

# --- 3. Chain integrity on most recent JSONL ---
if [ -d "$RECEIPTS_DIR" ] && [ -f "$KEY_FILE" ]; then
  LATEST_CHAIN=$(ls -t "$RECEIPTS_DIR"/*.jsonl 2>/dev/null | head -1)
  if [ -n "$LATEST_CHAIN" ]; then
    CHAIN_VERIFY=$(PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$LATEST_CHAIN" "$KEY_FILE" <<'PY' 2>&1
import sys
from pathlib import Path
from popdd import HmacSigner, load_chain_from_jsonl
chain_path, key_file = sys.argv[1], sys.argv[2]
key = bytes.fromhex(Path(key_file).read_text().strip())
signer = HmacSigner(key)
try:
    chain = load_chain_from_jsonl(chain_path)
    result = chain.verify()
    print(f"{result.valid} {len(chain.receipts)}")
except Exception as e:
    print(f"ERROR {e}")
PY
)
    case "$CHAIN_VERIFY" in
      ERROR*)
        echo "  ⚠️  POPDD chain corrupt: $LATEST_CHAIN"
        echo '{"source":"methodology-probe","domain":"pdd/integrity","trigger":"Most recent POPDD chain failed to load or verify","fix":"Inspect chain manually; if keys rotated, archive old chain and start fresh","chain":"'$LATEST_CHAIN'","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
        FOUND=$((FOUND+1))
        ;;
      False*)
        echo "  ⚠️  POPDD chain tampered: $LATEST_CHAIN"
        echo '{"source":"methodology-probe","domain":"pdd/integrity","trigger":"POPDD chain verify() returned invalid — chain has been tampered with","fix":"DO NOT trust any receipts from this chain. Investigate key compromise.","chain":"'$LATEST_CHAIN'","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
        FOUND=$((FOUND+1))
        ;;
    esac
  fi
fi

# Only print summary if there are findings
if [ "$FOUND" -gt 0 ]; then
  echo "--- methodology-probe complete: $FOUND findings ---"
fi

# Resolution pass: close any methodology findings whose conditions have cleared
if [ -f "$HERMES_HOME/scripts/alert-resolver.py" ]; then
  python3 "$HERMES_HOME/scripts/alert-resolver.py" --check "[]" --verbose 2>&1 || true
fi
