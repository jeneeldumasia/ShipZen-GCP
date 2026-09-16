# ShipZen

ShipZen is a "zero-config deploy anything" platform. It allows users to input a repository URL and automatically builds and deploys the application, serving it at `{dep-id}.{project}.shipzen.jeneeldumasia.codes`.

## Architecture

The platform utilizes a **3-Tier Ephemeral Builder** architecture to support various deployment strategies without introducing a permanent, shared blast radius:

1. **Tier 1 (Buildpacks):** The default fallback. Runs `pack` rootless.
2. **Tier 2 (Dockerfile):** If a `Dockerfile` exists, runs BuildKit in a privileged environment.
3. **Tier 3 (Railpack):** For complex/mixed repos (e.g., `Cargo.toml`, `bun.lockb`), runs Railpack natively in a privileged environment.

Every build is a single-use Kubernetes `Job` that instantly terminates.

## Components

### Backend Services
- **API (`api/`):** FastAPI application handling endpoints for deployments. It accepts user repository URLs and auto-generates image URIs. Triggers deployments via webhooks, with strict branch filtering and payload validation.
- **Worker (`worker/`):** Redis Streams consumer acting as a state machine (Queued → Building → Deploying → Verifying → Running → Failed/DLQ). Spawns Kubernetes Jobs for builds.
- **Controller (`controller/`):** Reconciliation loop handling Kubernetes namespace provisioning and drift detection via Python client.
- **Builder (`builder/`):** Single-use Kubernetes Jobs for building applications. Authenticates natively to GCP Artifact Registry via IAM Roles for Service Accounts (IRSA).
- **Database:** PostgreSQL database storing `projects` (with associated repositories and branches), `deployments`, `builds`, and `audit_logs`.

### Infrastructure
- **Terraform:** Provisions VPC, GKE, EBS CSI addon, Artifact Registry, GCS for build logs, Cluster Autoscaler, KEDA, External Secrets Operator (ESO), cert-manager, Gateway Controller, kube-prometheus-stack, ArgoCD, Redis, and PostgreSQL.
- **Kubernetes:** Uses GKE with Cluster Autoscaler for NodePool management (builder and tenant nodes).
- **ArgoCD (`infra/`):** Syncs infrastructure components including the controller, worker, API, builder, and schema jobs.
- **Gateway:** Envoy Gateway with wildcard TLS routing on `*.shipzen.jeneeldumasia.codes`.

### Frontend
- **UI (`ui/`):** Next.js 14 App Router application with Tailwind CSS, TypeScript, and `lucide-react`. Includes a dashboard, project management, and deployment tracking with a visual pipeline.

## Documentation & Audit

For a comprehensive review, see the main [ShipZen Audit Report](file:///c:/Project/ShipZen/ShipZen_Audit_Report.md).

Deep-dive documentation is available in the `docs/` directory:
- [Architecture Review](file:///c:/Project/ShipZen/docs/ARCHITECTURE_REVIEW.md)
- [Production Readiness](file:///c:/Project/ShipZen/docs/production-readiness-review.md)
- [GCP Setup Guide](file:///c:/Project/ShipZen/docs/AWS_SETUP_GUIDE.md)
- [Issues & Resolutions](file:///c:/Project/ShipZen/docs/ISSUES_AND_RESOLUTIONS.md)
- [Architecture Decision Records (ADRs)](file:///c:/Project/ShipZen/docs/adr/)
- [Architecture Diagrams](file:///c:/Project/ShipZen/docs/architecture/)

## Local Development

To run the local testing stack (API + PostgreSQL + Redis), use Docker Compose:

```bash
docker compose up --build
```

You can test the API by running:
```bash
scripts/test-api.sh
```
