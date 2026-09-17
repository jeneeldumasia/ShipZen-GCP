# Setup ArgoCD with SSH Deploy Key (No PAT Required!)

This is the company-approved way - uses SSH deploy keys instead of Personal Access Tokens.

## Step 1: Generate SSH Key Pair (30 seconds)

```bash
# In Cloud Shell or your terminal
ssh-keygen -t ed25519 -C "argocd-shipzen" -f argocd-deploy-key -N ""

# This creates two files:
# - argocd-deploy-key (private key - keep secret!)
# - argocd-deploy-key.pub (public key - add to GitHub)
```

## Step 2: Add Public Key to GitHub (1 minute)

1. Copy the public key:
   ```bash
   cat argocd-deploy-key.pub
   ```

2. Go to: https://github.com/jeneeldumasia/ShipZen-GCP/settings/keys

3. Click **Add deploy key**

4. Title: `ArgoCD Read Access`

5. Paste the public key

6. **Leave "Allow write access" UNCHECKED** (read-only is safer)

7. Click **Add key**

## Step 3: Add Private Key to Kubernetes (1 minute)

```bash
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster \
  --region us-central1 \
  --project project-ce3f7c39-eceb-4221-a76

# Create ArgoCD repository credentials secret with SSH
kubectl create secret generic repo-shipzen-gcp -n argocd \
  --from-literal=type=git \
  --from-literal=url=git@github.com:jeneeldumasia/ShipZen-GCP.git \
  --from-file=sshPrivateKey=argocd-deploy-key

# Label it so ArgoCD recognizes it
kubectl label secret repo-shipzen-gcp -n argocd \
  argocd.argoproj.io/secret-type=repository
```

## Step 4: Update ArgoCD Application to Use SSH (1 minute)

```bash
# Update the application to use SSH URL instead of HTTPS
kubectl patch application shipzen-platform -n argocd --type=json -p='[
  {
    "op": "replace",
    "path": "/spec/source/repoURL",
    "value": "git@github.com:jeneeldumasia/ShipZen-GCP.git"
  }
]'

# Trigger sync
kubectl patch application shipzen-platform -n argocd \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}' --type=merge
```

## Step 5: Wait for Sync (2-3 minutes)

```bash
# Watch ArgoCD sync the application
kubectl get application shipzen-platform -n argocd -w

# Should show: Synced, Healthy
```

## Step 6: Verify LoadBalancer (2-3 minutes)

```bash
# Wait for LoadBalancer to get external IP
kubectl get svc -A | grep LoadBalancer

# Should show an EXTERNAL-IP
```

## Why This is Better Than PAT:

✅ **Repository-specific** - only works for ShipZen-GCP  
✅ **Read-only** - can't modify code  
✅ **Revocable** - delete deploy key anytime from GitHub settings  
✅ **No expiration** - works forever unless revoked  
✅ **Company-approved** - standard practice for automation  
✅ **More secure** - private key never leaves the cluster  

## Cleanup

After adding to Kubernetes, delete the local key files:
```bash
rm argocd-deploy-key argocd-deploy-key.pub
```

The key is now only in:
1. Kubernetes secret (private key)
2. GitHub deploy keys (public key)

## Total Time: ~5 minutes

Much better than dealing with PATs!
