#!/bin/bash
# popdd-init.sh — Initialize/append a POPDD session receipt to today's chain.
# Idempotent: appends a session-resume receipt to today's chain if it exists.
# Usage:
#   ./popdd-init.sh [project-name] [phase]
#     project-name: hermes, signalengine, lux, prospector (default: hermes)
#     phase:        start | resume | action | complete (default: auto)
#
# Output (stdout): "<chain_path>  <total_receipts>  <chain_valid>"

set -e

PROJECT="${1:-hermes}"
PHASE="${2:-auto}"
LUX_ROOT="$HOME/.lux"
mkdir -p "$LUX_ROOT/keys" "$LUX_ROOT/receipts"

PYTHONPATH="$HOME/Documents/code/popdd-py" python3 - "$PROJECT" "$PHASE" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Documents" / "code" / "popdd-py"))
from popdd.agent import PopddAgent

project, phase = sys.argv[1], sys.argv[2]
# Per-project subdirectory under ~/.lux/receipts/<project>/ — keeps each
# project's chain isolated so orphaned chains from other keys don't break
# the signature check.
agent = PopddAgent(
    Path.home() / ".lux",
    agent_id=f"hermes-{project}",
    key_dir="keys",
    receipt_dir=f"receipts/{project}",
)

if phase == "auto":
    phase = "resume" if len(agent._receipts) > 0 else "start"

agent.sign_generic(
    f"session-{phase}",
    f"hermes-session-{project}",
    verdict="INITIALIZED",
    project=project,
    phase=phase,
    host=os.uname().nodename,
    pid=os.getpid(),
)

# Build the chain file path the agent would have written to
chain_file = agent._receipt_dir / f"{agent._receipts[-1].timestamp[:10]}.jsonl"
result = agent.verify_chain()
print(f"{chain_file}  {result['total']}  {result['valid']}")
PY
