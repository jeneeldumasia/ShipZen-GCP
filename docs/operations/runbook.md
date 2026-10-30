# Runbook

Day-to-day operation of ShipZen. Everything runs from **GitHub Actions**, so you
rarely need `kubectl`. First-time setup is in [setup.md](setup.md).

## Workflows

| Workflow | When to run it | What it does |
|---|---|---|
| **Deploy Platform Infra** (`deploy.yaml`) | The cluster doesn't exist (after a teardown) | Terraform plan + apply for everything, pushes secrets, waits for the load balancer, points Cloudflare at it. 15–25 min. If platform pods then can't pull their images (the registry was destroyed with the rest), run **Build and Push**. |
| **Apply Infrastructure Changes** (`apply-only.yaml`) | You changed `terraform/` and the cluster exists | Adopts orphaned resources, applies, restarts api/worker/controller. |
| **Build and Push Docker Images** (`build-push.yaml`) | Automatic on pushes touching `api/ ui/ worker/ controller/` | Builds the four images as `sha-<commit>`, pins them in `infra/kustomization.yaml`, waits for the rollout and un-sticks ArgoCD if needed. |
| **Infra Teardown** (`destroy.yaml`) | You want the cluster gone | Puts ArgoCD in teardown mode, drains load balancers, removes webhooks and finalizers, deletes GKE network leftovers and Cloudflare records, `terraform destroy`, then deletes the cluster's orphaned disks. |
| **Destroy and Redeploy Cluster** (`destroy-and-deploy.yaml`) | A clean rebuild; type `DESTROY` to confirm | Destroy, orphaned-disk cleanup, apply, build images. |
| **Auto-Destroy (Deadman Switch)** (`auto-destroy.yaml`) | Automatic every 3 h | If the cluster has been up 24 h, it triggers **Infra Teardown** to protect credits. |
| **Cluster Report** (`cluster-report.yaml`) | Something looks wrong | Read-only. Posts deployments, pods, ArgoCD status, gateway IP and source ranges, PVC disks and orphaned disks, and warning events as annotations on the run. |
| **Security Check** (`security-check.yaml`) | After changing IAM or network policies, and after each rebuild | Proves the builder identity can push images and nothing else, and that tenant and build pods are network-isolated. |
| **Container Security Scan** (`security-scan.yaml`) | Nightly, automatic | Trivy scan; fails on HIGH/CRITICAL. |
| **Deploy Secrets to GKE** (`deploy-secrets.yaml`) | You rotated OAuth / GitHub App / auth secrets, or set up WhatsApp | Pushes those GitHub secrets into Secret Manager (ESO picks them up) and sends a WhatsApp test message if configured. |
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
| kubectl | `gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project <project>` |
| Tenant manifests | https://github.com/jeneeldumasia/shipzen-tenants |
| Terraform state | HCP Terraform, org `jeneel-shipzen`, workspace `ShipZen-GCP` |

The ArgoCD admin password is in the `argocd-initial-admin-secret` Secret in the
`argocd` namespace (or `ARGOCD_ADMIN_PASSWORD` if set). Don't commit it or put it
in docs.

## Common tasks

**Ship a code change.** Merge to `main`. **Build and Push** builds, pins the new
tag and waits for the rollout. Nothing else to do.

**Change infrastructure.** Edit `terraform/`, merge, run **Apply Infrastructure
Changes**. Kubernetes-only changes under `infra/` need no workflow: ArgoCD syncs
them within about 3 minutes.

**Bring the platform back after Auto-Destroy.** Run **Deploy Platform Infra**.
Projects, users and deployments survive because Cloud SQL is outside the cluster.
The controller re-creates every tenant folder, and ArgoCD re-creates the apps.

**Get alerts on WhatsApp** (one-time):
1. Follow the WhatsApp steps at https://www.callmebot.com/blog/free-api-whatsapp-messages/: add CallMeBot's number (listed there) as a contact and send it `I allow callmebot to send me messages`. It replies with your API key.
2. In GitHub: repository → Settings → Secrets and variables → Actions, add `WHATSAPP_PHONE` (with country code, for example `+91…`) and `WHATSAPP_APIKEY`.
3. Run **Deploy Secrets to GKE**. It stores both in Secret Manager (`shipzen-whatsapp`) and sends you a test message. The relay picks the change up within about 10 minutes, with no restart.

To stop messages, store an empty value: `echo -n '{"phone": "", "apikey": ""}' | gcloud secrets versions add shipzen-whatsapp --data-file=-`.

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
| Everyone suddenly signed out / 401s | The user's GitHub token was revoked, or GitHub is down or rate-limiting | The API log says which (401 vs 503 with `Retry-After`). Sign in again for 401. |
| The site is down but pods are fine | Gateway or Cloudflare | Overview "Internet gateway" tile; Cloudflare DNS should point at the gateway IP. |
| Namespaces stuck Terminating during teardown | Finalizers on ArgoCD apps or webhooks | **Infra Teardown** already clears them; rerun it. |

Past incidents and what fixed them: [incidents.md](incidents.md).
