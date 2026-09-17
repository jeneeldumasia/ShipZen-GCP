# Setup ArgoCD with GitHub App (Best Solution!)

You already have a GitHub App configured for ShipZen. Let's use it for ArgoCD too!

## Why GitHub App is Better:

✅ **Fine-grained permissions** - only what you specify
✅ **Organization-wide** - works across all repos
✅ **Revocable** - disable in one click
✅ **Auditable** - GitHub logs all access
✅ **Time-limited tokens** - ArgoCD refreshes automatically
✅ **No SSH keys to manage**

## Quick Setup (2 commands, 1 minute)

```bash
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster \
  --region us-central1 \
  --project project-ce3f7c39-eceb-4221-a76

# Create ArgoCD GitHub App credentials secret
# Replace with your actual GitHub App ID and Private Key from GitHub Secrets
kubectl create secret generic github-app-creds -n argocd \
  --from-literal=githubAppID=YOUR_APP_ID \
  --from-literal=githubAppInstallationID=YOUR_INSTALLATION_ID \
  --from-literal=githubAppPrivateKey="$(echo 'YOUR_PRIVATE_KEY' | base64 -d)"

kubectl label secret github-app-creds -n argocd argocd.argoproj.io/secret-type=repository

# Trigger ArgoCD sync
kubectl patch application shipzen-platform -n argocd \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}' --type=merge
```

## Get Your Installation ID:

```bash
# Option 1: From GitHub API
curl -H "Authorization: Bearer YOUR_GITHUB_APP_JWT" \
  https://api.github.com/app/installations

# Option 2: From GitHub UI
# Go to: https://github.com/settings/installations
# Click on your app, the installation ID is in the URL
```

## Even Easier - Use Terraform!

I can automate this using the GitHub secrets you already have in GitHub Actions.
