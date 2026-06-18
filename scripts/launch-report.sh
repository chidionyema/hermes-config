#!/bin/bash
# Launch status report — aggregated view for all projects.
# Run when user asks for launch update or when significant work completes.

echo "=== Launch Update :: $(date '+%Y-%m-%d %H:%M') ==="
echo ""

# Prospector
echo "【Prospector】"
cd ~/Documents/code/prospector 2>/dev/null || { echo "  Repo not found"; echo ""; exit 1; }
echo "  Branch: $(git branch --show-current)"
echo "  Python tests: $(.venv/bin/python -m pytest -q --no-header --ignore=tests/test_ui_theme.py 2>&1 | tail -1)"
echo "  .NET tests: $(cd store_platform && dotnet test src/Store.Tests/ --no-build --no-restore 2>&1 | tail -1)"
echo "  Golden set: $(.venv/bin/python -m pytest tests/test_golden_set.py -q --no-header 2>&1 | tail -1)"
echo "  Uncommitted: $(git status --short | wc -l | tr -d ' ') files"
echo ""

# Signal Engine
echo "【Signal Engine】"
cd ~/Documents/code/signalengine 2>/dev/null || { echo "  Repo not found"; echo ""; exit 1; }
echo "  Branch: $(git branch --show-current)"
echo "  Tests: $(uv run pytest -q -m 'not slow' --no-header --tb=line -p no:cacheprovider 2>&1 | tail -1)"
echo "  Uncommitted: $(git status --short | wc -l | tr -d ' ') files"
echo ""

# LUX
echo "【LUX】"
cd ~/Documents/code/lux 2>/dev/null || { echo "  Repo not found"; echo ""; exit 1; }
echo "  Branch: $(git branch --show-current)"
echo "  Tests: $(npx jest --passWithNoTests --silent 2>&1 | tail -1)"
echo "  Uncommitted: $(git status --short | wc -l | tr -d ' ') files"
echo ""

# P0 blockers status
echo "=== P0 Blocker Status ==="
echo "  ✅ Fulfilment chain (DeliveryEndpoints, FulfilmentService, WebhookEndpoints)"
echo "  ✅ Provisional publish guard (bridge.py blocks provisional PASSes)"
echo "  ✅ Pricing conflict resolved (compose_packs deleted, £30 single source)"
echo "  🔴 Server-side auth on /internal/catalog — DISPATCHED"
echo "  🔴 Live Paddle credentials — needs user account setup"
echo "  🔴 Legal/Terms/Privacy — needs external review"
echo "  🔴 API test harness — DISPATCHED"
echo "  🔴 CI pipeline + golden-set gate — DISPATCHED"
