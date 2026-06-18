#!/bin/bash
# methodology-probe.sh — Watches for POPDD/PDD compliance drift.
# Runs every 15m via cron. Silent when healthy. Files findings when:
#   1. POPDD infrastructure missing (no ~/.lux/receipts/ or no key)
#   2. No receipt in last 24h while agent is active (drift)
#   3. A chain's hash chain is broken (TAMPERED) — high severity
#   4. A chain's signatures don't match current key (orphaned: signed with old key)
#   5. Active session with 0 receipts in last 30 min (per-session drift)
set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LUX_ROOT="$HOME/.lux"
RECEIPTS_DIR="$LUX_ROOT/receipts"
KEY_FILE="$LUX_ROOT/keys/agent.pem"
PROBE_LOG="$HERMES_HOME/logs/maintenance/methodology-findings.jsonl"
mkdir -p "$(dirname "$PROBE_LOG")"

FOUND=0
log_finding() {
  local severity="$1" domain="$2" trigger="$3" fix="$4"
  echo "  ⚠️  $trigger"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"source\":\"methodology-probe\",\"domain\":\"$domain\",\"trigger\":\"$trigger\",\"fix\":\"$fix\",\"severity\":\"$severity\",\"added_at\":\"$ts\"}" >> "$PROBE_LOG"
  FOUND=$((FOUND+1))
}

# --- 1. Infrastructure presence ---
[ -d "$RECEIPTS_DIR" ] || log_finding P2 pdd/infra "POPDD receipts dir missing" "mkdir -p ~/.lux/receipts && run popdd-init.sh"
[ -f "$KEY_FILE" ]     || log_finding P2 pdd/infra "POPDD HMAC key missing" "run popdd-init.sh (auto-generates key)"

# --- 2. Receipt activity in last 24h ---
if [ -d "$RECEIPTS_DIR" ]; then
  RECENT=$(find "$RECEIPTS_DIR" -name "*.jsonl" -type f -mtime -1 2>/dev/null | head -5)
  if [ -z "$RECENT" ]; then
    ACTIVE_GATEWAY=$(ps aux | grep "python.*gateway" | grep -v grep | wc -l | tr -d ' ')
    [ "$ACTIVE_GATEWAY" -gt 0 ] && log_finding P1 pdd/compliance "Gateway active but 0 POPDD receipts in 24h" "Run popdd-init.sh and sign every action via PopddAgent"
  fi
fi

# --- 3 + 4. Chain integrity (hash chain + signature) ---
if [ -d "$RECEIPTS_DIR" ] && [ -f "$KEY_FILE" ]; then
  PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$RECEIPTS_DIR" "$KEY_FILE" "$PROBE_LOG" 2>&1 <<'PY' || true
import sys, json
from pathlib import Path
from datetime import datetime, timezone
from popdd import HmacSigner, load_chain_from_jsonl, GENESIS_HASH, hash_receipt

receipts_dir, key_file, probe_log = sys.argv[1], sys.argv[2], sys.argv[3]
key = bytes.fromhex(Path(key_file).read_text().strip())
signer = HmacSigner(key)

def log(severity, domain, trigger, fix, chain=""):
    finding = {
        "source": "methodology-probe",
        "domain": domain,
        "trigger": trigger,
        "fix": fix,
        "severity": severity,
        "chain": chain,
        "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with open(probe_log, "a") as f:
        f.write(json.dumps(finding) + "\n")
    print(f"  ⚠️  {trigger}")

for chain_path in sorted(Path(receipts_dir).glob("*.jsonl")):
    try:
        receipts = load_chain_from_jsonl(chain_path)
    except Exception as e:
        log("P2", "pdd/integrity", f"Chain load error: {chain_path.name} — {e}",
            "Check disk / file format", str(chain_path))
        continue
    if not receipts:
        continue

    # --- HASH CHAIN check (does NOT require the key) ---
    chain_broken_at = None
    for i, r in enumerate(receipts):
        expected_prev = GENESIS_HASH if i == 0 else receipts[i - 1].content_hash
        if r.previous_hash != expected_prev:
            chain_broken_at = (i, "previous_hash mismatch")
            break
        partial = {
            "sequence": r.sequence, "timestamp": r.timestamp,
            "agent_id": r.agent_id, "action": r.action,
            "target": r.target, "proof": dict(r.proof),
            "previous_hash": r.previous_hash,
        }
        if hash_receipt(partial) != r.content_hash:
            chain_broken_at = (i, "content_hash mismatch")
            break
    if chain_broken_at is not None:
        i, reason = chain_broken_at
        log("P0", "pdd/tamper",
            f"Chain TAMPERED: {chain_path.name} broken at #{i} ({reason})",
            "DO NOT trust receipts. Investigate key compromise, restore from backup.",
            str(chain_path))
        continue  # don't double-report as orphan

    # --- SIGNATURE check (requires the current key) ---
    sig_failures = sum(1 for r in receipts if signer.sign(r.content_hash) != r.signature)
    if sig_failures == len(receipts):
        # All sigs wrong → chain was signed with a different key (orphaned)
        print(f"  ℹ️  {chain_path.name}: orphaned (signed with different key, {len(receipts)} receipts) — keeping for archive")
    elif sig_failures > 0:
        log("P0", "pdd/tamper",
            f"Chain {chain_path.name}: {sig_failures}/{len(receipts)} signatures INVALID under current key",
            "Partial key mismatch — investigate. This is anomalous.", str(chain_path))
    else:
        # All sigs valid
        pass  # healthy
PY
fi

# --- 5. Per-session drift ---
RECENT_RECEIPT_AGE_M=30
if [ -d "$RECEIPTS_DIR" ] && [ -f "$KEY_FILE" ]; then
  LATEST=$(find "$RECEIPTS_DIR" -name "*.jsonl" -type f -mmin -$RECENT_RECEIPT_AGE_M 2>/dev/null | head -1)
  if [ -z "$LATEST" ]; then
    GATEWAY_RUNNING=$(ps aux | grep "python.*gateway" | grep -v grep | wc -l | tr -d ' ')
    LAST_SESSION=$(find ~/.hermes/sessions -type f -mmin -$RECENT_RECEIPT_AGE_M 2>/dev/null | head -1)
    if [ "$GATEWAY_RUNNING" -gt 0 ] && [ -n "$LAST_SESSION" ]; then
      log_finding P2 pdd/compliance \
        "Active Hermes session but no POPDD receipt in last ${RECENT_RECEIPT_AGE_M} min" \
        "Append a session-action receipt via popdd-init.sh <project> action"
    fi
  fi
fi

[ "$FOUND" -gt 0 ] && echo "--- methodology-probe complete: $FOUND findings ---"

# Resolution pass
[ -f "$HERMES_HOME/scripts/alert-resolver.py" ] && \
  python3 "$HERMES_HOME/scripts/alert-resolver.py" --check "[]" --verbose 2>&1 || true
