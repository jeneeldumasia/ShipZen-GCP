# History

How ShipZen got to where it is. The details live in `git log` and
[operations/incidents.md](operations/incidents.md); this is the outline.

## June–August 2026: from DeployHub to ShipZen

- **Started as DeployHub**, a Kubernetes deploy pipeline: Postgres, Redis Streams
  and a Python worker that built images for a GitHub repository.
- **Gateway API and Cloudflare.** Envoy Gateway replaced ingress; Cloudflare in
  front for DNS and TLS. Teardown workflows were made reliable enough to run
  every day, which is what made the zero-idle-cost model possible.
- **Renamed to ShipZen**, with a Next.js dashboard and GitOps: the controller
  writes manifests to a Git repository and ArgoCD applies them.
- **GitHub sign-in and project roles** (owner / editor / viewer) in Postgres.
- **Ephemeral builders.** Every build became a single-use Job in its own
  namespace, with build logs streamed live and kept in GCS.
- **Cloudflare origin certificates** instead of cert-manager, and WebSocket log
  streaming to the UI.
- **Observability as code:** Prometheus, Grafana dashboards generated from
  Python, Loki and Alertmanager.
- **Secrets moved to GCP Secret Manager** through External Secrets, with Kyverno
  policies around them.
- **Delivery guarantees:** a transactional outbox in front of the queue and a
  dead-letter queue, so a deploy is never lost or queued twice.

## September–October 2026: GCP-only, and a security review

- **Moved to this repository, GCP only.** Builds settled on Kaniko for
  Dockerfiles and Nixpacks for everything else.
- **A full review of the platform** fixed viewer RBAC, rollback targets, a
  worker slot leak, database pool exhaustion, YAML injection through
  `shipzen.yaml` and broken alert queries, each with a regression test.
- **Locked down the edges:** the gateway accepts only Cloudflare's IP ranges,
  sign-in became invite-only, build pods lost every Google identity except a
  per-build push token, and a **Security Check** workflow proves it.
- **Network isolation** with GKE Dataplane V2 NetworkPolicies, and gVisor
  sandboxed node pools for builds and tenant apps.

## November 2026: product features and hardening

- **Blue-green releases** with instant rollback inside a grace period.
- **Preview deployments** for pull requests, stable vanity URLs, per-project
  scaling and email notifications.
- **Repo intelligence:** the analyzer explains what it detected, and failed
  builds get a diagnosis (and one safe automatic fix).
- **Admin operations:** announcements, a deploy freeze, user suspension and a
  running cost meter.
- **Invitations** instead of a fixed allowlist; build containers other than
  Kaniko run unprivileged; build images pinned by digest; GitHub sign-in for
  Grafana and ArgoCD; `terraform validate` in CI.
