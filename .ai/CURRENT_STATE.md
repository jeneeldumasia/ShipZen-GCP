# Current State: ShipZen-GCP

## Current Development Phase
GCP infrastructure is deployed. Platform pods are failing to start due to GKE node pool
oauth scope issue (403 on GAR image pull). Fix has been committed - next `apply-only.yaml`
run will resolve it.

## Infrastructure Status
| Resource | Status |
|---|---|
| GKE Cluster `shipzen-cluster` | ✅ Running (us-central1, single zone us-central1-a) |
| Node Pool `platform-nodes` | ✅ Running (n2-standard-4, 1 node, autoscale 1-3) |
| GAR `shipzen-platform` | ✅ All 4 images pushed (sha-8fc21f6 → api, ui, controller, worker) |
| GAR `shipzen-builds` | ✅ Created |
| ArgoCD | ✅ Installed, repo access working (GitHub App, repo-creds secret) |
| ArgoCD Application | ⚠️ OutOfSync / Degraded (pods can't pull images - 403) |
| External Secrets Operator | ✅ Installed |
| ClusterSecretStore | ✅ Applied |
| Kyverno | ✅ Installed |
| Envoy Gateway | ✅ Installed |
| PostgreSQL | ✅ Running |
| Redis | ✅ Running |
| LoadBalancer | ❌ Not provisioned (depends on pods being healthy) |
| Cloudflare DNS | ❌ Not updated (depends on LoadBalancer IP) |

## Recently Completed Changes
- Full AWS → GCP migration (EKS→GKE, ECR→GAR, S3→GCS, AWS Secrets→GCP Secret Manager)
- Cost optimization: 3 zones → 1 zone dev (saves ~$179/month)
- GitHub App auth for ArgoCD (no PAT, company policy)
- Fixed ArgoCD secret label: `repository` → `repo-creds`
- Built and pushed all 4 container images to GAR
- Fixed build workflow GAR path: `shipzen` → `shipzen-platform`
- Added `oauth_scopes` to node pool for GAR image pull access
- Added `kubectl wait` for ESO webhook pod before ClusterSecretStore apply
- Rewrote destroy.yaml with 4-phase teardown (prevents VPC deletion failure)
- Merged Copilot PR: ExternalDNS, node SA for GAR, helm wait flags

## Active Blocker
**Pods are in ErrImagePull / Kyverno webhook deadlock**

Root cause: When the oauth_scopes were added to the node pool, GKE drained and
recreated the node. This killed Kyverno pods mid-drain, so new pods can't be
created (webhook unavailable). The node is back but Kyverno hasn't recovered.

**Fix: Run `apply-only.yaml`** - Terraform will reconcile the node pool (already
has oauth_scopes), ESO webhook wait logic will hold until it's ready, and ArgoCD
will re-sync with correct images.

## Known Issues (will be resolved by next apply-only.yaml run)
1. Pods stuck in ErrImagePull (403 GAR) - fixed by oauth_scopes on node pool
2. Kyverno webhook deadlock after node drain - resolves once Kyverno pods restart
3. LoadBalancer not provisioned - resolves after pods are healthy and ArgoCD syncs

## What Will Happen on Next apply-only.yaml Run
1. Terraform: node pool already has oauth_scopes → no-op on node pool
2. Terraform: ESO ClusterSecretStore will wait for webhook pod Ready
3. ArgoCD syncs with sha-8fc21f6 images → pods pull successfully from GAR
4. Envoy Gateway creates LoadBalancer service
5. ExternalDNS OR Cloudflare step updates DNS
6. Site goes live at shipzen.jeneeldumasia.codes

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
