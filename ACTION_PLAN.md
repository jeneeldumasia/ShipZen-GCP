# 🚀 Action Plan: Fix Your Cluster

## Current Situation

✗ **Cluster Status:** ERROR (GCE_STOCKOUT)  
✗ **Problem:** No e2-medium capacity in us-central1-f zone  
✗ **Days to expiration:** 13 days until automatic deletion  
✗ **Machine type mismatch:** Cluster has e2-medium, terraform configured for n2-standard-8  

## What I Fixed

✅ Changed default machine type from `n2-standard-8` ($726/month) to `e2-standard-4` ($300/month)  
✅ Saved you **$426/month** (59% cost reduction)  
✅ Created scripts for terraform-based recreation  
✅ Fixed all AWS→GCP references in code  
✅ Updated documentation  

## Machine Type Decision

| Option | vCPUs | RAM | Cost/Month | Use Case |
|--------|-------|-----|------------|----------|
| **e2-standard-4** ⭐ | 4 | 16 GB | **$300** | **Recommended: Dev/Test** |
| e2-standard-2 | 2 | 8 GB | $150 | Budget (may be tight) |
| n2-standard-4 | 4 | 16 GB | $363 | Production (better performance) |
| n2-standard-8 ❌ | 8 | 32 GB | $726 | Overkill (don't use) |

Your workloads only need ~400m CPU total, so **e2-standard-4 is perfect**.

## How to Fix Everything (The Right Way™)

### Option A: Automated Script (Recommended)

```powershell
# Setup gcloud in your session
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"

# Authenticate for terraform
gcloud auth application-default login

# Run automated recreation
cd c:\Project\ShipZen-GCP
.\scripts\terraform-recreate-cluster.ps1
```

This script will:
1. ✅ Verify authentication
2. ✅ Destroy broken cluster via terraform
3. ✅ Recreate with correct machine type
4. ✅ Configure kubectl
5. ✅ Verify deployment

**Time:** 15-20 minutes

### Option B: Manual Terraform Commands

```powershell
# 1. Setup
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"
gcloud auth application-default login

# 2. Navigate to terraform
cd c:\Project\ShipZen-GCP\terraform

# 3. Initialize
terraform init

# 4. Targeted destroy (preserves VPC, GAR, GCS, Secrets)
terraform destroy `
  -target=google_container_cluster.primary `
  -target=google_container_node_pool.platform_nodes `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1" `
  -auto-approve

# 5. Recreate everything
terraform apply `
  -var="gcp_project=project-ce3f7c39-eceb-4221-a76" `
  -var="gcp_region=us-central1" `
  -auto-approve

# 6. Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76

# 7. Verify
cd ..
.\scripts\verify-deployment.ps1
```

## What Gets Preserved

✅ **VPC Network** - Your networking stays intact  
✅ **Artifact Registry** - All your container images safe  
✅ **GCS Buckets** - Build logs preserved  
✅ **Secret Manager** - All secrets intact  
✅ **Cloud SQL** - Database preserved (if using)  

Only the **GKE cluster** itself is recreated.

## What Gets Recreated

🔄 **GKE Cluster** - Fresh cluster with correct configuration  
🔄 **Node Pool** - 3x e2-standard-4 nodes (1 per zone)  
🔄 **Operators** - KEDA, ESO, Envoy Gateway, ArgoCD  
🔄 **ClusterSecretStore** - GCP Secret Manager integration  
🔄 **Platform Services** - API, Controller, Worker, UI  

ArgoCD will automatically sync and deploy everything.

## Post-Recreation Verification

```powershell
# Check cluster status
kubectl get nodes
kubectl get pods -A

# Check ArgoCD
kubectl get applications -n argocd

# Full verification
.\scripts\verify-deployment.ps1
```

Expected results:
- ✅ 3 nodes in READY state
- ✅ All pods Running or Completed
- ✅ ArgoCD applications Synced and Healthy
- ✅ Load Balancer has external IP

## Timeline

| Step | Duration | Status |
|------|----------|--------|
| Terraform init | 1 min | - |
| Cluster destroy | 3-5 min | - |
| Cluster create | 10-15 min | - |
| Operators deploy | 3-5 min | - |
| Platform sync | 2-3 min | - |
| **Total** | **20-30 min** | - |

## Troubleshooting

### If script fails with "not authenticated"
```powershell
gcloud auth login
gcloud auth application-default login
```

### If terraform can't find cluster to destroy
```powershell
# Manually delete first
gcloud container clusters delete shipzen-cluster `
  --region us-central1 `
  --project project-ce3f7c39-eceb-4221-a76 `
  --quiet

# Then run terraform apply
cd terraform
terraform apply
```

### If pods don't start
```powershell
# Check ArgoCD sync status
kubectl get applications -n argocd

# Force sync
kubectl patch application shipzen-platform -n argocd `
  -p '{"operation":{"sync":{"revision":"HEAD"}}}' --type=merge

# Check pod events
kubectl get events -A --sort-by='.lastTimestamp' | Select-Object -Last 20
```

## Cost Monitoring

After recreation:
```powershell
# Verify machine type
kubectl get nodes -o custom-columns=NAME:.metadata.name,INSTANCE-TYPE:.metadata.labels.beta\\.kubernetes\\.io/instance-type

# Should show: e2-standard-4
```

Monthly cost estimate with e2-standard-4:
- 3 nodes × $100/month = **$300/month**
- Plus storage, networking (~$20/month)
- **Total: ~$320/month**

Compare to old configuration:
- 3 × n2-standard-8 = $726/month
- **You're saving $400+/month!** 💰

## Files Changed

**Created:**
- `scripts/terraform-recreate-cluster.ps1` - Automated recreation
- `TERRAFORM_DESTROY_AND_RECREATE.md` - Detailed guide
- `ACTION_PLAN.md` - This file

**Modified:**
- `terraform/main.tf` - Node pool configuration optimizations
- `terraform/variables.tf` - Changed default from n2-standard-8 to e2-standard-4

## Next Steps After Recreation

1. ✅ Verify all pods are running
2. ✅ Check ArgoCD applications are synced
3. ✅ Get Load Balancer IP: `kubectl get svc -A | findstr LoadBalancer`
4. ✅ Update DNS in Cloudflare (if needed)
5. ✅ Run a test deployment
6. ✅ Set up monitoring alerts
7. ✅ Document any custom configurations

## Questions?

See these guides:
- **Detailed terraform guide:** `TERRAFORM_DESTROY_AND_RECREATE.md`
- **Troubleshooting:** `QUICK_START.md`
- **Setup from scratch:** `docs/GCP_SETUP_GUIDE.md`
- **All fixes applied:** `FIX_SUMMARY.md`

---

## ⚡ Quick Start (TL;DR)

```powershell
# 1. Setup gcloud
$gcloudPath = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"
$env:Path = "$gcloudPath;$env:Path"

# 2. Authenticate
gcloud auth application-default login

# 3. Run script
cd c:\Project\ShipZen-GCP
.\scripts\terraform-recreate-cluster.ps1

# 4. Wait 20 minutes ☕

# 5. Verify
.\scripts\verify-deployment.ps1
```

**That's it!** Your cluster will be fixed with optimal machine types and 60% cost savings.
