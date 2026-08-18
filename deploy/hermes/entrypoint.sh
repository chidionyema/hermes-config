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
