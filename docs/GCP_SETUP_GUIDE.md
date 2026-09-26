# ShipZen GCP Setup Guide

This guide outlines the exact steps required to set up the ShipZen infrastructure on a brand new GCP account.

## 1. GCP Account Creation & Security
1. Create a new GCP account at [cloud.google.com](https://cloud.google.com/).
2. Create a new **GCP Project** (e.g., `shipzen-gcp`).
3. Enable **2-Factor Authentication** for your Google account.
4. Navigate to the **Billing Console** and activate your $300 free tier credits (if applicable).

## 2. Configure GitHub Actions Access (Workload Identity Federation)
To allow GitHub Actions to safely deploy your infrastructure without using static service account keys, you need to set up Workload Identity Federation.

1. In the GCP Console, go to **IAM & Admin** -> **Workload Identity Federation** -> **Create Pool**.
2. **Pool name:** `github-actions-pool`
3. **Pool ID:** `github-actions-pool`
4. Click **Continue**.
5. **Select provider:** OpenID Connect (OIDC)
6. **Provider name:** `github`
7. **Issuer URL:** `https://token.actions.githubusercontent.com`
8. **Audience:** `Default audience` (leave default)
9. Click **Continue** and then **Save**.

## 3. Create the Deployment Service Account
1. Go to **IAM & Admin** -> **Service Accounts** -> **Create Service Account**.
2. **Service account name:** `shipzen-github-actions`
3. **Service account ID:** `shipzen-github-actions` (auto-populated)
4. Click **Create and Continue**.
5. **Grant roles:**
   - Compute Admin
   - Kubernetes Engine Admin
   - Service Account Admin
   - Secret Manager Admin
   - Cloud SQL Admin
   - Artifact Registry Administrator
   - Storage Admin
   - Service Usage Admin
6. Click **Continue**, then **Done**.
7. Go back to **Workload Identity Federation** -> Select your pool -> **Grant Access**.
8. Select your service account (`shipzen-github-actions`).
9. **Attribute mappings:**
   - `google.subject` = `assertion.sub`
   - `attribute.repository` = `assertion.repository`
10. **Attribute conditions:** 
    ```
    assertion.repository == "jeneeldumasia/ShipZen"
    ```
11. Click **Save**.
12. Copy the **Workload Identity Provider** resource name (looks like `projects/PROJECT_NUM/locations/global/workloadIdentityPools/github-actions-pool/providers/github`).

## 4. Update GitHub Secrets
1. Go to your ShipZen repository on GitHub -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Add/Update the following secrets:
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`: The Workload Identity Provider resource name from step 3
   - `GCP_SERVICE_ACCOUNT`: `shipzen-github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com`
   - `GCP_PROJECT_ID`: Your GCP project ID (e.g., `shipzen-gcp`)
   - `CLOUDFLARE_API_TOKEN`: Your Cloudflare API token with Zone:DNS:Edit permissions
   - `PG_PASSWORD`: PostgreSQL password
   - `GRAFANA_PASSWORD`: Grafana admin password
   - `TF_API_TOKEN`: Terraform Cloud API token
   - `SHIPZEN_OAUTH_CLIENT_ID`: GitHub OAuth App Client ID
   - `SHIPZEN_OAUTH_CLIENT_SGARET`: GitHub OAuth App Client Secret
   - `SHIPZEN_GITHUB_APP_ID`: GitHub App ID
   - `SHIPZEN_GITHUB_APP_PRIVATE_KEY`: GitHub App Private Key (PEM format)
   - `SHIPZEN_GITHUB_APP_WEBHOOK_SGARET`: GitHub App Webhook Secret
   - `SHIPZEN_AUTH_SGARET`: Random secret for session authentication

## 5. Set up Terraform Cloud Workspace
1. Log into [Terraform Cloud](https://app.terraform.io/).
2. Go to your organization (`jeneel-shipzen`).
3. Create a new workspace named `ShipZen-GCP` (or use existing).
4. Go to workspace **Settings** -> **General**.
5. Ensure **Execution Mode** is set to **Local** (so Terraform runs on GitHub Actions runner, not HCP servers).
6. Go to **Settings** -> **Variables** and add any required workspace variables (if applicable).
7. Generate a **Team API Token** from your organization settings if you haven't already, and ensure it's set as the `TF_API_TOKEN` GitHub secret. 

## 6. Enable Required GCP APIs
Before running Terraform, ensure all required APIs are enabled:
```bash
gcloud services enable compute.googleapis.com
gcloud services enable container.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable redis.googleapis.com
gcloud services enable iamcredentials.googleapis.com
```

## 7. Deployment Sequence
1. Go to the GitHub Actions tab in your repository.
2. Run the **Deploy Platform Infra** workflow. This takes ~15-20 minutes to provision:
   - VPC Network and Cloud NAT
   - GKE Cluster with Workload Identity
   - Artifact Registry repositories
   - GCS bucket for build logs
   - KEDA, External Secrets Operator, Envoy Gateway
   - ArgoCD with platform manifests
3. Once successful, run the **Build and Push Docker Images** workflow to build your containers and push them to Artifact Registry.
4. ArgoCD will automatically sync and deploy your platform services from the `infra/` directory.

## 8. Post-Deployment Checks
Run the following commands to verify your cluster is accessible:

```bash
# Install gcloud CLI if not already installed
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Connect to your cluster
gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project YOUR_PROJECT_ID

# Verify nodes
kubectl get nodes

# Verify pods
kubectl get pods -A

# Check ArgoCD applications
kubectl get applications -n argocd

# Get Load Balancer IP
kubectl get svc -A | grep LoadBalancer
```

- Verify DNS routing in Cloudflare points to the new GCP Load Balancer IP address.
- Access Grafana at `https://shipzen.jeneeldumasia.codes` (or your configured domain).
