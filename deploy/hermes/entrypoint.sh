#!/usr/bin/env bash
# Everything that must be true before any Hermes job starts.
set -euo pipefail

# State lives on the volume, never in the image. These are the directories the laptop
# jobs assume exist; launchd created them years ago and nobody has thought about them
# since, which is exactly why a fresh container fails on the first write.
for d in logs state runs receipts; do
  mkdir -p "/data/$d"
  ln -sfn "/data/$d" "/Users/chidionyema/.hermes/$d"
done

# MAKE ~/.hermes/.env EXIST. Eight scripts read it as a file; on Fly the same values are
# environment variables. Without this, otto-server dies on FileNotFoundError at import time
# and supervisor parks it in FATAL, while every other program starts - so the container looks
# healthy from the outside. See deploy/hermes/env.keys for what goes in and why it is a
# declared list rather than a dump of the environment.
#
# Written to the image filesystem, never to /data: a secret belongs in neither a layer nor a
# volume snapshot. It is rebuilt from the environment on every boot.
ENV_KEYS=/Users/chidionyema/.hermes/deploy/hermes/env.keys
ENV_FILE=/Users/chidionyema/.hermes/.env
if [ -f "$ENV_KEYS" ]; then
  umask 077
  : > "$ENV_FILE"
  written=0
  while read -r k; do
    case "$k" in ''|'#'*) continue ;; esac
    # Indirect expansion, so an unset key is skipped rather than written as an empty string -
    # an empty TELEGRAM_BOT_TOKEN reads as "configured" to every script that tests for presence.
    if [ -n "${!k:-}" ]; then
      printf '%s=%s\n' "$k" "${!k}" >> "$ENV_FILE"
      written=$((written + 1))
    fi
  done < "$ENV_KEYS"
  # Count only. Never the names, and never the values.
  echo "entrypoint: wrote $written secrets into $ENV_FILE" >&2
fi

# THE DOUBLE-ANSWER FENCE. The Telegram gateway is a long poller. Two of them against
# one bot token means every message is answered twice, and Telegram hands each update
# to whichever process asked first, so the two disagree at random. While the laptop
# gateway is still running, this one must not start. It is `autostart=false` in
# supervisord and is started deliberately, after the laptop's is stopped:
#
#   fly ssh console -a hermes -C "supervisorctl start gateway"
#
# This line only reports the state, because refusing to boot the whole container over
# it would take the coordinator and cockpit down with it.
if [ "${HERMES_GATEWAY_AUTOSTART:-0}" = "1" ]; then
  echo "entrypoint: gateway WILL autostart - make sure the laptop gateway is stopped" >&2
else
  echo "entrypoint: gateway is held back; start it with 'supervisorctl start gateway'" >&2
fi

exec "$@"
