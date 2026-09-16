# Repository Structure Plan

```text
ShipZen/
├── api/              # API server
├── worker/           # Deployment queue worker
├── builder/          # Build system (Buildpacks + Dockerfile fallback)
├── controller/       # Reconciliation engine
├── gateway/          # Gateway API config and HTTPRoute templates
├── infra/            # Kubernetes manifests, Helm charts, Cluster Autoscaler config
├── observability/    # Prometheus rules, Grafana dashboards, SLO definitions
├── docs/             # ADRs, architecture diagrams, runbooks, threat model
│   ├── adr/
│   └── architecture/
└── scripts/          # Developer tooling, local setup
```
