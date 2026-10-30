# ShipZen-GCP Task Tracker

The backlog lives in `docs/roadmap.md`. This file only tracks what's in flight.

## In flight
- [ ] WhatsApp alerts: user activates CallMeBot, adds `WHATSAPP_PHONE` / `WHATSAPP_APIKEY` repo secrets, runs **Deploy Secrets** (sends a test message).
- [ ] After every rebuild: run **Security Check**. Network isolation must report all PASS on Dataplane V2 clusters.

## Won't do
- Personal access tokens (GitHub App only).
- Multi-zone for the dev cluster (cost).
- Enabling or changing GCP billing from automation.
