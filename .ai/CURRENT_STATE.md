# Current State: ShipZen-GCP

## Current Development Phase
Phase 1 (Critical Bug Fixes & CI) and Phase 2 (Reliability) fixes have been implemented in the codebase. Development is paused.
Before the next deployment, several new GitHub Secrets must be configured for the CI pipelines to work correctly with Terraform (Redis password, GitHub App credentials).

## Infrastructure Status
| Resource | Status |
|---|---|
| GKE Cluster `shipzen-cluster` | ✅ Running (us-central1, single zone us-central1-a) |
| Node Pool `platform-nodes` | ✅ Running (n2-standard-4, 1 node, autoscale 1-3) |
| GAR `shipzen-platform` | ✅ All 4 images pushed (sha-8fc21f6 → api, ui, controller, worker) |
| GAR `shipzen-builds` | ✅ Created |
| ArgoCD | ✅ Installed, repo access working (GitHub App, repo-creds secret) |
| ArgoCD Application | ⚠️ Pending sync for infrastructure updates (PDBs, probes) |
| External Secrets Operator | ✅ Installed |
| ClusterSecretStore | ✅ Applied |
| Kyverno | ✅ Installed |
| Envoy Gateway | ✅ Installed |
| PostgreSQL | ✅ Running |
| Redis | ✅ Running (Persistence enabled) |
| LoadBalancer | ❌ Not provisioned (depends on pods being healthy) |
| Cloudflare DNS | ❌ Not updated (depends on LoadBalancer IP) |

## Recently Completed Changes (Phase 1, 2, 3 & Production-Readiness Audit)
- Fixed critical runtime crash (`NameError`) in API `PUT /env`.
- Fixed 5 silent error-masking bugs in API env/secrets endpoints (dead `except` blocks).
- Worker startup fragility fixed (logger definition moved).
- API now receives `GCP_PROJECT` env var (fixes all Secret Manager calls).
- Fixed `deploy.yaml` to include missing `TF_VAR_redis_password` and `TF_VAR_github_app_*` credentials.
- `argocd.tf` no longer writes the GitHub App private key to the runner's disk (now passed via env).
- Redis AOF persistence enabled to prevent data loss of queue/events on pod restart.
- Both webhook handlers refactored to use the transactional outbox pattern instead of direct Redis `xadd`.
- Thread-safe locks added to Controller DB pool and API Auth circuit breaker.
- Real `/healthz` HTTP endpoint added to worker for probing Redis connectivity.
- PodDisruptionBudgets added for API, Worker, and Controller.
- **Phase 3**: Fixed `apply-only.yaml` — added missing `TF_VAR_redis_password` and `TF_VAR_github_token` to Plan and Apply steps; corrected secret name `SHIPZEN_APP_INSTALLATION_ID` → `SHIPZEN_GITHUB_APP_INSTALLATION_ID` (now matches `deploy.yaml`).
- **Phase 3**: Renamed `ECR_REPOSITORY_URL` → `GAR_REGISTRY_URL` throughout `api/main.py` — variable declaration, comments, and all 3 image URI construction sites (create_deployment, github_webhook, github_app_webhook).
- **Phase 3**: Updated `docker-compose.local.yml` — `ECR_REPOSITORY_URL`/`ECR_REGISTRY` → `GAR_REGISTRY_URL`/`GAR_REGISTRY`; comments now accurately describe GCP Artifact Registry as the production target.
- **Phase 3**: Fixed deprecated `datetime.utcnow()` → `datetime.now(timezone.utc)` in `controller/models.py`.
- **Phase 3**: Updated `PROJECT_CONTEXT.md` — replaced stale AWS stack references (EKS, ECR, S3, Secrets Manager, Karpenter, IRSA) with accurate GCP equivalents (GKE, GAR, GCS, Secret Manager, KEDA, Workload Identity).
- **Production-Readiness Audit (20 bugs fixed)**:
  - **Critical (4)**: Webhook INSERT syntax corruption; in-flight deployment guard; DATABASE_URL validation; rollback branch hardcoding
  - **High (8)**: /github/branches auth; circuit breaker reset race; env/secret validators; GCS client singleton; _project_failures scope; controller startupProbe; deployment name sanitization; /users/me DB query
  - **Medium (5)**: walk_path recursion limit; httpx client singleton; tenant NetworkPolicy tightening; schema-job resource limits; deletion_protection=true; audit log project_members join; builder CPU limits
  - **Low (3)**: Bare except blocks; duplicate imports cleanup; UI startupProbe; worker HOSTNAME env var

## Active Blocker
**None** — All secrets are present, code is committed and pushed. Waiting for `build-push.yaml` CI to build new worker image with the nixpacks fix (ec76bca).

## Recently Fixed (Live Production Builds)
- **B-01**: Nixpacks image tag `ubuntu-1718844893` deleted upstream → changed to `:latest` (commit 2197632)
- **B-02**: Nixpacks `--out /workspace/.nixpacks` generated Dockerfile at wrong nested path `.nixpacks/.nixpacks/Dockerfile` → changed to `--out /workspace` so Dockerfile lands at `.nixpacks/Dockerfile` (commit ec76bca)
- **B-03**: `app-deployment.yaml.j2` ExternalSecret keyed by `project_name` instead of `project_id` → fixed template + controller context (commit 2197632)

## Known Issues
1. LoadBalancer not provisioned - resolves after pods are healthy and ArgoCD syncs.
2. Worker image in cluster is sha-2197632 (has B-01 fix). B-02 fix (ec76bca) will land once `build-push.yaml` CI completes and ArgoCD syncs.


## What Will Happen on Next apply-only.yaml Run
1. Terraform uses new secrets to provision ArgoCD GitHub App credentials reliably.
2. Terraform applies Redis persistence configuration.
3. ArgoCD syncs infrastructure changes (PDBs, new probes, env vars).
4. Envoy Gateway creates LoadBalancer service.
5. ExternalDNS updates DNS.
6. Site goes live.

## Infrastructure Details
- **Cluster**: shipzen-cluster (us-central1 regional, single zone us-central1-a)
- **Machine type**: n2-standard-4 (4 vCPU, 16 GB RAM)
- **GCP Project**: project-ce3f7c39-eceb-4221-a76
- **Terraform state**: HCP Terraform, org: jeneel-shipzen, workspace: ShipZen-GCP
- **Repo**: https://github.com/jeneeldumasia/ShipZen-GCP (private)
- **ArgoCD source path**: infra/
- **Image registry**: us-central1-docker.pkg.dev/project-ce3f7c39-eceb-4221-a76/shipzen-platform/

## Operators Installed in Cluster
- ArgoCD (GitOps controller)
- External Secrets Operator (syncs GCP Secret Manager → k8s secrets)
- Kyverno (pod security policies)
- KEDA (autoscaling)
- Envoy Gateway (ingress / LoadBalancer)
- kube-prometheus-stack (Prometheus + Grafana)
- ExternalDNS (auto Cloudflare DNS from gateway annotations)

## Important Notes for Next Developer/AI
- **No PATs** - GitHub App only for ArgoCD (SHIPZEN_GITHUB_APP_ID, SHIPZEN_APP_INSTALLATION_ID)
- **Manual workflows only** - no auto-deploy on push (user preference)
- **Auto-destroy runs every 6 hours** via destroy.yaml cron schedule
- **Never run terraform locally** - always via GitHub Actions
- **Single zone** - intentional for dev cost savings, not a bug
- **Kyverno blocks privileged pods** - builder pods need PolicyException (already configured)
