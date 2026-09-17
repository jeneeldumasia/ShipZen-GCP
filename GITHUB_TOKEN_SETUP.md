# GitHub Token Setup for Private Repository Access

ArgoCD needs to access the private `ShipZen-GCP` repository. Follow these steps to set it up:

## Step 1: Create GitHub Personal Access Token (Classic)

1. Go to: https://github.com/settings/tokens
2. Click **Generate new token** → **Generate new token (classic)**
3. Give it a name: `ArgoCD ShipZen-GCP`
4. Select scopes:
   - ✅ **repo** (Full control of private repositories)
5. Click **Generate token**
6. **Copy the token immediately** (you won't see it again!)

## Step 2: Add Token to GitHub Repository Secrets

1. Go to: https://github.com/jeneeldumasia/ShipZen-GCP/settings/secrets/actions
2. Click **New repository secret**
3. Name: `GITHUB_TOKEN`
4. Value: Paste the token from Step 1
5. Click **Add secret**

## Step 3: Rebuild Cluster with New Configuration

The cluster needs to be destroyed and recreated because:
- Zone configuration changed (3 zones → 1 zone)
- PersistentVolumes are stuck in old zones
- ArgoCD needs the GitHub token to access private repo

### Run the Destroy and Redeploy Workflow:

1. Go to: https://github.com/jeneeldumasia/ShipZen-GCP/actions/workflows/destroy-and-deploy.yaml
2. Click **Run workflow**
3. Type `DESTROY` in the confirmation field
4. Click **Run workflow**

### What This Does:

1. **Destroys existing cluster** (~5 minutes)
   - Deletes all GKE resources
   - Removes old PersistentVolumes
   - Cleans up networking

2. **Recreates cluster** (~20 minutes)
   - Single zone: `us-central1-a`
   - Machine type: `e2-standard-4` (or `n2-standard-4` if you changed it)
   - 1 node (can autoscale to 3)
   - ArgoCD configured with GitHub token
   - All services deployed

3. **Updates DNS** (automatic)
   - Cloudflare CNAME records updated
   - TLS certificates provisioned

### Timeline:
- Destroy: 5 minutes
- Recreate: 20 minutes
- **Total: 25-30 minutes**

### Cost After Rebuild:
- **Before:** 3 zones × e2-standard-4 = ~$300/month
- **After:** 1 zone × e2-standard-4 = ~$100/month
- **Savings:** $200/month (67% reduction!)

## Verification

After the workflow completes:

```bash
# Check cluster configuration
gcloud container clusters describe shipzen-cluster --region us-central1

# Verify single zone
gcloud container clusters describe shipzen-cluster --region us-central1 --format="get(locations)"
# Should show: [us-central1-a]

# Check node count
kubectl get nodes
# Should show: 1 node

# Verify ArgoCD sync
kubectl get application shipzen-platform -n argocd
# Should show: Synced, Healthy

# Check all pods
kubectl get pods -A
# All should be Running
```

## Troubleshooting

### If ArgoCD still shows "Repository not found":
1. Verify the token has `repo` scope
2. Check the token hasn't expired
3. Verify the secret is named exactly `GITHUB_TOKEN` in GitHub Secrets

### If cluster destruction fails:
The workflow has safety checks. If destruction fails, you can manually destroy:
```bash
gcloud container clusters delete shipzen-cluster --region us-central1 --quiet
```
Then re-run the workflow.

## Security Notes

- The GitHub token is stored as an encrypted secret in GitHub Actions
- It's never exposed in logs or outputs
- It's only used by terraform to configure ArgoCD
- ArgoCD stores it in a Kubernetes secret in the `argocd` namespace
