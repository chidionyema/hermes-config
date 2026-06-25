#!/bin/bash
# ngrok daemon — kept alive by launchd (ai.hermes.ngrok)
# Exposes port 8801 to the public internet so Telegram can reach the webhook
export HOME=/Users/chidionyema
export PATH="/usr/local/bin:$PATH"
exec /usr/local/bin/ngrok http 8801 --log=stdout
