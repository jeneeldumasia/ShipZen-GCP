# Handoff: ShipZen-GCP

Short version for the next person or assistant. The full operating guide is
`docs/operations/runbook.md`; architecture is `docs/architecture.md`.

## What it is
A Heroku-style PaaS on GKE: GitHub repo → build (Kaniko / Nixpacks) → image in
Artifact Registry → controller commits manifests to `shipzen-tenants` → ArgoCD
deploys into a per-project namespace → Envoy Gateway behind Cloudflare.
Postgres (Cloud SQL) is the source of truth.

## Components
| | Path | Notes |
|---|---|---|
| UI | `ui/` | Next.js 16, NextAuth v5 (GitHub), allowlist enforced in `signIn` |
| API | `api/` | FastAPI; outbox → Redis Stream; roles owner/editor/viewer |
| Worker | `worker/` | consumer group, build Jobs in `shipzen-build`, retries + DLQ |
| Controller | `controller/` | leader-elected, 60 s sweep, renders `controller/templates/`, commits to Git |
| Alert relay | `infra/system/alert-relay/` | Alertmanager webhook → WhatsApp |
| Infra | `terraform/`, `infra/` | Terraform for GCP and operators; Kustomize tree for ArgoCD |

## How to operate (all via GitHub Actions)
- Bring up: **Deploy Platform Infra**, then **Build and Push** if images are missing.
- Change infra: edit `terraform/`, merge, run **Apply Infrastructure Changes**. `infra/` changes sync by themselves.
- Tear down: **Infra Teardown** (Auto-Destroy does this at 24 h).
- Diagnose: **Cluster Report** (read-only annotations), Grafana Overview.
- Verify security: **Security Check** (builder identity + network isolation).

## Access
- https://shipzen.jeneeldumasia.codes · https://argocd.jeneeldumasia.codes · https://grafana-shipzen.jeneeldumasia.codes
- `gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project <project>`
- Never write passwords or tokens into the repo, docs or `.ai/` files.

## Required GitHub secrets
`GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `TF_API_TOKEN`,
`CLOUDFLARE_API_TOKEN`, `PG_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_PASSWORD`,
`SHIPZEN_OAUTH_CLIENT_ID/SECRET`, `SHIPZEN_GITHUB_APP_ID`, `SHIPZEN_APP_INSTALLATION_ID`,
`SHIPZEN_GITHUB_APP_PRIVATE_KEY`, `SHIPZEN_GITHUB_APP_WEBHOOK_SECRET`, `SHIPZEN_AUTH_SECRET`;
optional `ARGOCD_ADMIN_PASSWORD`, `WHATSAPP_PHONE`, `WHATSAPP_APIKEY`.

## Before you change things
- Dashboards: edit `observability/dashboards.py`, run it, commit both files (a test checks they match).
- New alert: add it to `infra/system/shipzen-alerts.yaml` **and** to `PROBLEM_TEXT` in `dashboards.py`.
- Any new network path (platform ↔ tenant, tenant → something internal) needs a NetworkPolicy change first, then **Security Check**.
- `tenant.yaml.j2` changes reach existing projects within about 20 minutes. App manifests (`app-deployment.yaml.j2`) re-render on the next sweep.
- Run `pytest` before pushing.
