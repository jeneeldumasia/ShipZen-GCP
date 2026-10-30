# Design decisions

Why ShipZen is built the way it is. Each entry: what was decided, why, and what
it costs. Add a new entry rather than rewriting history; mark replaced ones as
superseded.

## 1. Postgres is the source of truth
**Decision.** Projects, deployments, members and audit logs live in PostgreSQL:
Cloud SQL now, an in-cluster Postgres before that. Kubernetes and Git are derived
from it.
**Why.** Schema validation, transactions and foreign keys. MongoDB was proposed
first and dropped for those reasons.
**Cost.** Cloud SQL is a separate bill and a single `db-f1-micro` instance; there
is no HA.

## 2. Deploys go through a Redis Stream, via an outbox
**Decision.** The API writes the deployment and an `outbox_events` row in one
transaction; a relay moves it to the `deploy_stream` Redis Stream. Workers use a
consumer group with explicit ACKs, reclaim stalled messages, retry, and finally
dead-letter. No Redis Lists.
**Why.** A deploy is never queued without being recorded, or recorded without
being queued, and a crashed worker doesn't lose builds.
**Cost.** Redis is in-cluster (AOF on), so the queue lives and dies with the cluster.

## 3. Every build is a throwaway Job
**Decision.** Each build is a single-use Job in `shipzen-build`: Kaniko for a
Dockerfile, otherwise Nixpacks generates one and Kaniko builds it.
**Why.** User code never shares an environment with other builds or the
platform. Buildpacks with long-lived KEDA-scaled builder pods were tried first
(June) and replaced.
**Cost.** Cold-start per build. Kaniko runs as root inside its container, and
Nixpacks is downloaded at build time (see [security.md](security.md#known-gaps)).

## 4. Builders get their own identity
**Decision.** `shipzen-builder-sa` can only push to `shipzen-builds`. The
platform services use `shipzen-platform-sa`. (October 2026, #15)
**Why.** Builds run untrusted Dockerfiles; previously they ran with the platform's
permissions, including Secret Manager admin.
**Cost.** Two identities to maintain. The **Security Check** workflow guards the
boundary.

## 5. One namespace per project
**Decision.** Each project gets its own namespace with quota, limits, restricted
Pod Security and its own RBAC. Never shared namespaces.
**Why.** Quota and blast-radius isolation between tenants.
**Cost.** Network isolation depends on NetworkPolicy enforcement, which is not on
yet ([security.md](security.md#known-gaps)).

## 6. The controller writes Git; ArgoCD applies it
**Decision.** The controller renders manifests from Postgres and commits them to
`shipzen-tenants` through a GitHub App; an ArgoCD ApplicationSet syncs one app
per tenant folder, with prune and self-heal. The platform itself is the
`shipzen-platform` app syncing `infra/`.
**Why.** Every change to running apps is a commit you can read and revert; manual
`kubectl` edits are undone. Postgres stays authoritative because the controller
re-renders from it.
**Cost.** A GitHub round-trip per change, GitHub API rate limits, and two places to
look (Postgres for intent, Git for what was rendered).

## 7. Gateway API with Envoy Gateway, behind Cloudflare
**Decision.** One Envoy Gateway, one HTTPRoute per deployment, hostnames under
`shipzen.jeneeldumasia.codes`, DNS by ExternalDNS. The load balancer accepts only
Cloudflare's IP ranges. No Ingress objects and no NodePorts.
**Why.** A standard routing API, a single load balancer, and Cloudflare's
TLS/DDoS protection that can't be bypassed.
**Cost.** If Cloudflare publishes new ranges, `infra/system/gateway.yaml` must be
updated.

## 8. Secrets live in Secret Manager
**Decision.** Platform secrets and each project's environment variables are in
Google Secret Manager; External Secrets Operator syncs them into the cluster.
Nothing secret goes in Postgres or Git.
**Why.** One audited store, and a rebuilt cluster gets its secrets back
automatically.
**Cost.** Secret Manager costs per secret version and access; ESO is one more
moving part.

## 9. No long-lived credentials anywhere
**Decision.** GitHub Actions → GCP uses Workload Identity Federation; pods use
GKE Workload Identity; ArgoCD and the controller use a GitHub App. No service
account keys and no personal access tokens.
**Why.** Nothing to leak that stays valid.

## 10. The cluster is disposable
**Decision.** Everything is Terraform; Auto-Destroy tears the cluster down after
24 h of uptime; teardown cleans up network leftovers, DNS records and orphaned
disks; redeploy rebuilds it in about 20 minutes.
**Why.** It runs on credits. A cluster nobody is using should cost nothing.
**Cost.** Prometheus history and Redis contents don't survive a rebuild. The
first deploy of the day takes 20 minutes.

## 11. Observability: Prometheus, Loki, Grafana as code
**Decision.** kube-prometheus-stack for metrics and alerts, Loki for logs, and
dashboards generated from `observability/dashboards.py`, aimed at people who
don't run Kubernetes. Avoid unbounded labels; per-project labels are acceptable
at this scale.
**Why.** The stock dashboards answered questions nobody here asks. Dashboards as
code are reviewable and tested against the metrics that actually exist.
**Cost.** Dashboard edits made in the Grafana UI don't stick.

## 12. Single zone, small nodes
**Decision.** Regional control plane, nodes only in `us-central1-c`, one
`e2-standard-4` node scaling to three.
**Why.** Cost: three zones roughly tripled the node bill.
**Cost.** A zone outage takes the platform down. Fine for a personal platform,
not for paying customers.

## 13. Network isolation with Dataplane V2
**Decision.** GKE Dataplane V2 enforces NetworkPolicies. Tenants and build Jobs
are confined to DNS, their own pods and the public internet; `shipzen-system`
accepts only itself, the gateway and monitoring. (October 2026)
**Why.** The policies existed but nothing enforced them. The Security Check probe
showed a tenant pod could reach the API, Redis, Grafana, Cloud SQL and the
metadata server.
**Cost.** Dataplane V2 is chosen at cluster creation, so it arrives with the next
rebuild. Any new platform-to-tenant or tenant-to-platform path needs a policy
change first.

## 14. Alerts go to WhatsApp through a webhook relay
**Decision.** Alertmanager's webhook calls a ~100-line relay in the cluster,
which sends one plain-language message per alert group through CallMeBot.
**Why.** WhatsApp is where it will be seen. There is no official free WhatsApp
API for personal alerts (Meta's needs a verified business; Twilio is paid).
**Cost.** It depends on a free third-party service. No message if CallMeBot is
down, apart from Alertmanager's retries.

