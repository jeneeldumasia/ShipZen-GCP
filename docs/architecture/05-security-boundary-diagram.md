# Security Boundary Diagram

```mermaid
graph TD
    subgraph Public Internet
        Users
    end
    
    subgraph DMZ
        Cloudflare --> GCP_ALB[GCP Gateway]
    end
    
    subgraph ShipZen Platform [Namespace: shipzen-system]
        GCP_ALB --> Envoy[Envoy Gateway]
        Envoy --> API[API Server]
        API --> Postgres[(PostgresDB)]
        API --> Redis[(Redis)]
        Controller[Reconciliation Engine]
        ESO[External Secrets Operator]
    end
    
    subgraph Builder Isolation [Namespace: shipzen-build]
        Worker --> Builder[Builder Pods]
        Builder -- Workload Identity --> Artifact Registry[GCP Artifact Registry]
        Builder -- NetworkPolicy --> ExternalGit[GitHub]
    end
    
    subgraph Tenant Isolation [Namespaces: tenant-*]
        Pod1[Tenant Pods]
        Pod1 -- Restricted by NetworkPolicy --> Public
    end
    
    ESO -- Workload Identity --> SecretsManager[GCP Secret Manager]
```
