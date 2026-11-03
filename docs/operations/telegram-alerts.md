# Set up Telegram alerts

ShipZen sends its alerts to one Telegram chat:

- **Platform problems** from inside the cluster (an app keeps crashing, error
  rate is high, a node is down, …), in the same plain words as Grafana, and a
  ✅ message when each one clears. Prometheus → Alertmanager →
  `alert-relay` → Telegram.
- **Teardown problems** from GitHub Actions: the database backup failed before
  a teardown, or the teardown itself failed (resources may still be billing).

It's free and takes about 5 minutes. Until it's set up, nothing breaks: alerts
are simply dropped, and failures are only visible in GitHub Actions.

## 1. Create a bot

1. In Telegram, open **@BotFather** (blue check mark) and send `/newbot`.
2. Pick a display name (for example `ShipZen Alerts`) and a username that ends
   in `bot` (for example `shipzen_jeneel_bot`).
3. BotFather replies with a **bot token** like `123456789:AAH...`.
   Treat it like a password: anyone with it can post as your bot.

## 2. Say hello to the bot

Open your new bot (BotFather links it) and send it any message, such as `hi`.
A Telegram bot can't message you until you've messaged it first.

## 3. Find your chat ID

Open this in a browser, with your token in place of `<token>`:

```
https://api.telegram.org/bot<token>/getUpdates
```

Look for `"chat":{"id":123456789,...}` and copy the number. That's your
**chat ID**.

- **Use your phone** (or a home network) for this step. The work network
  blocks `api.telegram.org`, so the page won't load there. ShipZen itself is
  unaffected: GitHub's runners and GKE can reach Telegram.
- If the result is empty (`"result":[]`), send the bot another message and
  reload.

## 4. Add two repository secrets

GitHub → the ShipZen-GCP repository → **Settings** → **Secrets and variables**
→ **Actions** → **New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from step 1 |
| `TELEGRAM_CHAT_ID` | the number from step 3 |

From this point the **teardown alerts** work, even while the platform is down;
they read these secrets directly.

## 5. Push them to the platform and test

Run **Actions → Deploy Secrets to GKE → Run workflow**. It:

1. stores both values in Secret Manager as `shipzen-telegram`;
2. sends a test message: *"ShipZen alerts are connected…"*. Check Telegram.

The workflow's later steps need the cluster, so run it while the platform is up
(after **Deploy Platform Infra**). If the platform is down, the test message
still arrives, and the run then fails at "Update kubeconfig", which is harmless.

The in-cluster relay picks up the new values within about 10 minutes, with no
restart. Every later **Deploy Platform Infra** keeps them (it never overwrites
`shipzen-telegram`).

## Check it's working

- **Test message didn't arrive:** open the Deploy Secrets run. The Telegram step
  prints `Telegram answered <code>`:
  - `401`: the token is wrong.
  - `400` / `403`: the chat ID is wrong, or you haven't messaged the bot yet
    (step 2).
- **In-cluster alerts:** `kubectl logs -n observability deploy/alert-relay`
  shows `Telegram answered 200` for each message sent, or
  `Telegram not configured` if the secret is still empty.

## Change or stop alerts

- **New chat or token:** update the repository secrets and run **Deploy Secrets
  to GKE** again.
- **Stop all alerts:** store empty values:
  ```bash
  echo -n '{"bot_token": "", "chat_id": ""}' | bash scripts/put-secret.sh shipzen-telegram
  ```
  and delete the two repository secrets.
- **Token leaked:** in @BotFather send `/revoke`, pick the bot, then update
  `TELEGRAM_BOT_TOKEN` and rerun **Deploy Secrets to GKE**.

## Leftovers from the WhatsApp setup (optional cleanup)

ShipZen used to alert through CallMeBot/WhatsApp, which stopped accepting new
users. If they exist, these are no longer used:

- the repository secrets `WHATSAPP_PHONE` and `WHATSAPP_APIKEY`: delete them in
  GitHub;
- the Secret Manager secret `shipzen-whatsapp`:
  `gcloud secrets delete shipzen-whatsapp`. It holds one version, inside the
  free tier, but deleting it keeps the project at or under the 6 free versions.

## How it fits together

- Relay code: `infra/system/alert-relay/relay.py`.
- Relay deployment and its ExternalSecret: `infra/system/alert-relay.yaml`.
- Alertmanager routing (`warning`, `high` and `critical` go to the `telegram`
  receiver): `terraform/monitoring.tf`.
- Workflow sender: `scripts/notify.sh`.
- Why Telegram, and why a relay: [decisions.md #14](../decisions.md).
