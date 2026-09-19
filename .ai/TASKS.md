# ShipZen-GCP Task Tracker

## Current (Do This Next)
- [ ] **Run `apply-only.yaml`** to deploy all fixes and get the site live
  - URL: https://github.com/jeneeldumasia/ShipZen-GCP/actions/workflows/apply-only.yaml
  - Expected outcome: all pods Running, LoadBalancer provisioned, DNS updated

## Blocked On
Nothing — all secrets are present, all code fixes are committed.

## After apply-only.yaml Succeeds
- [ ] Verify all pods Running: `kubectl get pods -n shipzen-system`
- [ ] Verify LoadBalancer IP: `kubectl get svc -A | grep LoadBalancer`
- [ ] Verify site accessible: https://shipzen.jeneeldumasia.codes
- [ ] Verify ArgoCD UI: https://argocd.jeneeldumasia.codes
- [ ] Verify Grafana: https://grafana.jeneeldumasia.codes
- [ ] Test end-to-end: connect a GitHub repo via UI, trigger a build

## Completed
- ✅ Phase 1: API runtime crash fix, 5 silent error bugs, worker startup fragility, missing GCP_PROJECT.
- ✅ Phase 1: CI `deploy.yaml` updated with `TF_VAR_redis_password` and GitHub App variables.
- ✅ Phase 1: `argocd.tf` private key /tmp disk write security hole fixed.
- ✅ Phase 1: Redis persistence (AOF) enabled.
- ✅ Phase 2: Webhooks use transactional outbox, outbox relay `UnboundLocalError` fixed.
- ✅ Phase 2: Double-checked locking added to controller DB pool, Lock added to API circuit breaker.
- ✅ Phase 2: Real `/healthz` HTTP endpoint added to worker for Redis/loop liveness.
- ✅ Phase 2: PodDisruptionBudgets added for API, worker, controller.
- ✅ Phase 3: `apply-only.yaml` fixed — added missing `TF_VAR_redis_password`; corrected `SHIPZEN_APP_INSTALLATION_ID` secret name (was `SHIPZEN_GITHUB_APP_INSTALLATION_ID`); removed non-existent `TF_VAR_github_token`.
- ✅ Phase 3: `deploy.yaml` fixed — same installation ID correction, `github_token` removed (optional var with default="", GitHub App handles ArgoCD access).
- ✅ Phase 3: `api/main.py` — renamed `ECR_REPOSITORY_URL` → `GAR_REGISTRY_URL` throughout (variable, comments, all 3 image URI construction sites).
- ✅ Phase 3: `docker-compose.local.yml` — `ECR_REPOSITORY_URL`/`ECR_REGISTRY` → `GAR_REGISTRY_URL`/`GAR_REGISTRY`; comments updated for GCP.
- ✅ Phase 3: `controller/models.py` — `datetime.utcnow()` → `datetime.now(timezone.utc)` (deprecated in Python 3.12+).
- ✅ Phase 3: `.ai/PROJECT_CONTEXT.md` — replaced stale AWS stack (EKS, ECR, S3, Secrets Manager, IRSA) with GCP equivalents (GKE, GAR, GCS, Secret Manager, Workload Identity).
- ✅ Cost optimization (3 zones → 1 zone, saves ~$179/month)
- ✅ GitHub App auth for ArgoCD (no PAT)
- ✅ Build workflow fixed (correct GAR path)
- ✅ All 4 images built and pushed to GAR (sha-8fc21f6)

## Backlog
- [ ] Production readiness: 3-zone HA setup
- [ ] Cloud SQL PostgreSQL (replace in-cluster)
- [ ] Memorystore Redis (replace in-cluster)
- [ ] Custom domains for tenant deployments
- [ ] Cost monitoring / billing alerts
- [ ] Update architecture diagrams for GCP
- [ ] Runbook for common operations

## Won't Do
- ~~PAT for GitHub auth~~ (company policy)
- ~~Auto-deploy on git push~~ (user preference, manual only)
- ~~Multi-zone for dev~~ (cost savings)
- ✅ Remove the 'Restart System Pods' button from the admin UI (SystemControls.tsx) because ArgoCD reverts the deployment patches.