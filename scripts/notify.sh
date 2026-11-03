#!/usr/bin/env bash
# Send a Telegram message from a workflow.
#
#   TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... bash scripts/notify.sh "text"
#
# Does nothing (and succeeds) when either variable is empty, so workflows can
# call it unconditionally. Never fails the calling step, and never prints the
# token (it is part of the API URL).
set -uo pipefail

text="${1:?usage: notify.sh TEXT}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID repository secrets); not sending."
  exit 0
fi

body=$(jq -cn --arg c "$TELEGRAM_CHAT_ID" --arg t "$text" \
  '{chat_id: $c, text: $t, disable_web_page_preview: true}')
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
  -H 'Content-Type: application/json' -d "$body" \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" || echo 000)
echo "Telegram answered $code"
if [ "$code" != "200" ]; then
  echo "::warning title=Telegram message failed::Telegram answered $code. Check TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and that you sent the bot a message first."
fi
exit 0
