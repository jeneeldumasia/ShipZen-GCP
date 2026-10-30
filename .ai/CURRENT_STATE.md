# Current State: ShipZen-GCP

_Last updated: 2026-10-31. Treat the code as authoritative if this disagrees._

## Status
The platform is live and working end to end: GitHub sign-in, deploy, build logs,
rollback, restart, env vars, monitoring. The cluster is disposable: it is torn
down after 24 h of uptime and rebuilt with **Deploy Platform Infra**. Postgres is
Cloud SQL, so projects and deployments survive rebuilds.

## Infrastructure
| Resource | State |
|---|---|
| GKE `shipzen-cluster` | us-central1 control plane, nodes in us-central1-c, Workload Identity, **Dataplane V2 on clusters created after 2026-10-31** |
| Node pool `platform-nodes` | e2-standard-4, autoscale 1–3 |
| Cloud SQL `shipzen-postgres` | POSTGRES_15, db-f1-micro, private IP (`use_cloud_sql = true`) |
| Redis | Bitnami chart in `shipzen-system`, AOF on |
| Artifact Registry | `shipzen-platform` (platform images, `sha-<commit>`), `shipzen-builds` (user apps) |
| ArgoCD | `shipzen-platform` app syncs `infra/`; ApplicationSet syncs `shipzen-tenants` (private repo) |
| Gateway | Envoy Gateway; load balancer accepts Cloudflare IP ranges only |
| Monitoring | kube-prometheus-stack + Loki; 4 generated Grafana dashboards; alerts → WhatsApp relay |
| Terraform state | HCP Terraform, org `jeneel-shipzen`, workspace `ShipZen-GCP`, local execution |
| Repo | https://github.com/jeneeldumasia/ShipZen-GCP (**public**: run annotations and logs are public, so redact) |

## Recently done (Oct 2026, PRs #8–#27)
- IAM split: `shipzen-builder-sa` is push-only; platform uses `shipzen-platform-sa`. Security Check proves it.
- Gateway locked to Cloudflare ranges; `/metrics` refuses Cloudflare-forwarded requests.
- GitHub sign-in allowlist (`ALLOWED_GITHUB_USERS`), admins from `ADMIN_GITHUB_USERS`. GitHub outages and rate limits are reported as 503, not 401.
- Images pinned to `sha-<commit>` by Build and Push, which also un-sticks ArgoCD syncs.
- Orphaned resources are imported before plan (`scripts/adopt-orphaned-resources.sh`).
- Controller: orphan tenant-folder GC, `tenant.yaml` refreshed for existing projects about every 20 min, `/healthz`, `shipzen_database_up`.
- Grafana rebuilt: dashboards generated from `observability/dashboards.py`; Loki and Envoy metrics wired; false GKE alerts removed.
- Alerts: `infra/system/shipzen-alerts.yaml` → Alertmanager webhook → `alert-relay` → CallMeBot → WhatsApp.
- Network isolation: corrected NetworkPolicies (tenants, build namespace, shipzen-system, API egress) plus Dataplane V2; probed by Security Check.
- Teardown deletes the cluster's orphaned PVC disks (`scripts/cleanup-orphaned-disks.sh`).
- Docs restructured under `docs/` (see README).

## Open / next
- WhatsApp needs the user's one-time CallMeBot activation plus the `WHATSAPP_PHONE` / `WHATSAPP_APIKEY` repo secrets, then **Deploy Secrets**.
- Network isolation is only enforced on a cluster created after PR #27. Run **Security Check** after each rebuild; it must pass.
- The rest: `docs/roadmap.md`.

## Facts that trip people up
- Auto-Destroy runs every 3 h and fires once the cluster is 24 h old (GitHub may delay or skip scheduled runs).
- `apply-only.yaml` never replaces the cluster (`ignore_changes = [datapath_provider]`); datapath changes need a rebuild.
- Reconcile interval as deployed is 60 s (`RECONCILIATION_INTERVAL`), so "every 20 sweeps" is about 20 min.
- Tenant namespaces are identified by their `tenant-quota` ResourceQuota.
- Deploy workflows only *create* the `shipzen-alerts` and `shipzen-whatsapp` secrets when missing; they never overwrite them.
