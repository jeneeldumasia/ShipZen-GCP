# Runbook

Day-to-day operation of ShipZen. Everything runs from **GitHub Actions**, so you
rarely need `kubectl`. First-time setup is in [setup.md](setup.md).

## Workflows

| Workflow | When to run it | What it does |
|---|---|---|
| **Deploy Platform Infra** (`deploy.yaml`) | The cluster doesn't exist (after a teardown) | Terraform plan + apply for everything, pushes secrets, waits for the load balancer, points Cloudflare at it. 15–25 min. If platform pods then can't pull their images (the registry was destroyed with the rest), run **Build and Push**. |
| **Apply Infrastructure Changes** (`apply-only.yaml`) | You changed `terraform/` and the cluster exists | Adopts orphaned resources, applies, restarts api/worker/controller. |
| **Build and Push Docker Images** (`build-push.yaml`) | Automatic on pushes to `main` touching `api/ ui/ worker/ controller/ shipzen_common/`; skips (no cost) while the platform is torn down, so run it by hand after **Deploy Platform Infra** | Builds the four images as `sha-<commit>`, pins them in `infra/kustomization.yaml`, waits for the rollout and un-sticks ArgoCD if needed. |
| **Infra Teardown** (`destroy.yaml`) | You want the cluster gone | Puts ArgoCD in teardown mode, drains load balancers, removes webhooks and finalizers, deletes GKE network leftovers and Cloudflare records, `terraform destroy`, then deletes the cluster's orphaned disks. |
| **Destroy and Redeploy Cluster** (`destroy-and-deploy.yaml`) | A clean rebuild; type `DESTROY` to confirm | Destroy, orphaned-disk cleanup, apply, build images. |
| **Auto-Destroy (Deadman Switch)** (`auto-destroy.yaml`) | Automatic every hour | Once the cluster is 9 h old it triggers **Infra Teardown**, unless you were active in the last 60 min (successful ShipZen API/UI requests, your kubectl changes, or your pushes and workflow runs). Then it checks again next hour. At 12 h it tears down regardless. Override with repository variables `MAX_UPTIME_HOURS`, `IDLE_MINUTES` and `HARD_CAP_HOURS`. |
| **Cluster Report** (`cluster-report.yaml`) | Something looks wrong | Read-only. Posts deployments, pods, ArgoCD status, gateway IP and source ranges, PVC disks and orphaned disks, and warning events as annotations on the run. |
| **Security Check** (`security-check.yaml`) | After changing IAM or network policies, and after each rebuild | Proves the builder identity can push images and nothing else, and that tenant and build pods are network-isolated. |
| **Container Security Scan** (`security-scan.yaml`) | Before a release, or after changing a Dockerfile | Trivy scan; fails on HIGH/CRITICAL. |
| **Deploy Secrets to GKE** (`deploy-secrets.yaml`) | You rotated OAuth / GitHub App / auth secrets, or set up Telegram alerts or email | Pushes those GitHub secrets into Secret Manager (ESO picks them up), including `SHIPZEN_DATA_KEY` (create-only) and the Resend key, and sends a Telegram test message if configured. |
| **Set Up Email** (`setup-email.yaml`) | Once, after adding `RESEND_API_KEY`; safe to re-run | Registers the domain with Resend and writes its SPF/DKIM records to Cloudflare (they survive teardowns). Touches no cloud infrastructure. |
| **Tests** (`tests.yaml`) | Automatic on pull requests and pushes | `pytest`, including the Postgres-backed API contract tests. |
| **Deploy DevBox** (`deploy-devbox.yaml`) | You want the remote dev VM | See [devbox.md](devbox.md). |
| **Disable Deletion Protection** | Before destroying the cluster manually | Turns off GKE deletion protection through Terraform. |
| **Debug Cluster** (`debug.yaml`) | Ad-hoc | Dumps cluster state to the log. Prefer **Cluster Report**. |

The destroy workflows are the only ones that delete data. Nothing else touches
billing.

## Where things are

| What | URL / command |
|---|---|
| ShipZen | https://shipzen.jeneeldumasia.codes |
| ArgoCD | https://argocd.jeneeldumasia.codes (user `admin`) |
| Grafana | https://grafana-shipzen.jeneeldumasia.codes (user `admin`, password from the `GRAFANA_PASSWORD` secret) |
| kubectl | `gcloud container clusters get-credentials shipzen-cluster --zone us-central1-c --project <project>` |
| Tenant manifests | https://github.com/jeneeldumasia/shipzen-tenants |
| Terraform state | HCP Terraform, org `jeneel-shipzen`, workspace `ShipZen-GCP` |

The ArgoCD admin password is in the `argocd-initial-admin-secret` Secret in the
`argocd` namespace (or `ARGOCD_ADMIN_PASSWORD` if set). Don't commit it or put it
in docs.

## Common tasks

**Ship a code change.** Merge to `main`. **Build and Push** builds, pins the new
tag and waits for the rollout. Infrastructure workflows (deploy, apply, secrets,
devbox) never run on their own; only Build and Push (on commits) and
Auto-Destroy (on a schedule) start automatically.

**Change infrastructure.** Edit `terraform/`, merge, run **Apply Infrastructure
Changes**. Kubernetes-only changes under `infra/` need no workflow: ArgoCD syncs
them within about 3 minutes.

**Bring the platform back after a teardown.** Run **Deploy Platform Infra**.
Teardown deletes everything that bills while idle, Cloud SQL included, so a torn-down
platform costs $0. Projects, users and deployments survive anyway: **Infra Teardown**
first exports the database to `gs://<project>-shipzen-db-backups/latest.sql.gz` (a
bucket outside Terraform state, inside the GCS free tier), and **Deploy Platform
Infra** recreates Cloud SQL and imports that dump *before* the platform services
start. Zero idle cost comes first: if the export fails (after 3 tries), teardown
still deletes everything and sends an alert, and the next deploy restores the
previous successful backup, so changes since then are lost. Timestamped
copies are kept under `history/` for 30 days. Run teardown with **skip_db_backup**
only if you mean to lose the data. Then the controller re-creates every tenant
folder, and ArgoCD re-creates the apps.

**Restore an older backup.** Copy the dump you want over `latest.sql.gz`
(`gcloud storage cp gs://<project>-shipzen-db-backups/history/<file> gs://<project>-shipzen-db-backups/latest.sql.gz`)
before running Deploy Platform Infra.

**Get alerts on Telegram** (one-time, free). Full guide with troubleshooting:
[telegram-alerts.md](telegram-alerts.md). Short version:
1. In Telegram, open **@BotFather**, send `/newbot`, pick a name and a username ending in `bot`. It replies with a **bot token** (`123456789:AA...`). Treat it like a password.
2. Open your new bot and send it any message (a bot can't message you until you do).
3. Get your **chat ID**: open `https://api.telegram.org/bot<token>/getUpdates` in a browser (on your phone if your work network blocks Telegram) and copy `"chat":{"id": ...}`. It's a number.
4. In GitHub: repository → Settings → Secrets and variables → Actions, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
5. Run **Deploy Secrets to GKE**. It stores both in Secret Manager (`shipzen-telegram`) and sends you a test message. The in-cluster relay picks the change up within about 10 minutes, with no restart. Teardown alerts (failed backup, failed teardown) use the repository secrets directly, so they work from step 4 on, even while the platform is down.

To stop messages: see [telegram-alerts.md](telegram-alerts.md#change-or-stop-alerts). `shipzen-telegram` also holds the Resend key for deploy emails, so don't blank it by hand while emails are on.

**Send deploy emails** (one-time, free: Resend's free tier is 3,000 emails a month).
Users get an email when a deploy goes live, fails, an app goes down, or a preview
is ready. Emails go to their GitHub-verified address, and each user can turn them
off with the bell in the top bar.
1. Create a Resend account and an API key. Give it full access for the setup
   step; afterwards you can replace it with a sending-only key.
2. Add it as the repository secret `RESEND_API_KEY`.
3. Run **Set Up Email**. It registers `jeneeldumasia.codes` with Resend and adds
   the DNS records in Cloudflare. Verification takes a few minutes; Resend's
   dashboard shows when the domain is verified.
4. Run **Deploy Secrets to GKE**. It adds the key to `shipzen-telegram` as
   `resend_api_key`. It goes there rather than into a new secret because Secret
   Manager is free only up to 6 versions. The worker and controller read it
   through the `shipzen-notify` ExternalSecret.

Without a key nothing is sent, and nothing fails.

**PR preview deploys** need the GitHub App to deliver pull-request events. In the
App's settings, grant **Pull requests: Read & write** (write is only for the
preview comment). Subscribe to the **Pull request** event, then approve the new
permission on the installation.

**Run the platform as an admin.** Admin → System:
- **Session Cost:** what the running cluster costs per hour, a session total, and the
  time left before auto-destroy. These are node list prices, so the figure is an upper bound.
- **Platform Controls:**
  - publish an announcement banner (info / warning / critical) that every user sees;
  - pause all new deploys with a reason (a deploy freeze). Running apps and builds
    already started carry on.

Admin → Users:
- **Suspend** with an optional reason. The user is signed out within seconds, and
  their projects can't deploy. Their running apps keep serving.
- **Restore** undoes it.

Every action is in the audit log.

**Protect Grafana and ArgoCD with Cloudflare Access** (one-time, free). Both are
public hostnames behind only an admin password. `terraform/access.tf` puts a
Cloudflare login in front of them, letting through only the emails in the
`ADMIN_EMAILS` repository secret (each gets a one-time code by email):
1. Cloudflare dashboard → **Zero Trust**: pick a team name and the Free plan (a
   card may be asked for; Free doesn't charge).
2. Add the permission **Account → Access: Apps and Policies → Edit** to the API
   token in `CLOUDFLARE_API_TOKEN` (My Profile → API Tokens → edit).
3. Add the repository secret `CLOUDFLARE_ACCOUNT_ID` (Cloudflare dashboard → the
   zone → Overview → API → Account ID).
4. Next **Deploy Platform Infra** (or **Apply Infrastructure Changes**) creates the
   Access applications. Until step 3 is done, nothing changes.

**Encrypt secrets stored in Postgres** (one-time, optional). Per-project webhook
secrets are encrypted with `SHIPZEN_DATA_KEY` when it's set. Generate a key once:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
Add it as the repository secret `SHIPZEN_DATA_KEY`. The next **Deploy Platform
Infra** stores it in Secret Manager (`shipzen-data-key`), and only creates it once.
**Never change it.** It's what decrypts those values, including in database backups.
Without it, values are stored as before.

**Budget alert.** A Cloud Billing budget "ShipZen monthly (before credits)" of
₹2,000/month emails billing admins at 50%, 90% and 100%. It counts usage *before*
credits, so it still fires while credits pay the bill. It lives on the billing
account, not in Terraform, so teardowns don't remove it. Change it under Billing →
Budgets & alerts. It warns; it doesn't stop spending.

**Secrets keep one version.** Workflows write Secret Manager values through
`scripts/put-secret.sh`, which adds a version only when the value changed and destroys
older ones. Every non-destroyed version is billed (6 are free), so use the script
rather than `gcloud secrets versions add` by hand.

**Check for leaked disks.**
`scripts/cleanup-orphaned-disks.sh <project>` lists them; add `--delete` to remove
them (it refuses while the cluster exists). **Cluster Report** shows the same list.

## Troubleshooting

Start with **Cluster Report**, then the Grafana **Overview** page.

| Symptom | Likely cause | Fix |
|---|---|---|
| Apply fails with `Error 409: ... already exists` | A previous run created resources whose state never reached HCP Terraform | The adopt step imports them; rerun the apply. If one still fails, its import error is in the run's annotations. |
| Terraform says the state is locked | A cancelled run left the lock in HCP Terraform | Workspace → Settings → Locking → force unlock, then rerun. |
| Pods run an old image after a merge | The rollout didn't finish, or ArgoCD is stuck retrying an old sync | Rerun **Build and Push**; its rollout step terminates a stuck sync and starts a fresh one. |
| A deploy stays in Building | Builder Job failing or no node room | Build log in the UI; `kubectl get jobs,pods -n shipzen-build`; Grafana "Room to grow". |
| An app shows Offline | Crashing, wrong port, or out of memory | Grafana **Your app** → crashes and logs. The app must listen on `$PORT` on `0.0.0.0`. |
| Old namespaces keep coming back in ArgoCD | A tenant folder outlived its project | The controller removes ownerless folders about every 20 min; check its logs for "Orphan GC". |
| Every deploy gets 423 "Deploys are paused" | An admin turned on the deploy freeze | Admin → System → **Resume deploys** |
| A user gets 403 "Your ShipZen account is suspended" | An admin suspended them | Admin → Users → **Restore** |
| No preview for a pull request | The App lacks pull-request events/permission, the PR comes from a fork, the project already has 3 PRs with previews, or deploys are paused | API log: "Ignored pull request … from a fork" or "No preview for …" says which |
| No deploy emails | No `RESEND_API_KEY` in `shipzen-telegram`, domain not verified, or the user turned emails off | Worker/controller logs say "Resend refused an email" or "Could not send email"; rerun **Set Up Email** and **Deploy Secrets to GKE** |
| App page Logs or Metrics empty | Promtail or Prometheus not running yet, or the release just started | `kubectl get pods -n shipzen-system -l app.kubernetes.io/name=promtail` (Promtail must tolerate the tenant taint); give metrics a minute |
| Vanity URL 404 right after setting it | DNS and the route still propagating | The Vanity URL card shows **Setting up…** until the route is accepted; allow a few minutes |
| Everyone suddenly signed out / 401s | The user's GitHub token was revoked, or GitHub is down or rate-limiting | The API log says which (401 vs 503 with `Retry-After`). Sign in again for 401. |
| The site is down but pods are fine | Gateway or Cloudflare | Overview "Internet gateway" tile; Cloudflare DNS should point at the gateway IP. |
| Namespaces stuck Terminating during teardown | Finalizers on ArgoCD apps or webhooks | **Infra Teardown** already clears them; rerun it. |

Past incidents and what fixed them: [incidents.md](incidents.md).
