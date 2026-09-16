# Terraform Destroy and Recreate Guide

## Current Situation

Your GKE cluster is in **ERROR** state due to:
- **GCE_STOCKOUT**: No `e2-medium` capacity in `us-central1-f`
- **Wrong machine type**: Cluster has `e2-medium`, terraform wants `e2-standard-4` (now)
- **Expiring soon**: 13 days until automatic deletion

## Cost Optimization Applied

Changed default machine type from **`n2-standard-8`** to **`e2-standard-4`**:

| Machine Type | vCPUs | RAM | Cost/Node/Month | Total (3 nodes) | Savings |
|--------------|-------|-----|-----------------|-----------------|---------|
| n2-standard-8 (old) | 8 | 32 GB | $242 | $726 | - |
| **e2-standard-4 (new)** | **4** | **16 GB** | **$100** | **$300** | **$426/month** |

You can override this when applying:
```bash
terraform apply -var="platform_machine_type=e2-standard-2"  # Even cheaper
```

## Step-by-Step: Destroy and Recreate via Terraform

### Prerequisites

1. **Set up gcloud in your session:**
```powershell
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"
```

2. **Authenticate to GCP:**
```powershell
gcloud auth login
gcloud auth application-default login  # For terraform
```

3. **Set your project:**
```powershell
gcloud config set project project-ce3f7c39-eceb-4221-a76
```

### Step 1: Backup Important Data (if any)

If you have any important data in the cluster:

```powershell
# Backup any ConfigMaps or Secrets you need
kubectl get configmap -A -o yaml > backup-configmaps.yaml
kubectl get secret -A -o yaml > backup-secrets.yaml

# Export ArgoCD applications
kubectl get applications -n argocd -o yaml > backup-argocd-apps.yaml
```

### Step 2: Navigate to Terraform Directory

```powershell
cd c:\Project\ShipZen-GCP\terraform
```

### Step 3: Initialize Terraform (if not done)

```powershell
terraform init
```

This should connect to your Terraform Cloud workspace: `ShipZen-GCP`

### Step 4: Target Destroy the Cluster Only (Recommended)

Instead of destroying everything, target just the broken cluster:

```powershell
# Destroy just the cluster and node pool
terraform destroy `
  -target=google_container_cluster.primary `
  -target=google_container_node_pool.platform_nodes `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"
```

**Confirm with `yes` when prompted.**

This preserves:
- ✅ VPC and networking
- ✅ Artifact Registry repositories
- ✅ GCS buckets
- ✅ Secret Manager secrets
- ✅ Cloud SQL (if using)

### Step 5: Recreate the Cluster

```powershell
terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"
```

**What this will create:**
- New GKE cluster with `e2-standard-4` nodes
- 3 nodes (1 per zone: us-central1-a, b, c)
- All operators: KEDA, ESO, Envoy Gateway, ArgoCD
- ClusterSecretStore for GCP Secret Manager
- Kubernetes secrets for DB, Redis, GAR, GCS

**Time estimate:** 15-20 minutes

### Step 6: Get Cluster Credentials

```powershell
gcloud container clusters get-credentials shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76
```

### Step 7: Verify Everything Works

```powershell
cd ..
.\scripts\verify-deployment.ps1 -ProjectId project-ce3f7c39-eceb-4221-a76
```

### Step 8: Check ArgoCD Sync

```powershell
kubectl get applications -n argocd
kubectl get pods -A
```

ArgoCD should automatically sync and deploy your platform services.

## Alternative: Full Destroy (Nuclear Option)

If you want to start completely fresh:

```powershell
# Destroy EVERYTHING
terraform destroy `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"

# Recreate EVERYTHING
terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1"
```

⚠️ **This will delete:**
- GKE Cluster
- Artifact Registry repositories (and all images!)
- GCS buckets (and all build logs!)
- VPC networking
- Everything

## Customizing Machine Type

You can override the machine type at apply time:

```powershell
# Use budget option (2 vCPUs, 8GB RAM)
terraform apply -var="platform_machine_type=e2-standard-2"

# Use performance option (4 vCPUs, 16GB RAM, better CPU)
terraform apply -var="platform_machine_type=n2-standard-4"

# Use high-end option (8 vCPUs, 32GB RAM) - NOT RECOMMENDED
terraform apply -var="platform_machine_type=n2-standard-8"
```

## Troubleshooting

### Issue: Terraform can't find cluster to destroy

If terraform can't find the cluster because it's in ERROR state:

```powershell
# Manually delete via gcloud
gcloud container clusters delete shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76 `
  --quiet

# Then run terraform apply (it will create new cluster)
terraform apply
```

### Issue: "Cluster already exists" error

```powershell
# Import existing cluster into terraform state
terraform import google_container_cluster.primary `
  projects/project-ce3f7c39-eceb-4221-a76/locations/us-central1/clusters/shipzen-cluster
```

### Issue: Terraform state is broken

```powershell
# Remove cluster from state
terraform state rm google_container_cluster.primary
terraform state rm google_container_node_pool.platform_nodes

# Then run apply
terraform apply
```

## Cost Monitoring

After recreation, monitor costs:

```powershell
# Check running nodes
kubectl get nodes

# Check machine types
gcloud container clusters describe shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76 `
  --format="value(nodePools[0].config.machineType)"
```

## Post-Recreation Checklist

- [ ] Cluster is RUNNING
- [ ] All 3 nodes are healthy
- [ ] Machine type is correct (e2-standard-4)
- [ ] ArgoCD is installed and syncing
- [ ] All platform pods are Running
- [ ] External Secrets are syncing
- [ ] Load Balancer has external IP
- [ ] Can access services

## Summary of Changes

**Files Modified:**
- `terraform/main.tf` - Updated node pool with cost optimizations
- `terraform/variables.tf` - Changed default from n2-standard-8 to e2-standard-4

**Cost Savings:**
- **Before:** ~$726/month (3x n2-standard-8)
- **After:** ~$300/month (3x e2-standard-4)
- **Savings:** ~$426/month (59% reduction)

**No data loss because:**
- Artifact Registry repositories preserved
- GCS buckets preserved
- Secrets in Secret Manager preserved
- Only the cluster itself is recreated
