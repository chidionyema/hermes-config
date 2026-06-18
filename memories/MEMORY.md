[tags: project:prospector domain:go-live type:state] Prospector branch bug3-fulfilment-chain. Fulf chain built (DeliveryEndpoints, FulfilmentService, WebhookEndpoints, orders/[token].tsx). Python 352 pass, .NET 39 pass, golden set 1/1. P0: live payments, legal, entitlements stub.
§
[tags: project:lux domain:pdd type:state] POPDD inline attestation done: lux spec verify appends POPDD receipt per-function (lines 254-268 in src/cli.ts). popdd_verify.py handles batch test-run receipts. CI gate script at ~/Documents/code/lux/scripts/ci-gate.sh — checks modified functions against receipts. Pre-commit hooks copied to all 3 repos.
§
[tags: project:hermes-config domain:infra type:decision] Hermes-Claude model: Hermes owns control loop. Claude consulted at decision points (planning, decomposition, judgment, verification). Pass full state each call. Claude returns structured JSON output (plan, next_action, rationale). Model tiering: Opus for hard strategy, Sonnet for lighter planning, Minimax for cheap execution.
§
INVARIANTS — always injected. (1) Source-or-die: every factual claim cites retrievable source or is unverifiable. (2) Verdict-from-retrieval-only: model rules only from fetched passages. (3) Kill-fast: cheapest decisive gate first. (4) Hermes owns control loop; Claude consulted at decisions; Minimax for cheap execution. (5) Never commit secrets. (6) Never substitute fabricated output for real execution results.
§
Otto active objectives stored at ~/Documents/code/.hermes/OBJECTIVES.md. Read on session start to pick up where I left off.
§
When user gives me a problem I'm unsure how to fix: delegate to Claude Code with full context, the problem spec, and what's been tried. Track the task in todo, report progress and result. Never guess or attempt a fix I'm not confident about.
§
Self-reflection 2026-06-18: root cause of all corrections is acting before thinking. Fix: delegate to Claude before acting on anything fuzzy. Present options, not actions. Batch corrections in skill, never repeat. Anticipate next question. Track correction rate trending to zero.