#!/bin/bash
# Otto daemon — kept alive by launchd (ai.hermes.otto-server)
# Loads the hermes AI agent and exposes it via HTTP on 127.0.0.1:8802
export HOME=/Users/chidionyema

# Load secrets from .env line by line (safe for values with spaces)
ENV_FILE="$HOME/.hermes/.env"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac
    case "$line" in
      *=*)
        key="${line%%=*}"
        val="${line#*=}"
        val="${val#\"}"; val="${val%\"}"
        val="${val#\'}"; val="${val%\'}"
        [ -n "$key" ] && export "$key=$val"
        ;;
    esac
  done < "$ENV_FILE"
fi

# The otto server needs the hermes-agent package on PYTHONPATH
export PYTHONPATH="$HOME/.hermes/hermes-agent:$PYTHONPATH"
cd "$HOME/.hermes/hermes-agent"
exec /usr/local/bin/python3 \
  "$HOME/Documents/code/sentinel-loop/scripts/otto_server.py" 8802
