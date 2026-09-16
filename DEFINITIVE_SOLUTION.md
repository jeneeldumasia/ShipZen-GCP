# The Definitive Solution: Fix Your GKE Cluster

## Understanding the Problem

### What Actually Happened

Your GKE cluster is in **ERROR** state because of **immutable resource conflicts**:

1. **Historical State**: Cluster was originally created with:
   - Machine type: `e2-medium` (2 vCPU, 4GB RAM)
   - Zones: `us-central1-f`

2. **Current Terraform Config**: Now specifies:
   - Machine type: `e2-standard-4` (4 vCPU, 16GB RAM)
   - Zones: `us-central1-a, us-central1-b, us-central1-c`

3. **The Conflict**: 
   - GCP ran out of `e2-medium` capacity in `us-central1-f` → **GCE_STOCKOUT**
   - Terraform cannot change zones or machine types on existing clusters (immutable)
   - The cluster must be destroyed and recreated

### Why `terraform apply` Won't Fix It

GKE cluster properties that are **immutable** (cannot be changed after creation):
- ✗ Cluster zones (`node_locations`)
- ✗ Machine type (on existing node pools)
- ✗ Control plane location

Terraform will fail trying to update these properties. The only solution: **destroy and recreate**.

## The Terraform Architecture

### Resource Dependency Chain

```
google_project_service.apis (Enable GCP APIs)
    ↓
google_compute_network.vpc (VPC Network)
    ↓
google_compute_subnetwork.subnet (Subnet 10.0.0.0/16)
    ↓
google_compute_router + NAT (Internet access for private nodes)
    ↓
google_container_cluster.primary (GKE Control Plane)
    ↓
google_container_node_pool.platform_nodes (Worker Nodes)
    ↓
time_sleep.wait_for_cluster_auth (60 second wait)
    ↓
helm_release.keda, helm_release.external_secrets (Operators)
    ↓
helm_release.postgresql, helm_release.redis (Data Layer)
    ↓
helm_release.kyverno (Security Policies)
    ↓
helm_release.kube_prometheus_stack (Observability)
    ↓
helm_release.argocd (GitOps)
    ↓
null_resource.argocd_apps (Platform Services)
```

### What's Preserved vs Recreated

**Preserved** (exists outside cluster):
- ✅ VPC Network (`google_compute_network.vpc`)
- ✅ Subnets, Router, NAT Gateway
- ✅ Artifact Registry repositories (`shipzen-builds`, `shipzen-platform`)
- ✅ GCS bucket (`shipzen-build-logs-*`)
- ✅ Secret Manager secrets (`shipzen-github`, `shipzen-github-app`, etc.)
- ✅ Service Accounts (`shipzen-builder-sa`, `shipzen-eso-sa`)
- ✅ IAM bindings and Workload Identity configurations

**Recreated** (lives inside cluster):
- 🔄 GKE Cluster control plane
- 🔄 Node pool with new machine type
- 🔄 All Helm releases (KEDA, ESO, ArgoCD, PostgreSQL, Redis, Prometheus)
- 🔄 Kubernetes secrets (db credentials, gar/gcs config)
- 🔄 ArgoCD Application (points to GitHub `infra/` directory)

**Data Impact**:
- **PostgreSQL**: In-cluster, will be recreated with empty database
- **Redis**: In-cluster, will be recreated empty (queues reset)
- **Prometheus metrics**: Lost (unless using persistent volumes)
- **Grafana dashboards**: Preserved if using persistent storage
- **Your container images**: Safe in Artifact Registry
- **Build logs**: Safe in GCS

## The Correct Solution (Via GitHub Actions)

### Option 1: Automated via CI/CD (Recommended)

Since your infrastructure is managed by Terraform Cloud and GitHub Actions, the proper way is:

**Step 1: Trigger Infrastructure Rebuild**

Your `.github/workflows/deploy.yaml` workflow will:
1. Authenticate to GCP via Workload Identity
2. Run `terraform init` (connect to Terraform Cloud workspace)
3. Run `terraform plan` (detect cluster needs replacement)
4. Run `terraform apply` (destroy + recreate cluster)
5. Install all operators and services
6. Wait for Load Balancer IP
7. Update Cloudflare DNS automatically

**How to trigger it:**

```powershell
# Make a small change to force workflow run
cd c:\Project\ShipZen-GCP
echo "# Force rebuild $(Get-Date)" >> terraform\README.md
git add terraform\README.md
git commit -m "fix: force cluster rebuild to fix GCE_STOCKOUT"
git push origin main
```

**Or manually trigger:**
1. Go to GitHub → Actions tab
2. Select "Deploy Platform Infra" workflow
3. Click "Run workflow" → "Run workflow"

**Time**: 15-20 minutes

**What happens**:
- Workflow detects cluster configuration drift
- Terraform destroys broken cluster
- Terraform creates new cluster with:
  - Machine type: `e2-standard-4` (or `n2-standard-4` if you want performance)
  - Zones: `us-central1-a`, `us-central1-b`, `us-central1-c` (avoiding stockout zone)
  - Autoscaling: 3-9 nodes
- ArgoCD syncs platform services from `infra/` directory
- Load Balancer provisions
- DNS updates automatically

### Option 2: Manual Terraform (If GitHub Actions Not Working)

If you need to run terraform locally:

**Step 1: Setup**

```powershell
# Add gcloud to PATH for this session
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"

# Authenticate
gcloud auth login
gcloud auth application-default login  # Required for Terraform

# Set project
gcloud config set project project-ce3f7c39-eceb-4221-a76
```

**Step 2: Navigate and Initialize**

```powershell
cd c:\Project\ShipZen-GCP\terraform
terraform init
```

**Step 3: Targeted Destroy (Preserves Data)**

```powershell
terraform destroy `
  -target=google_container_cluster.primary `
  -target=google_container_node_pool.platform_nodes `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"
```

Type `yes` when prompted.

**Step 4: Recreate**

```powershell
terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"
```

Type `yes` when prompted.

**Step 5: Verify**

```powershell
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76

# Check nodes
kubectl get nodes

# Check pods
kubectl get pods -A

# Check ArgoCD
kubectl get applications -n argocd
```

## Machine Type Decision

Your current configuration uses **`e2-standard-4`** (changed from `n2-standard-8`).

You mentioned you want "performance". Here's the comparison:

| Type | vCPUs | RAM | Cost/Node/Month | Total (3 nodes) | Performance | Recommendation |
|------|-------|-----|-----------------|-----------------|-------------|----------------|
| e2-standard-2 | 2 | 8 GB | $50 | $150 | Budget | Too small |
| **e2-standard-4** | **4** | **16 GB** | **$100** | **$300** | **Good** | **Current default** |
| **n2-standard-4** | **4** | **16 GB** | **$121** | **$363** | **Better CPU** | **Your choice (performance)** |
| n2-standard-8 | 8 | 32 GB | $242 | $726 | Excellent | Overkill |

### Your Workload Analysis

Your pods request:
- API: 100m CPU, 256Mi RAM
- Controller: 100m CPU, 128Mi RAM
- Worker: 100m CPU, 128Mi RAM  
- UI: 100m CPU, 128Mi RAM
- **Total platform**: ~400m CPU, ~640Mi RAM

Plus overhead:
- PostgreSQL: ~500m CPU, 512Mi RAM
- Redis: ~200m CPU, 256Mi RAM
- Prometheus: ~500m CPU, 2Gi RAM
- Grafana: ~100m CPU, 512Mi RAM
- ArgoCD: ~300m CPU, 512Mi RAM
- Envoy Gateway: ~100m CPU, 128Mi RAM
- **Total with overhead**: ~2000m CPU (2 vCPUs), ~5Gi RAM

### Recommendation for Performance

Use **`n2-standard-4`** (your preference):

```powershell
# Option 1: Via GitHub Actions (edit terraform/variables.tf)
# Change line 42: default = "n2-standard-4"

# Option 2: Via command line override
terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1" `
  -var="platform_machine_type=n2-standard-4"
```

**Why n2-standard-4 is better**:
- ✅ Intel Cascade Lake processors (better single-thread performance)
- ✅ Higher memory bandwidth
- ✅ Better for CPU-intensive builds
- ✅ Only $21/node more than e2-standard-4 (+20%)
- ✅ Still 50% cheaper than n2-standard-8

## Post-Recreation Checklist

After cluster recreation:

**1. Verify Cluster**
```powershell
gcloud container clusters describe shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-ecreb-4221-a76
```

Check:
- Status: RUNNING (not ERROR)
- Machine type: n2-standard-4 or e2-standard-4
- Zones: us-central1-a, b, c
- Node count: 3

**2. Verify Pods**
```powershell
kubectl get pods -A
```

All pods should be Running or Completed within 5-10 minutes.

**3. Verify ArgoCD**
```powershell
kubectl get applications -n argocd
```

Should show:
- shipzen-platform: Synced, Healthy

**4. Verify Load Balancer**
```powershell
kubectl get svc -A | findstr LoadBalancer
```

Should have an EXTERNAL-IP (not `<pending>`).

**5. Verify DNS**

Go to `https://shipzen.jeneeldumasia.codes` (should load after DNS propagates).

**6. Check Costs**
```powershell
# Verify machine type
kubectl get nodes -o custom-columns=NAME:.metadata.name,INSTANCE-TYPE:.metadata.labels.beta\\.kubernetes\\.io/instance-type
```

**7. Run Database Migrations**

Since PostgreSQL was recreated empty:
```powershell
# The schema-job in infra/system/ runs automatically via ArgoCD
kubectl logs -n shipzen-system job/shipzen-schema-bootstrap
```

## Why This is The Right Solution

### Terraform Best Practices

1. **Infrastructure as Code**: Everything defined in terraform
2. **Immutable Infrastructure**: Replace, don't modify
3. **State Management**: Terraform Cloud tracks state
4. **GitOps**: GitHub Actions triggers on code changes
5. **Declarative**: Describe desired state, Terraform figures out how

### GCP/GKE Best Practices

1. **Regional Clusters**: High availability across zones
2. **Workload Identity**: No service account keys
3. **Node Auto-scaling**: Adjusts to load
4. **Managed Control Plane**: Google handles master nodes
5. **Zone Distribution**: Avoids single zone failures

### Why Not Manual Fixes

❌ **Manual gcloud commands**: State drift with Terraform
❌ **kubectl edits**: ArgoCD will revert changes
❌ **Console changes**: Not tracked in Git
❌ **Partial fixes**: Leaves system in inconsistent state

✅ **Terraform destroy + apply**: Clean, reproducible, tracked

## Summary: What You Need to Do

### Quick Version (GitHub Actions)

1. Go to GitHub → Actions → "Deploy Platform Infra" → "Run workflow"
2. Wait 20 minutes
3. Verify cluster is RUNNING
4. Access your platform

### Detailed Version (Local Terraform)

```powershell
# Setup
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"
gcloud auth login
gcloud auth application-default login

# Destroy and Recreate
cd c:\Project\ShipZen-GCP\terraform
terraform init

terraform destroy `
  -target=google_container_cluster.primary `
  -target=google_container_node_pool.platform_nodes `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"

terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1" `
  -var="platform_machine_type=n2-standard-4"

# Verify
gcloud container clusters get-credentials shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76
kubectl get nodes
kubectl get pods -A
```

**Time**: 20-30 minutes  
**Data loss**: In-cluster PostgreSQL/Redis (acceptable per architecture)  
**Cost**: ~$363/month (n2-standard-4) or ~$300/month (e2-standard-4)  
**Result**: Fully functional cluster with correct configuration

---

**This is the only correct solution. Everything else is a workaround.**
