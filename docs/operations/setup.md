# Setting up ShipZen from scratch

Do this once per GCP project. Afterwards everything runs from GitHub Actions
([runbook.md](runbook.md)).

## You need

- A GCP project with billing already active (this repo never changes billing settings)
- A Cloudflare zone for your domain, plus an API token with **Zone → DNS → Edit**
- An HCP Terraform organization (free tier is fine)
- A GitHub **OAuth App** (user sign-in) and a GitHub **App** (ShipZen's access to the `shipzen-tenants` repo, plus webhooks)
- `gcloud` installed locally (Windows: `scripts/setup-gcloud.ps1`)

## 1. Enable the APIs

```bash
gcloud services enable compute.googleapis.com container.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com sqladmin.googleapis.com \
  servicenetworking.googleapis.com cloudresourcemanager.googleapis.com iamcredentials.googleapis.com \
  --project <project>
```

Terraform enables the rest itself (`google_project_service.apis`).

## 2. Let GitHub Actions into GCP (no keys)

1. **IAM → Workload Identity Federation → Create pool** `github-actions-pool`, with an OIDC provider `github`:
   - issuer `https://token.actions.githubusercontent.com`
   - attribute mapping `google.subject = assertion.sub`, `attribute.repository = assertion.repository`
   - condition `assertion.repository == "jeneeldumasia/ShipZen-GCP"`
2. Create the service account `shipzen-github-actions` with these roles:
   - Compute Admin
   - Kubernetes Engine Admin
   - Service Account Admin
   - Project IAM Admin
   - Secret Manager Admin
   - Cloud SQL Admin
   - Artifact Registry Administrator
   - Storage Admin
   - Service Usage Admin
3. On the pool, **Grant access** to that service account for the repository.
4. Copy the provider's full resource name (`projects/<number>/locations/global/workloadIdentityPools/github-actions-pool/providers/github`).

If you ever rename the repository, update the condition, or every workflow fails
to authenticate.

## 3. HCP Terraform

Organization `jeneel-shipzen`, workspace `ShipZen-GCP`, **Execution mode: Local**.
Terraform runs on the GitHub runner, which has the GCP credentials. In remote mode
it fails with "no valid credentials". Create a team API token for `TF_API_TOKEN`.

## 4. GitHub repository secrets

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | The project ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | The provider resource name from step 2 |
| `GCP_SERVICE_ACCOUNT` | `shipzen-github-actions@<project>.iam.gserviceaccount.com` |
| `TF_API_TOKEN` | HCP Terraform team token |
| `CLOUDFLARE_API_TOKEN` | Cloudflare token (DNS edit) |
| `PG_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_PASSWORD` | Strong random values |
| `SHIPZEN_OAUTH_CLIENT_ID`, `SHIPZEN_OAUTH_CLIENT_SECRET` | GitHub OAuth App |
| `SHIPZEN_GITHUB_APP_ID`, `SHIPZEN_APP_INSTALLATION_ID`, `SHIPZEN_GITHUB_APP_PRIVATE_KEY`, `SHIPZEN_GITHUB_APP_WEBHOOK_SECRET` | GitHub App (`scripts/get-github-app-installation-id.sh` finds the installation ID) |
| `SHIPZEN_AUTH_SECRET` | Random string for NextAuth sessions |
| `ARGOCD_ADMIN_PASSWORD` | Optional; otherwise ArgoCD generates one |

The OAuth App's callback URL is `https://shipzen.<domain>/api/auth/callback/github`.

## 5. Who may use it

Set the allowlist and admins in `infra/api/deployment.yaml` and
`infra/ui/deployment.yaml`: `ALLOWED_GITHUB_USERS` and `ADMIN_GITHUB_USERS`
(comma-separated GitHub logins). Anyone else gets "Access denied".

## 6. First deploy

1. Run **Deploy Platform Infra** (15–25 min).
2. Run **Build and Push Docker Images**, unless a push to `main` already did.
3. Run **Cluster Report** and check that all four platform deployments show 2/2 ready.
4. Open `https://shipzen.<domain>`, sign in, and deploy a small app (see [../using-shipzen.md](../using-shipzen.md)).
5. Run **Security Check**.

## Local development

`docker compose -f docker-compose.local.yml up` starts Postgres, Redis, the API
(with local stub sign-in), a local registry and LocalStack in place of Secret
Manager. The controller and builds need a real cluster. Tests:

```bash
pip install -r api/requirements.txt -r worker/requirements.txt -r controller/requirements.txt pytest pytest-asyncio
pytest            # tests that need Docker or Postgres skip themselves
```
