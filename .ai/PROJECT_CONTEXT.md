# Project Context: ShipZen

## Purpose
ShipZen is a multi-tenant Platform-as-a-Service (PaaS) built on Kubernetes, designed to behave like Vercel or Heroku. Users authenticate with GitHub, connect repositories, and ShipZen automatically builds and deploys their code to a GKE cluster.

## Tech Stack
* **Frontend**: Next.js (App Router), React, NextAuth (GitHub OAuth)
* **Backend API**: Python, FastAPI, WebSockets
* **Background Worker**: Custom Python worker (Redis Streams queue)
* **Kubernetes Controller**: Custom Python operator (Jinja2 templating, kubernetes client)
* **Database**: PostgreSQL on Cloud SQL (psycopg2) for state and RBAC; in-cluster Redis Streams for the deploy queue
* **Infrastructure**: GCP (GKE, Google Artifact Registry, GCS, Secret Manager) managed via Terraform (HCP backend)
* **Cluster Addons**: ArgoCD (GitOps), Kyverno (admission policies), External Secrets Operator, Envoy Gateway, kube-prometheus-stack + Loki, ExternalDNS (Cloudflare), Velero, KEDA (installed, currently unused)
* **Networking**: GKE Dataplane V2 enforces NetworkPolicies; Cloudflare in front of a gateway that only accepts Cloudflare IPs
* **CI/CD**: GitHub Actions

## Architecture & Data Flow
1. **User Action**: User connects a repo in the UI. UI calls the FastAPI backend.
2. **Database**: API creates `projects`, `deployments`, and `outbox_events` records in PostgreSQL.
3. **Build Phase**: API inserts a deploy event into the `outbox_events` table (transactional outbox). The `outbox_relay` coroutine forwards it to a Redis Stream. The Python `worker` picks it up, runs the build, and pushes the image to Google Artifact Registry (`shipzen-builds`).
4. **Deploy Phase**: The leader `controller` (60 s sweep) renders the tenant's manifests from Postgres and commits them to the private `shipzen-tenants` repo via a GitHub App; an ArgoCD ApplicationSet applies them (prune + self-heal). It marks the deployment Running when its pods are ready.
5. **Observability**: Prometheus + Loki; Grafana dashboards generated from `observability/dashboards.py`; alerts go Alertmanager → webhook → `alert-relay` → WhatsApp.
6. **Isolation**: one namespace per project (restricted Pod Security, quota, NetworkPolicy). Build Jobs run as a push-only identity in an isolated namespace.

## Important Directories
* `ui/`: Next.js frontend code
* `api/`: FastAPI backend (`schema.sql`; the deployed schema is `infra/system/schema-configmap.yaml`)
* `worker/`: Python build/task processor
* `controller/`: Python Kubernetes operator
* `terraform/`: Infrastructure-as-Code (GCP + Helm charts)
* `infra/`: Base Kubernetes manifests (ArgoCD manages these)
* `.github/workflows/`: every operation (deploy, destroy, build, reports, security check)
* `observability/dashboards.py`: source of the Grafana dashboards and alert wording
* `scripts/`: CI helpers, orphaned-disk cleanup, network-isolation probe
* `docs/`: human documentation (architecture, security, decisions, runbook, roadmap)

## Architectural Rules
* **Strict GitOps**: No manual infrastructure changes. All infra changes go through GitHub Actions.
* **Separation of Concerns**: Tenant workloads are strictly isolated from system workloads.
* **Transactional Outbox**: Webhook and deploy endpoints write to `outbox_events` atomically with the deployment row; `outbox_relay` forwards to Redis. Never direct-write to Redis from an HTTP handler.
* **Append-Only Auditing**: The `audit_logs` table enforces append-only rules via database triggers.
* **Production Standards**: No "dev" shortcuts. Use real lifecycle policies, GCP Workload Identity (no service account key files), and persistent volumes.
* **No PATs**: GitHub App only for ArgoCD and the controller. No personal access tokens in secrets.
* **Isolation is enforced**: tenants and builds may not reach the platform, other tenants, nodes, Cloud SQL or the metadata server. A new path needs a NetworkPolicy change and a passing Security Check.
* **Least privilege per identity**: builders push images only; never give build Jobs the platform service account.
* **Never touch GCP billing** from code or workflows.

## Future AI Startup Protocol
When starting a new development session:
1. Read `.ai/PROJECT_CONTEXT.md`
2. Read `.ai/CURRENT_STATE.md`
3. Read `.ai/HANDOFF.md`
4. Read `.ai/TASKS.md`
5. Read `.ai/DECISIONS.md` and `docs/decisions.md` when making architectural changes
6. Read `.ai/RULES.md` for specific engineering guidelines
7. Identify the specific files relevant to the requested task
8. Inspect only those files unless broader investigation is necessary
9. Do NOT perform a full repository scan by default
10. Treat the source code as authoritative if it conflicts with stale context documentation
11. Update the relevant `.ai/` files after completing meaningful changes
12. Commit your changes locally when finished, but do NOT push them unless the user has said you may. The user will verify and push them.
13. Keep `docs/` accurate in the same change (see `.ai/RULES.md`).
