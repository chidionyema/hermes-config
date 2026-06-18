#!/bin/bash
# popdd-init.sh — Initialize a POPDD session chain for the current session.
# Run at the START of every new session / response cycle that will perform
# verifiable work. Idempotent: if today's chain exists, it appends a new
# "session-resume" receipt to it. Otherwise it creates a new chain.
#
# Usage:
#   ./popdd-init.sh [project-name]
#
# Output (stdout):
#   {chain_path}  {total_receipts}  {chain_valid}
#
# Receipts go to: ~/.lux/receipts/<project>-<YYYY-MM-DD>.jsonl

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PROJECT="${1:-hermes}"
DATE="$(date -u +%Y-%m-%d)"
RECEIPTS_DIR="$HOME/.lux/receipts"
KEY_DIR="$HOME/.lux/keys"
KEY_FILE="$KEY_DIR/agent.pem"
CHAIN="$RECEIPTS_DIR/${PROJECT}-${DATE}.jsonl"

mkdir -p "$RECEIPTS_DIR" "$KEY_DIR"

# Use the Hermes-level key (shared across all projects' chains) for cross-project
# audit. If a project-specific key exists, prefer it.
if [ ! -f "$KEY_FILE" ]; then
  python3 - <<'PY'
import secrets, pathlib
key = secrets.token_bytes(32)
p = pathlib.Path.home() / ".lux" / "keys" / "agent.pem"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(key.hex())
import os
os.chmod(p, 0o600)
print(f"  Generated new 32-byte HMAC key at {p}")
PY
fi

# Sign the session-start receipt via the popdd-py package.
PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$PROJECT" "$CHAIN" "$KEY_FILE" <<'PY'
import sys
from pathlib import Path
from popdd import HmacSigner, ReceiptChain

project, chain_path, key_file = sys.argv[1], sys.argv[2], sys.argv[3]
key = bytes.fromhex(Path(key_file).read_text().strip())
signer = HmacSigner(key)

# Hot chain: load today's chain if it exists, else start fresh
chain = ReceiptChain(signer, agent_id=f"hermes-{project}")
if Path(chain_path).exists():
    chain.load(chain_path)

# Sign session-start (or session-resume)
import os
resume = len(chain.receipts) > 0
action = "session-resume" if resume else "session-start"
chain.append(
    action=action,
    target=f"hermes-session-{project}",
    proof={
        "verdict": "INITIALIZED",
        "project": project,
        "session_type": "interactive",
        "host": os.uname().nodename,
        "pid": os.getpid(),
        "resume": resume,
    },
)
chain.save(chain_path)
result = chain.verify()
print(f"{chain_path}  {len(chain.receipts)}  {result.valid}")
PY
