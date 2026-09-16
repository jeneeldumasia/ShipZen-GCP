# ShipZen Quick Start Guide

This guide helps you quickly diagnose and fix common issues with your ShipZen GCP deployment.

## 🚨 Common Issues & Fixes

### Issue 1: "Cluster is not running" Error

**Symptoms:**
- `gcloud container clusters get-credentials` fails
- `kubectl` commands return "The connection to the server was refused"

**Fix:**
```powershell
# Run the cluster access fix script
.\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID

# If cluster doesn't exist, deploy infrastructure first
# Go to GitHub Actions → Run "Deploy Platform Infra" workflow
```

### Issue 2: Pods Stuck in "ImagePullBackOff"

**Symptoms:**
- Pods can't pull images from Artifact Registry
- Error: "failed to authorize: failed to fetch anonymous token"

**Fix:**
This usually means the GAR configuration secrets are missing or incorrect.

```powershell
# Check if secrets exist
kubectl get secret shipzen-gar-config -n shipzen-system
kubectl get secret shipzen-gar-config -n shipzen-build

# If missing, re-run terraform apply
cd terraform
terraform apply -auto-approve
```

### Issue 3: External Secrets Not Syncing

**Symptoms:**
- ExternalSecret resources show "SecretSyncedError"
- Pods can't find required secrets

**Fix:**
```powershell
# Check ClusterSecretStore
kubectl get clustersecretstore gcp-secret-manager

# Check ESO pod logs
kubectl logs -n external-secrets deployment/external-secrets

# Verify secrets exist in GCP Secret Manager
gcloud secrets list | findstr shipzen

# If secrets are missing, push them via GitHub Actions
# Go to GitHub Actions → Run "Deploy Secrets" workflow
```

### Issue 4: Database Connection Errors

**Symptoms:**
- API/Controller/Worker pods crash with "could not connect to database"
- Error: "FATAL: password authentication failed"

**Fix:**
```powershell
# Check if PostgreSQL is running
kubectl get pods -n shipzen-system -l app.kubernetes.io/name=postgresql

# Check if database secret exists
kubectl get secret shipzen-db-credentials -n shipzen-system

# View database URL (base64 encoded)
kubectl get secret shipzen-db-credentials -n shipzen-system -o jsonpath='{.data.url}' | base64 -d

# If PostgreSQL pod is not running, check helm release
kubectl get helmrelease postgres -n shipzen-system
```

### Issue 5: ArgoCD Application Not Syncing

**Symptoms:**
- ArgoCD shows "OutOfSync" or "Unknown" status
- Infrastructure changes not applying

**Fix:**
```powershell
# Check ArgoCD application status
kubectl get applications -n argocd

# Force manual sync
kubectl patch application shipzen-platform -n argocd -p '{"operation":{"sync":{"revision":"HEAD"}}}' --type=merge

# Check ArgoCD server logs
kubectl logs -n argocd deployment/argocd-server

# Access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Then open https://localhost:8080
# Username: admin
# Password: kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d
```

## 🛠️ Useful Commands

### Check Overall System Health
```powershell
# Run comprehensive verification
.\scripts\verify-deployment.ps1 -ProjectId YOUR_PROJECT_ID

# Quick pod status check
kubectl get pods -A | findstr -v Running | findstr -v Completed

# Check for events/errors
kubectl get events -A --sort-by='.lastTimestamp' | Select-Object -Last 20
```

### View Logs
```powershell
# API logs
kubectl logs -n shipzen-system deployment/shipzen-api --tail=100 -f

# Controller logs
kubectl logs -n shipzen-system deployment/shipzen-controller --tail=100 -f

# Worker logs
kubectl logs -n shipzen-system deployment/shipzen-worker --tail=100 -f

# Builder logs (if builds are running)
kubectl logs -n shipzen-build -l app=shipzen-builder --tail=100 -f
```

### Access Services
```powershell
# Get LoadBalancer IP
kubectl get svc -A | findstr LoadBalancer

# Port forward to API locally
kubectl port-forward -n shipzen-system svc/shipzen-api 8000:8000

# Port forward to Grafana
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

### Debug Networking
```powershell
# Check Gateway status
kubectl get gateway -A

# Check HTTPRoutes
kubectl get httproute -A

# Check if Envoy Gateway is running
kubectl get pods -n envoy-gateway-system

# Test DNS resolution from within cluster
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup redis-master.shipzen-system.svc.cluster.local
```

### Reset/Clean Up
```powershell
# Delete a specific namespace (e.g., a stuck tenant)
kubectl delete namespace TENANT_NAMESPACE

# Restart a deployment
kubectl rollout restart deployment/shipzen-api -n shipzen-system

# Delete and recreate a pod
kubectl delete pod POD_NAME -n NAMESPACE
```

## 📋 Pre-Flight Checklist

Before deploying or debugging, verify:

- [ ] gcloud CLI installed and authenticated
- [ ] kubectl installed (comes with gcloud)
- [ ] Project ID set correctly: `gcloud config get-value project`
- [ ] GitHub secrets configured (see GCP_SETUP_GUIDE.md)
- [ ] Terraform Cloud workspace configured
- [ ] GCP APIs enabled (Compute, Container, Artifact Registry, Secret Manager, etc.)

## 🔄 Typical Deployment Flow

1. **Initial Setup** (once)
   ```powershell
   # Install gcloud CLI
   # Authenticate and set project
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   
   # Configure GitHub secrets (via GitHub UI)
   # Set up Terraform Cloud workspace
   ```

2. **Deploy Infrastructure** (via GitHub Actions)
   - Push changes to `terraform/` directory, or
   - Manually trigger "Deploy Platform Infra" workflow
   - Wait ~15-20 minutes for completion

3. **Verify Cluster Access**
   ```powershell
   .\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID
   ```

4. **Build and Push Images** (via GitHub Actions)
   - Push changes to `api/`, `controller/`, `worker/`, or `ui/` directories, or
   - Manually trigger "Build and Push Docker Images" workflow

5. **Verify Deployment**
   ```powershell
   .\scripts\verify-deployment.ps1 -ProjectId YOUR_PROJECT_ID
   ```

6. **Access the Platform**
   - Get LoadBalancer IP: `kubectl get svc -A | findstr LoadBalancer`
   - Update DNS (Cloudflare) to point to the IP
   - Access via `https://shipzen.jeneeldumasia.codes`

## 🆘 Still Having Issues?

1. **Check GitHub Actions logs** - Most deployment errors show up here first
2. **Run verify-deployment.ps1** - Get a comprehensive health report
3. **Check ArgoCD UI** - See which resources are failing to sync
4. **Review Terraform state** - Ensure infrastructure is provisioned correctly
5. **Check GCP Console** - Verify GKE cluster, Artifact Registry, and Secret Manager

## 📚 Additional Resources

- [GCP Setup Guide](docs/GCP_SETUP_GUIDE.md) - Detailed setup instructions
- [Architecture Documentation](docs/architecture/) - System design and diagrams
- [ADRs](docs/adr/) - Architecture Decision Records
- [Issues and Resolutions](docs/ISSUES_AND_RESOLUTIONS.md) - Historical troubleshooting guide
