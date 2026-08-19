#!/usr/bin/env bash
# Ask every configured model provider for a real token, hourly, and tell the founder DIRECTLY
# when none of them will sell one.
#
# 2026-08-19: MiniMax returned HTTP 429 "Token Plan usage limit reached" on every call for days.
# fallback_model was [], DeepSeek was 402 Insufficient Balance, Gemini 429 credits depleted, and
# the ANTHROPIC/OPENAI keys were empty strings. The agent had no brain and the only signal the
# founder ever received was Telegram going quiet.
#
# Two reasons the existing alert chain could not carry this:
#   1. scripts/provider_chain_check.py graded the KEY, not the balance, and printed OK.
#   2. watchdog alerts go to the gateway queue, drained by queue-curator and forwarded by
#      otto-dispatch -- both agent jobs. The message "there is no brain" needed a brain.
# --alert goes straight to Telegram over urllib for exactly that reason.
#
# Exit 0 = at least one provider answered a live call. Exit 1 = no brain.
set -uo pipefail
exec /usr/bin/env python3 "$HOME/.hermes/scripts/provider_chain_check.py" --probe --alert
