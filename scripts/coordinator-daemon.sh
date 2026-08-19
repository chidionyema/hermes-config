#!/bin/zsh
# Launchd wrapper for the autonomous coordinator. launchd gives a bare environment:
# no ~/.local/bin on PATH (where claude/agy live) and none of the provider API keys.
# This restores both WITHOUT baking secrets into the plist — keys stay in ~/.hermes/.env.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# launchd does not set the user-identity vars. The `claude` CLI resolves its OAuth token
# from the macOS keychain ("Claude Code-credentials"), which needs USER/LOGNAME to identify
# the security session — without them claude reports "Not logged in" and the strategist
# silently rotates to the (headless-broken) agy CLI. TMPDIR keeps tooling from writing to /.
export USER="${USER:-$(id -un)}"
export LOGNAME="${LOGNAME:-$USER}"
export TMPDIR="${TMPDIR:-/tmp}"
# Load ONLY the provider API keys from .env. A blanket `source` breaks because .env
# also holds entries with unquoted spaces (e.g. AGENT_BROWSER_EXECUTABLE_PATH). We
# deliberately SKIP ANTHROPIC_API_KEY (dead pay-per-token credits) so the claude/agy
# CLIs fall through to the working OAuth subscription.
if [ -f "$HOME/.hermes/.env" ]; then
  set -a
  # GEMINI dropped 2026-08-06 with the provider (429 credits depleted); exporting
  # a key for a retired provider is how a dead backend keeps looking configured.
  eval "$(grep -E '^(DEEPSEEK|MINIMAX)_API_KEY=' "$HOME/.hermes/.env")"
  set +a
fi
unset ANTHROPIC_API_KEY
# -u is load-bearing. stdout here is a FILE (launchd StandardOutPath), so python block-
# buffers it at 8KB and a daemon that never exits never flushes. The daemon now mirrors
# every event to stdout as one JSON line; without -u those lines would sit in a buffer
# for the life of the process and logs/coordinator.log would stay at the 0 bytes it held
# for 60 days.
exec /usr/local/bin/python3 -u "$HOME/.hermes/scripts/coordinator.py" "${1:-daemon}"
