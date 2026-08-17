#!/bin/bash
set -u
# ci-watchdog.sh — shell wrapper around ci-watchdog.py.
# Output: silent when healthy+unchanged, delivers Telegram message on change/failure.
PROBE="$HOME/.hermes/scripts/ci-watchdog.py"
[ -f "$PROBE" ] || { echo "CI watchdog missing: $PROBE" >&2; exit 1; }
output=$(timeout 30 python3 "$PROBE" 2>&1) || { echo "CI watchdog crashed: $output" >&2; exit 1; }
[ -z "$output" ] && exit 0
timeout 60 hermes send --to telegram "$output" 2>&1
exit $?
