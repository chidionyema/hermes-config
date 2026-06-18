#!/bin/bash
# otto-dispatch.sh — cron wrapper for the Otto relay step (Ball 17).
# Runs the deterministic dispatcher that reads queue/pending-digest.json, auto-remediates
# mechanical issues, and forwards to the user only what Otto decides is worth their
# attention. deliver:origin on this cron sends its (curated) stdout to the user.
exec python3 "$HOME/.hermes/scripts/otto-dispatch.py"
