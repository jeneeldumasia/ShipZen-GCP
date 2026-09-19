# Handoff Document - ShipZen-GCP

## What This Project Is
ShipZen is a multi-tenant platform-as-a-service. Users connect a GitHub repo,
ShipZen builds it into a container (via worker + buildkit), deploys it onto GKE
(via controller), and exposes it at a subdomain. It's a mini Heroku on GCP.

## Components
| Component | Purpose | Location |
|---|---|---|
| `ui/` | Next.js frontend dashboard | Deployed as `shipzen-ui` |
| `api/` | FastAPI backend + auth | Deployed as `shipzen-api` |
| `worker/` | Build job dispatcher | Deployed as `shipzen-worker` |
| `controller/` | Tenant namespace/deploy manager | Deployed as `shipzen-controller` |
| `infra/` | ArgoCD-managed k8s manifests | Synced by ArgoCD |
| `terraform/` | GCP infrastructure | Applied via GitHub Actions |

## How to Deploy
1. Make code changes, push to main
2. If app code changed: run `build-push.yaml` to build new images
3. Run `apply-only.yaml` to apply terraform + trigger ArgoCD sync

## How to Destroy
Run `destroy.yaml` (manual or auto every 6h).
Do NOT run terraform destroy locally - the pipeline handles GCP artifact cleanup first.

## Accessing the Cluster
```bash
# Add to PATH first (Windows)
$env:PATH += ";$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"

# Get credentials
gcloud container clusters get-credentials shipzen-cluster \
  --region us-central1 \
  --project project-ce3f7c39-eceb-4221-a76

# Access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Then open https://localhost:8080
# Password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

## Key GitHub Secrets Required
| Secret | Purpose |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | GitHub Actions → GCP auth |
| `GCP_SERVICE_ACCOUNT` | GCP service account email |
| `GCP_PROJECT_ID` | GCP project ID |
| `TF_API_TOKEN` | HCP Terraform token |
| `REDIS_PASSWORD` | Static password for Redis cluster |
| `SHIPZEN_APP_INSTALLATION_ID` | ArgoCD GitHub App Installation ID |
| `SHIPZEN_GITHUB_APP_ID` | ArgoCD GitHub App ID |
| `SHIPZEN_GITHUB_APP_PRIVATE_KEY` | ArgoCD GitHub App private key (PEM) |
| `SHIPZEN_OAUTH_CLIENT_ID` | OAuth for UI login |
| `SHIPZEN_OAUTH_CLIENT_SECRET` | OAuth for UI login |
| `SHIPZEN_GITHUB_APP_WEBHOOK_SECRET` | GitHub webhook HMAC secret |
| `SHIPZEN_AUTH_SECRET` | NextAuth secret |
| `CLOUDFLARE_API_TOKEN` | DNS management |
| `PG_PASSWORD` | PostgreSQL password |
| `GRAFANA_PASSWORD` | Grafana admin password |
| `ARGOCD_ADMIN_PASSWORD` | Custom ArgoCD admin password (optional) |

## Current Blocker (as of last session)
All Phase 1, 2, and 3 fixes have been applied and committed. All required GitHub Secrets are now present. **Run `apply-only.yaml`** to deploy and get the site live.

## Common Debugging Commands
```bash
# Check pod status
kubectl get pods -n shipzen-system

# Check ArgoCD sync
kubectl get application shipzen-platform -n argocd
kubectl describe application shipzen-platform -n argocd

# Check image pull errors
kubectl describe pod <pod-name> -n shipzen-system | grep -A5 "Failed"

# Check ESO secret sync
kubectl get externalsecret -n shipzen-system

# Check LoadBalancer
kubectl get svc -A | grep LoadBalancer

# Check gateway
kubectl get gateway -A
kubectl get httproute -A

# ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=50
```
