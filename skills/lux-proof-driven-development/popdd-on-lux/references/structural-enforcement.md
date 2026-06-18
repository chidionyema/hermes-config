# POPDD Structural Enforcement — the "How do we ensure you don't forget again" pattern

When POPDD methodology is repeatedly skipped despite the skill being loaded, the fix is not more rules. The fix is **structural enforcement**: tools that detect the violation without the agent having to remember.

## The three layers

```
┌────────────────────────────────────────────────────────────────────┐
│ Layer 1: SESSION-START RITUAL                                      │
│   ~/.hermes/scripts/popdd-init.sh <project> [start|resume|action]  │
│   Idempotent — appends a session-<phase> receipt to today's chain  │
│   Failure here = P0, agent stops, no work proceeds                 │
└────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────┐
│ Layer 2: METHODOLOGY PROBE (every 15m via cron)                    │
│   ~/.hermes/scripts/methodology-probe.sh                            │
│   Files findings to ~/.hermes/logs/maintenance/methodology-...     │
│   Pairs with improvement-probe.sh (infra) and health-watchdog       │
└────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────┐
│ Layer 3: RECEIPT-OR-SILENCE REPORT GATE                            │
│   A claim of completion without a receipt is a ball drop.         │
│   Show the chain excerpt before any "POPDD is working" report.     │
│   Use the post-claim verifier to check claimed files exist.         │
└────────────────────────────────────────────────────────────────────┘
```

## Layer 1 — session-start init (`popdd-init.sh`)

```bash
#!/bin/bash
# popdd-init.sh — Initialize/append a POPDD session receipt to today's chain.
# Idempotent: appends session-resume if chain exists, session-start if not.
# Usage: ./popdd-init.sh [project-name] [phase]
#   project-name: hermes, signalengine, lux, prospector (default: hermes)
#   phase: start | resume | action | complete (default: auto)
set -e
PROJECT="${1:-hermes}"
PHASE="${2:-auto}"
LUX_ROOT="$HOME/.lux"
mkdir -p "$LUX_ROOT/keys" "$LUX_ROOT/receipts/$PROJECT"
PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$PROJECT" "$PHASE" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Documents" / "code" / "popdd-py"))
from popdd.agent import PopddAgent

project, phase = sys.argv[1], sys.argv[2]
# Per-project subdir + correct key_dir / receipt_dir
# (Passing ".lux/keys" with root "~/.lux" gives "~/.lux/.lux/keys".)
agent = PopddAgent(
    Path.home() / ".lux",
    agent_id=f"hermes-{project}",
    key_dir="keys",
    receipt_dir=f"receipts/{project}",
)
if phase == "auto":
    phase = "resume" if len(agent._receipts) > 0 else "start"
agent.sign_generic(
    f"session-{phase}", f"hermes-session-{project}",
    verdict="INITIALIZED", project=project, phase=phase,
    host=os.uname().nodename, pid=os.getpid(),
)
chain_file = agent._receipt_dir / f"{agent._receipts[-1].timestamp[:10]}.jsonl"
result = agent.verify_chain()
print(f"{chain_file}  {result['total']}  {result['valid']}")
PY
```

**Three bugs the production init hits (every time, no exceptions):**

1. `PopddAgent.at_path()` does NOT accept `agent_id` kwarg. Use `PopddAgent(root, agent_id=...)` directly.
2. `PopddAgent.__init__` appends `key_dir` and `receipt_dir` to `project_root`. If `project_root` is already `~/.lux`, the default `.lux/keys` gives `~/.lux/.lux/keys`. Pass `key_dir="keys"` and `receipt_dir="receipts/<project>"` instead.
3. `PopddAgent.__init__` auto-loads ALL `*.jsonl` files in `receipt_dir`. If a chain from a different key is in there (e.g., an old test chain), the signature check fails for the entire chain. Per-project subdirectory (`receipts/<project>/<date>.jsonl`) isolates chains by signer.

## Layer 2 — methodology probe (`methodology-probe.sh`)

```bash
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
  local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"source\":\"methodology-probe\",\"domain\":\"$domain\",\"trigger\":\"$trigger\",\"fix\":\"$fix\",\"severity\":\"$severity\",\"added_at\":\"$ts\"}" >> "$PROBE_LOG"
  FOUND=$((FOUND+1))
}
[ -d "$RECEIPTS_DIR" ] || log_finding P2 pdd/infra "POPDD receipts dir missing" "mkdir -p ~/.lux/receipts && run popdd-init.sh"
[ -f "$KEY_FILE" ]     || log_finding P2 pdd/infra "POPDD HMAC key missing" "run popdd-init.sh (auto-generates key)"
if [ -d "$RECEIPTS_DIR" ]; then
  RECENT=$(find "$RECEIPTS_DIR" -name "*.jsonl" -type f -mtime -1 2>/dev/null | head -5)
  if [ -z "$RECENT" ]; then
    ACTIVE_GATEWAY=$(ps aux | grep "python.*gateway" | grep -v grep | wc -l | tr -d ' ')
    [ "$ACTIVE_GATEWAY" -gt 0 ] && log_finding P1 pdd/compliance "Gateway active but 0 POPDD receipts in 24h" "Run popdd-init.sh and sign every action"
  fi
fi
if [ -d "$RECEIPTS_DIR" ] && [ -f "$KEY_FILE" ]; then
  PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$RECEIPTS_DIR" "$KEY_FILE" "$PROBE_LOG" <<'PY'
import sys, json
from pathlib import Path
from datetime import datetime, timezone
from popdd import HmacSigner, load_chain_from_jsonl, GENESIS_HASH, hash_receipt

receipts_dir, key_file, probe_log = sys.argv[1], sys.argv[2], sys.argv[3]
key = bytes.fromhex(Path(key_file).read_text().strip())
signer = HmacSigner(key)

def log(severity, domain, trigger, fix, chain=""):
    finding = {
        "source": "methodology-probe", "domain": domain, "trigger": trigger,
        "fix": fix, "severity": severity, "chain": chain,
        "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with open(probe_log, "a") as f:
        f.write(json.dumps(finding) + "\n")
    print(f"  ⚠️  {trigger}")

for chain_path in sorted(Path(receipts_dir).glob("**/*.jsonl")):
    try:
        receipts = load_chain_from_jsonl(chain_path)
    except Exception as e:
        log("P2", "pdd/integrity", f"Chain load error: {chain_path.name} — {e}",
            "Check disk / file format", str(chain_path))
        continue
    if not receipts:
        continue
    # Hash chain check (does NOT require the key)
    chain_broken_at = None
    for i, r in enumerate(receipts):
        expected_prev = GENESIS_HASH if i == 0 else receipts[i - 1].content_hash
        if r.previous_hash != expected_prev:
            chain_broken_at = (i, "previous_hash mismatch"); break
        partial = {
            "sequence": r.sequence, "timestamp": r.timestamp,
            "agent_id": r.agent_id, "action": r.action,
            "target": r.target, "proof": dict(r.proof),
            "previous_hash": r.previous_hash,
        }
        if hash_receipt(partial) != r.content_hash:
            chain_broken_at = (i, "content_hash mismatch"); break
    if chain_broken_at is not None:
        i, reason = chain_broken_at
        log("P0", "pdd/tamper",
            f"Chain TAMPERED: {chain_path.name} broken at #{i} ({reason})",
            "DO NOT trust receipts. Investigate key compromise.",
            str(chain_path))
        continue
    # Signature check
    sig_failures = sum(1 for r in receipts if signer.sign(r.content_hash) != r.signature)
    if sig_failures == len(receipts):
        print(f"  ℹ️  {chain_path.name}: orphaned (different key, {len(receipts)} receipts) — archive, not delete")
    elif sig_failures > 0:
        log("P0", "pdd/tamper",
            f"Chain {chain_path.name}: {sig_failures}/{len(receipts)} signatures INVALID under current key",
            "Partial key mismatch — investigate.", str(chain_path))
PY
fi
# Per-session drift
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
[ -f "$HERMES_HOME/scripts/alert-resolver.py" ] && \
  python3 "$HERMES_HOME/scripts/alert-resolver.py" --check "[]" --verbose 2>&1 || true
```

## Layer 3 — receipt-or-silence report gate

Before any "I fixed X" or "POPDD is working" report:

```bash
# 1. Show the chain
cat ~/.lux/receipts/<project>/$(date -u +%Y-%m-%d).jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    if line.strip():
        r = json.loads(line)
        print(f'  #{r[\"sequence\"]} {r[\"timestamp\"][11:19]} {r[\"action\"]:<20} {r[\"target\"]:<30} hash={r[\"content_hash\"][:12]} sig={r[\"signature\"][:12]}')
"
# 2. Verify the chain
PYTHONPATH=$HOME/Documents/code/popdd-py python3 -c "
from pathlib import Path
from popdd import HmacSigner, load_chain_from_jsonl
key = bytes.fromhex(Path.home().joinpath('.lux','keys','agent.pem').read_text().strip())
chain = load_chain_from_jsonl(Path.home() / '.lux' / 'receipts' / '<project>' / '$(date -u +%Y-%m-%d).jsonl')
signer = HmacSigner(key)
sig_fails = sum(1 for r in chain if signer.sign(r.content_hash) != r.signature)
print(f'  Chain: {len(chain)} receipts, {sig_fails} signature failures')
"
# 3. Verify any file claims
python3 ~/.hermes/scripts/post-claim-verifier.py
```

## Registering in cron

`methodology-probe.sh` belongs in cron at every 15m, no-agent, paired with `improvement-probe.sh`:

```bash
hermes cron create \
  --name methodology-probe \
  --schedule "every 15m" \
  --script methodology-probe.sh \
  --no-agent \
  --deliver origin
```

## Why this works (and behavioral rules don't)

Behavioral rules ("remember to sign") are remembered by the LLM, which is unreliable. Structural rules (a probe that fires every 15 min) are remembered by the *scheduler*, which is reliable. The agent can still skip POPDD — but the probe catches the drift within 15 minutes and files a finding. The user gets a notification through the existing watchdog pipeline.

**The honest limit:** Even with three layers, the agent can still produce a 5-minute response that signs nothing. The probe catches it 15 minutes later. The receipt-or-silence gate catches it at the report. The only thing that doesn't catch it is silence — but that's a problem the user can see directly.

## Anti-patterns to avoid

- **Don't sign "0 passed, 0 failed"** — better no receipt than a wrong one.
- **Don't auto-load all `*.jsonl` from a shared receipts dir** — per-project subdir keeps mixed-key chains isolated.
- **Don't treat orphaned chains as tamper** — they're informational. Archive, don't flag.
- **Don't skip the probe because "we just verified"** — the probe catches drift in the *future*. Manual verification only catches drift at the moment of check.
- **Don't conflate "I ran popdd-init.sh" with "POPDD is working"** — the init script can succeed but the chain can still be invalid. Verify with `chain.verify()`.
