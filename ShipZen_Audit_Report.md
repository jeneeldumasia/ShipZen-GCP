# ShipZen Comprehensive Audit Report

**Date:** September 15, 2026
**Project:** ShipZen (Internal Developer Platform)
**Status:** 100% Production Ready

---

## 1. Executive Summary

ShipZen is an Internal Developer Platform (IDP) allowing developers to provide a Git repository URL, automatically build a container image, deploy it to a Kubernetes cluster, and expose it via a unique subdomain. 

This audit report summarizes the current architectural state, security boundary definitions, historical architectural evolution, and production readiness of the ShipZen platform.

---

## 2. Core Architecture

The platform is designed around a decoupled, event-driven architecture using **PostgreSQL** as the strict source of truth and **Redis Streams** as the asynchronous message bus.

### 2.1 The 3-Tier Ephemeral Builder
To guarantee absolute security and eliminate shared blast radius, all builds are executed as single-use, ephemeral Kubernetes `Jobs` via a 3-tier detection framework:
1. **Tier 1 (Buildpacks):** Default fallback. Runs `pack` rootless.
2. **Tier 2 (Dockerfile):** If `Dockerfile` exists, runs BuildKit in `shipzen-builder-privileged`.
3. **Tier 3 (Railpack):** Runs Railpack natively in `shipzen-builder-privileged` for complex repositories.

*(Historical Note: The platform originally utilized KEDA-scaled persistent builder pods. This was explicitly redesigned on June 19 to the current single-use Job architecture to enforce stricter multi-tenant isolation).*

### 2.2 Reconciliation Loop
Kubernetes state is intentionally designed to be non-authoritative. The Python-based **Controller** continuously polls PostgreSQL and dynamically provisions/patches Kubernetes resources (`Namespace`, `Deployment`, `Service`, `HTTPRoute`, `NetworkPolicy`).

### 2.3 Routing & Networking
Traffic is ingested via **Envoy Gateway** (Gateway API). Dynamic HTTPRoutes are generated per-deployment mapping to `{dep-id}.{project}.shipzen.jeneeldumasia.codes`.

---

## 3. Production Readiness & Security

- **Database Integrity:** PostgreSQL replaced the original MongoDB implementation to enforce strict schema validation, ACID compliance, and relational constraints.
- **Tenant Isolation:** Complete logical separation via `Namespace` per project, augmented by `ResourceQuota`, `LimitRange`, `NetworkPolicy`, and Pod Security Standards (`restricted`).
- **Secret Management:** AWS Secrets Manager is used as the centralized store. External Secrets Operator (ESO) dynamically injects them into the cluster.
- **Node Isolation:** Karpenter NodePools use dedicated taints (`shipzen.io/dedicated=builder` vs `tenant`) to physically isolate user workloads from platform operations.
- **Authentication Hardening:** Explicit `conn.commit()` transaction boundaries in user creation, strict proxy-aware rate limiters parsing `X-Forwarded-For`, and parameterized admin role escalations.

---

## 4. Architecture Decision Records (ADRs) Overview

A summary of critical, audited ADRs currently governing the platform:

| ADR | Topic | Decision & History |
|---|---|---|
| **ADR-0001** | Queue System | **Redis Streams.** Originally utilized for persistent builder queues, amended on June 19 to trigger the Ephemeral Builder K8s Jobs. |
| **ADR-0002** | Database Design | **PostgreSQL.** Amended from MongoDB to enforce strict relational integrity and transactional guarantees. |
| **ADR-0003** | Networking | **Envoy Gateway (Gateway API).** Selected over traditional Ingress/NodePorts for dynamic, isolated HTTPRoute generation. |
| **ADR-0004** | Multi-Tenancy | **Namespace-per-Project.** Strict isolation augmented with NetworkPolicies and RBAC. |
| **ADR-0005** | Build System | **3-Tier Ephemeral Builder.** Amended from persistent scaled builders to ensure zero shared environment contamination. |
| **ADR-0006** | Reconciliation | **Python Controller.** PostgreSQL is the single source of truth; manual `kubectl` state mutations are automatically reverted. |
| **ADR-0007** | Observability | **Prometheus/Grafana/S3.** High cardinality metrics are strictly forbidden. Build logs are offloaded to S3. |
| **ADR-0008** | Secrets | **AWS Secrets Manager + ESO.** Prevents hardcoded credentials and centralizes audit trails. |

---

## 5. Operations & Setup Checklist

The infrastructure requires strict adherence to the **AWS Setup Guide** leveraging GitHub Actions OIDC (`shipzen-github-actions-role`) to dynamically assume IAM roles without static keys. 

1. **VPC & Control Plane:** HCP Terraform manages EKS, RDS PostgreSQL, ElastiCache Redis, and AWS ALB.
2. **Cluster Bootstrapping:** ArgoCD manages all Kubernetes manifest rollouts located in the `infra/` directory.
3. **Telemetry:** Prometheus metrics define SLOs and alert rules tracking Backlogs, DLQs, Builder Failures, and Drift.

---

*This report is generated dynamically based on the verified state of the ShipZen repository.*
