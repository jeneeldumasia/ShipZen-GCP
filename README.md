# ShipZen - Cloud-Native Multi-Tenant PaaS on GCP

> **A production-ready Platform-as-a-Service built on Google Kubernetes Engine**

ShipZen is a Heroku-like platform that automatically builds, deploys, and manages containerized applications on Kubernetes. It provides tenant isolation, automated scaling, observability, and GitOps-driven deployments.

## 🚀 Quick Start

### Prerequisites
- GCP account with billing enabled
- gcloud CLI installed
- kubectl installed
- GitHub account
- Terraform Cloud account

### 1. Fix Cluster Access (If Cluster Exists)
```powershell
cd c:\Project\ShipZen-GCP
.\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID
```

### 2. Verify Deployment Health
```powershell
.\scripts\verify-deployment.ps1 -ProjectId YOUR_PROJECT_ID
```

### 3. Deploy New Infrastructure
Follow the detailed guide: [GCP Setup Guide](docs/GCP_SETUP_GUIDE.md)

### 4. Troubleshoot Issues
See: [Quick Start Guide](QUICK_START.md)

## 📋 What's Inside

### Core Components
- **API** - FastAPI-based REST API with GitHub OAuth
- **Controller** - Kubernetes reconciliation engine
- **Worker** - Build orchestration and job processing
- **UI** - Next.js dashboard (React)
- **Builder** - Buildpack-based container builds

### Infrastructure
- **GKE Cluster** - Google Kubernetes Engine
- **Artifact Registry** - Container image storage
- **Cloud Storage** - Build logs and artifacts
- **Secret Manager** - Centralized secret management
- **PostgreSQL** - Metadata and state storage
- **Redis** - Message queue and caching

### Operators & Tools
- **ArgoCD** - GitOps continuous deployment
- **KEDA** - Event-driven autoscaling
- **External Secrets Operator** - Secret synchronization
- **Envoy Gateway** - Ingress and routing
- **Kyverno** - Policy enforcement
- **Prometheus + Grafana** - Monitoring and alerting

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      GitHub Actions                          │
│  (CI/CD, Image Builds, Infrastructure Deployment)           │
└───────────────────┬─────────────────────────────────────────┘
                    │
        ┌───────────▼──────────┐
        │   Artifact Registry   │
        │   (Container Images)  │
        └───────────┬───────────┘
                    │
┌───────────────────▼─────────────────────────────────────────┐
│                     GKE Cluster                              │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   ArgoCD     │  │     KEDA     │  │     ESO      │     │
│  │  (GitOps)    │  │ (Autoscale)  │  │  (Secrets)   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │          ShipZen Platform Services                   │  │
│  │  ┌─────────┐  ┌────────────┐  ┌────────────┐      │  │
│  │  │   API   │  │ Controller │  │   Worker   │      │  │
│  │  └─────────┘  └────────────┘  └────────────┘      │  │
│  │  ┌─────────┐  ┌────────────┐  ┌────────────┐      │  │
│  │  │   UI    │  │ PostgreSQL │  │   Redis    │      │  │
│  │  └─────────┘  └────────────┘  └────────────┘      │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │           Tenant Namespaces (Isolated)               │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │  │
│  │  │ Tenant 1 │  │ Tenant 2 │  │ Tenant N │          │  │
│  │  └──────────┘  └──────────┘  └──────────┘          │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Observability Stack                          │  │
│  │  ┌────────────┐  ┌──────────┐  ┌──────────────┐   │  │
│  │  │ Prometheus │  │ Grafana  │  │ Alertmanager │   │  │
│  │  └────────────┘  └──────────┘  └──────────────┘   │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## 📚 Documentation

- **[Quick Start](QUICK_START.md)** - Common issues and quick fixes
- **[GCP Setup Guide](docs/GCP_SETUP_GUIDE.md)** - Complete setup instructions
- **[Migration Summary](MIGRATION_SUMMARY.md)** - AWS→GCP migration details
- **[Fix Summary](FIX_SUMMARY.md)** - Recent fixes and improvements
- **[Architecture Docs](docs/architecture/)** - System design and diagrams
- **[ADRs](docs/adr/)** - Architecture Decision Records
- **[Issues & Resolutions](docs/ISSUES_AND_RESOLUTIONS.md)** - Troubleshooting guide

## 🛠️ Development

### Project Structure
```
ShipZen-GCP/
├── api/                    # FastAPI REST API
├── controller/             # Kubernetes controller
├── worker/                 # Build worker
├── ui/                     # Next.js frontend
├── infra/                  # Kubernetes manifests
├── terraform/              # Infrastructure as Code
├── scripts/                # Utility scripts
├── docs/                   # Documentation
└── tests/                  # Test suite
```

### Local Development
```bash
# Start local environment
docker-compose -f docker-compose.local.yml up

# Run tests
pytest

# Lint code
ruff check .
flake8 .
```

## 🚀 Deployment Flow

1. **Code Push** → GitHub repository
2. **GitHub Actions** → Build Docker images
3. **Push to GAR** → Artifact Registry
4. **ArgoCD Sync** → Deploy to GKE
5. **Controller** → Provision tenant namespaces
6. **Worker** → Build user applications
7. **KEDA** → Auto-scale based on load

## 🔒 Security Features

- **Workload Identity** - No static credentials
- **Network Policies** - Pod-to-pod isolation
- **Kyverno Policies** - Security enforcement
- **Secret Encryption** - GCP Secret Manager
- **RBAC** - Fine-grained access control
- **Pod Security Standards** - Restricted by default
- **Image Scanning** - Vulnerability detection (configurable)

## 📊 Monitoring & Observability

- **Metrics** - Prometheus + Grafana dashboards
- **Logs** - Centralized in GCS
- **Alerts** - Slack/PagerDuty integration
- **Tracing** - (Future: OpenTelemetry)
- **Health Checks** - Liveness/Readiness probes

## 🧪 Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# E2E tests (requires cluster)
pytest tests/e2e/
```

## 📦 Tech Stack

### Backend
- Python 3.11+
- FastAPI
- psycopg2 (PostgreSQL driver)
- redis-py
- kubernetes Python client

### Frontend
- Next.js 14
- React 18
- Tailwind CSS
- TypeScript

### Infrastructure
- Terraform
- Google Cloud Platform
- Kubernetes (GKE)
- Helm

### CI/CD
- GitHub Actions
- ArgoCD
- Docker

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## 📝 License

[Add your license here]

## 🆘 Support

### Having Issues?

1. **Check the scripts:**
   ```powershell
   .\scripts\fix-cluster-access.ps1 -ProjectId YOUR_PROJECT_ID
   .\scripts\verify-deployment.ps1 -ProjectId YOUR_PROJECT_ID
   ```

2. **Read the guides:**
   - [Quick Start](QUICK_START.md) - Common problems
   - [Issues & Resolutions](docs/ISSUES_AND_RESOLUTIONS.md) - Historical fixes

3. **Check logs:**
   ```bash
   kubectl logs -n shipzen-system deployment/shipzen-api
   kubectl get events -A --sort-by='.lastTimestamp'
   ```

4. **Verify resources:**
   ```bash
   kubectl get pods -A
   kubectl get applications -n argocd
   gcloud container clusters list
   ```

### Useful Commands

```bash
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project YOUR_PROJECT_ID

# Port forward to services
kubectl port-forward -n shipzen-system svc/shipzen-api 8000:8000
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
kubectl port-forward -n argocd svc/argocd-server 8080:443

# View resources
kubectl get all -n shipzen-system
kubectl get externalsecrets -A
kubectl describe pod POD_NAME -n NAMESPACE
```

## 🎯 Features

- ✅ Multi-tenant isolation with resource quotas
- ✅ Automated Buildpack-based builds
- ✅ GitOps deployment with ArgoCD
- ✅ Auto-scaling with KEDA
- ✅ Integrated monitoring and alerting
- ✅ Secret management via External Secrets Operator
- ✅ Network isolation with policies
- ✅ Pod security standards enforcement
- ✅ Rolling deployments with zero downtime
- ✅ Custom domains (future)
- ✅ Build logs in GCS
- ✅ Database migrations
- ⏭️ Horizontal pod autoscaling per tenant
- ⏭️ Custom buildpacks support
- ⏭️ Metrics in UI
- ⏭️ Cost tracking per tenant

## 📈 Roadmap

### Q1 2025
- [ ] Enhanced UI with real-time logs
- [ ] Custom domain support
- [ ] Backup and restore automation
- [ ] Cost allocation dashboard

### Q2 2025
- [ ] OpenTelemetry tracing
- [ ] Multi-region support
- [ ] Advanced RBAC policies
- [ ] Terraform module library

### Q3 2025
- [ ] Self-service tenant provisioning
- [ ] Marketplace integrations
- [ ] Advanced analytics
- [ ] Compliance reporting

---

**Built with ❤️ using Google Cloud Platform and Kubernetes**

