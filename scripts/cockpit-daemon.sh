#!/bin/bash
# Cockpit daemon — kept alive by launchd (ai.hermes.cockpit)
# Sources .env safely (line-by-line to avoid space-in-value issues), then starts FastAPI on 127.0.0.1:8801
export HOME=/Users/chidionyema

# Load secrets from .env line by line (like _load_dotenv does)
ENV_FILE="$HOME/.hermes/.env"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"  # trim leading whitespace
    line="${line%"${line##*[![:space:]]}"}"  # trim trailing whitespace
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac
    case "$line" in
      *=*)
        key="${line%%=*}"
        val="${line#*=}"
        # strip surrounding quotes
        val="${val#\"}"; val="${val%\"}"
        val="${val#\'}"; val="${val%\'}"
        [ -n "$key" ] && export "$key=$val"
        ;;
    esac
  done < "$ENV_FILE"
fi

# Ensure ACL mapping (env uses TELEGRAM_ALLOWED_USERS, code checks TELEGRAM_ALLOWED_USER_IDS)
: "${TELEGRAM_ALLOWED_USER_IDS:="${TELEGRAM_ALLOWED_USERS:-8868748055}"}"
export TELEGRAM_ALLOWED_USER_IDS
export COCKPIT_HOST="${COCKPIT_HOST:-127.0.0.1}"
export COCKPIT_PORT="${COCKPIT_PORT:-8801}"

cd "$HOME/Documents/code/sentinel-loop"
exec /usr/local/bin/python3 -u -m uvicorn sentinel.cockpit.server:create_app \
  --factory --host "$COCKPIT_HOST" --port "$COCKPIT_PORT" --log-level warning
