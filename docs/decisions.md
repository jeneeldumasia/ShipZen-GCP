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
**Decision.** A zonal cluster in `us-central1-c` (the control plane is then in
GKE's free tier). One `e2-standard-4` platform node scales to three. Separate
build and tenant pools scale from zero. (A regional control plane was used until
November 2026.)
**Why.** Cost: three zones roughly tripled the node bill, and a regional control
plane is billed.
**Cost.** A zone outage takes the platform down. Fine for a personal platform,
not for paying customers.

## 13. Network isolation with Dataplane V2
**Decision.** GKE Dataplane V2 enforces NetworkPolicies. Tenants and build Jobs
are confined to DNS, their own pods and the public internet; `shipzen-system`
accepts only itself, the gateway and monitoring. (October 2026)
**Why.** The policies existed but nothing enforced them. The Security Check probe
showed a tenant pod could reach the API, Redis, Grafana, Cloud SQL and the
metadata server.
**Cost.** Dataplane V2 is chosen at cluster creation. Every cluster since has it,
since each session rebuilds the cluster. Any new platform-to-tenant or
tenant-to-platform path needs a policy change first. The API's access to Loki and
Prometheus for the app page was one such change.

## 14. Alerts go to Telegram through a webhook relay
**Decision.** Alertmanager's webhook calls a ~100-line relay in the cluster,
which sends one plain-language message per alert group with a Telegram bot.
Teardown workflows send their alerts to the same chat (`scripts/notify.sh`).
**Why.** Telegram's Bot API is official, free and private to your chat.
Alertmanager could send to Telegram natively, but only raw alert names; the
relay keeps Grafana's plain words. (Until 2026-11 this went to WhatsApp through
CallMeBot, a free third-party service that stopped accepting new users.)
**Cost.** One more bot token to keep secret. If Telegram is down, Alertmanager
retries.

## 15. Deploy emails through Resend, not our own mail server
**Decision.** Deploy notifications (live, failed, app down, preview ready) go out
through Resend's HTTP API from `notify@jeneeldumasia.codes`, to each owner's and
editor's GitHub-verified address, deduplicated in Redis. Users can turn them off.
(November 2026)
**Why.**
- Resend's free tier (3,000 emails a month) covers a personal platform.
- Self-hosted SMTP is out: GCP blocks port 25, and the cluster has no fixed IP
  across teardowns, so mail from it would land in spam.
- The domain's DNS records live in Cloudflare and survive teardowns.

**Cost.**
- One more API key, stored inside the existing `shipzen-telegram` secret, since a
  new secret would push Secret Manager past its free versions.
- Sending never blocks or fails a deploy, so a Resend outage means missing emails,
  not failed deploys.

## 16. Preview deploys: same repository only, never live
**Decision.** Pull requests on a project's bound repository get a preview
release with its own URL, a PR comment and an email. Rules:
- Fork PRs are ignored.
- At most 3 PRs per project have previews, and each PR builds one commit at a time.
- Previews never become the live release and always run small × 1.
- Closing the PR supersedes its previews.

(November 2026)

**Why.**
- Building a fork's code would let anyone run code on the cluster by opening a PR.
- Keeping previews out of every "live release" query means production can't be
  replaced by a branch.

**Cost.**
- Contributors from forks get no preview.
- The GitHub App needs write access to pull requests, only for the comment.

## 17. Repo intelligence is rule-based
**Decision.** Repository analysis and build-failure diagnosis are plain rules:
- `api/analyzer.py` reads lockfiles, version files and framework defaults to work
  out the build, and gives its reasons.
- `worker/failure_rules.py` matches known error text. For a few failures with a
  safe fix it retries once with fixed values.

There is no LLM. (November 2026)

**Why.**
- Free, fast and predictable.
- The automatic fixes can only ever set values written in the repository's code,
  never anything taken from the log.

**Cost.** Unknown failures fall back to the raw log tail, and new failure types
need a new rule.

## 18. Platform switches live in Postgres
**Decision.**
- The announcement banner and the deploy freeze are rows in `platform_settings`.
- The freeze is checked in `check_deploy_limits`, which every deploy path already calls.
- Suspension is a column on `users`, checked at sign-in, and the cached tokens
  are evicted on every replica through Redis. (November 2026)

**Why.**
- Admins change these from the UI in seconds, without a redeploy or a workflow.
- They're audited like everything else.

**Cost.**
- A query on each deploy and on each page load (the banner).
- Suspension doesn't stop apps that are already running.
