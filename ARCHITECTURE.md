# 🏗️ ShipZen Platform Architecture: Comprehensive Blueprint & Component Reference

> **Repository:** `ShipZen-GCP`  
> **Platform Category:** Multi-Tenant Internal Developer Platform (IDP / Mini-PaaS)  
> **Target Cloud:** Google Cloud Platform (GCP) — Google Kubernetes Engine (GKE)  
> **Diagram Source File:** [`ARCHITECTURE.mmd`](file:///home/jeneeld7492/ShipZen-GCP/ARCHITECTURE.mmd) & [`docs/architecture/complete_architecture.mmd`](file:///home/jeneeld7492/ShipZen-GCP/docs/architecture/complete_architecture.mmd)

---

## 📑 Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Master Mermaid Architecture Diagram](#2-master-mermaid-architecture-diagram)
3. [Component Breakdown by Layer](#3-component-breakdown-by-layer)
   - [Layer 1: External Edge, DNS & Network Load Balancing](#layer-1-external-edge-dns--network-load-balancing)
   - [Layer 2: Ingress & Kubernetes Gateway API (Envoy Gateway)](#layer-2-ingress--kubernetes-gateway-api-envoy-gateway)
   - [Layer 3: Frontend Presentation Tier (Next.js 14)](#layer-3-frontend-presentation-tier-nextjs-14)
   - [Layer 4: API Control Plane (FastAPI)](#layer-4-api-control-plane-fastapi)
   - [Layer 5: Persistence, Messaging & Storage](#layer-5-persistence-messaging--storage)
   - [Layer 6: Asynchronous Worker Engine](#layer-6-asynchronous-worker-engine)
   - [Layer 7: Ephemeral Builder Subsystem (Isolated Sandbox)](#layer-7-ephemeral-builder-subsystem-isolated-sandbox)
   - [Layer 8: Reconciliation Controller Engine (Custom Controller)](#layer-8-reconciliation-controller-engine-custom-controller)
   - [Layer 9: GitOps Pipeline & ArgoCD](#layer-9-gitops-pipeline--argocd)
   - [Layer 10: Multi-Tenant Workload Runtime](#layer-10-multi-tenant-workload-runtime)
   - [Layer 11: Platform Operators & Security Admission](#layer-11-platform-operators--security-admission)
   - [Layer 12: Observability, Metrics, Dashboards & Alerting](#layer-12-observability-metrics-dashboards--alerting)
   - [Layer 13: Cloud Infrastructure & Networking (Terraform)](#layer-13-cloud-infrastructure--networking-terraform)
4. [End-to-End Lifecycle & Data Flows](#4-end-to-end-lifecycle--data-flows)
   - [Flow A: Deployment Ingestion & Build Pipeline](#flow-a-deployment-ingestion--build-pipeline)
   - [Flow B: Dual Reconciliation & GitOps Synchronization](#flow-b-dual-reconciliation--gitops-synchronization)
   - [Flow C: Live Log Telemetry (K8s Watch to WebSockets)](#flow-c-live-log-telemetry-k8s-watch-to-websockets)
   - [Flow D: Secret Ingestion, Encryption & In-Cluster Sync](#flow-d-secret-ingestion-encryption--in-cluster-sync)
   - [Flow E: Failure Recovery & Dead Letter Queue (DLQ)](#flow-e-failure-recovery--dead-letter-queue-dlq)
5. [Codebase File & Component Cross-Reference](#5-codebase-file--component-cross-reference)

---

## 1. Architecture Overview

**ShipZen** is an open-source, production-grade cloud-native Developer Platform (PaaS) built on Google Kubernetes Engine (GKE). It transforms raw source code from GitHub into secure, isolated, auto-scaled, and production-monitored container workloads on Kubernetes with zero infrastructure burden on developers.

Key architectural characteristics:
- **Asynchronous, Event-Driven Core:** HTTP requests terminate instantly at the API boundary; all build and deployment tasks are written to PostgreSQL and dispatched through Redis Streams.
- **Strict Process Isolation:** Untrusted code builds execute in dedicated, ephemeral Kubernetes Jobs within an isolated `shipzen-build` namespace with non-root containers, unshare-only seccomp policies, and dedicated builder node taints.
- **True Multi-Tenancy:** Each user project receives an isolated Kubernetes namespace with restricted Pod Security Standards, tight ResourceQuotas, LimitRanges, egress-blocking NetworkPolicies, and zero-trust RBAC.
- **Dual State Enforcement (Fast-Path + GitOps):** The custom controller reconciles desired state by applying manifests directly via the Kubernetes API for sub-second updates while simultaneously committing rendered manifests to a GitOps repository (`shipzen-tenants`), where ArgoCD enforces automated synchronization, self-healing, and drift prevention.
- **Modern Ingress & Zero-Trust Security:** Envoy Gateway (Kubernetes Gateway API v1) backed by Cloudflare Origin CA certificates and Google Cloud Load Balancing provides rate-limited, TLS-terminated ingress routing.

---

## 2. Master Mermaid Architecture Diagram

```mermaid
flowchart TB

    %% ──────────────────────────────────────────────────────────────────────────
    %% 1. EXTERNAL ACTORS and EDGE SECURITY LAYER
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Edge_Layer ["🌐 External Clients, Edge and Security"]
        Developer["👨‍💻 Developer / User Browser"]
        GitHub_VCS["🐙 GitHub VCS (Source Repos and Webhook Events)"]
        
        subgraph Cloudflare_Edge ["🛡️ Cloudflare Edge Network"]
            CF_DNS["Cloudflare DNS (jeneeldumasia.codes)"]
            CF_Proxy["Cloudflare CDN and DDoS Proxy"]
            CF_SSL["Cloudflare Universal SSL / TLS"]
            CF_Origin_CA["Cloudflare Origin CA (15-Yr RSA Wildcard *.shipzen.jeneeldumasia.codes)"]
        end

        GCP_NLB["⚖️ GCP External TCP Network Load Balancer (Layer 4 NLB)"]
    end

    Developer -->|"HTTPS Traffic (*.shipzen.jeneeldumasia.codes)"| CF_Proxy
    GitHub_VCS -->|"Push Events and Webhooks (/webhooks/...)"| CF_Proxy
    CF_Proxy --> CF_SSL
    CF_SSL -->|"Encrypted Origin Forwarding (Port 443 / 80)"| GCP_NLB

    %% ──────────────────────────────────────────────────────────────────────────
    %% 2. INGRESS and GATEWAY API SUBSYSTEM (Envoy Gateway)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Gateway_API_System ["🚪 Kubernetes Gateway API Layer (envoy-gateway-system and shipzen-system)"]
        EG_Controller["🎮 Envoy Gateway Controller (v1.1.2)"]
        EG_Class["📋 GatewayClass: envoy-gateway"]
        EG_Proxy["📦 EnvoyProxy CRD: gcp-nlb-proxy (Type: LoadBalancer)"]
        
        Gateway_Core["⛩️ Gateway: shipzen-gateway (shipzen-system)"]
        GW_Listener_80["Listener: HTTP (Port 80)"]
        GW_Listener_443["Listener: HTTPS (Port 443 - TLS Terminate)"]
        TLS_Cert_Secret["🔐 K8s Secret: shipzen-tls-cert (Origin Cert and Key)"]
        
        Rate_Limit_Policy["🛑 BackendTrafficPolicy: global-rate-limit (100 req/min)"]
        HTTP_Redirect_Route["🔀 HTTPRoute: shipzen-http-redirect (Port 80 -> 301 HTTPS)"]
        
        HTTPRoute_UI["📍 HTTPRoute: shipzen-ui-route (shipzen.jeneeldumasia.codes)"]
        HTTPRoute_API["📍 HTTPRoute: shipzen-api-route (shipzen.jeneeldumasia.codes/api/v1)"]
        HTTPRoute_Argo["📍 HTTPRoute: argocd-route (argocd.jeneeldumasia.codes)"]
        HTTPRoute_Grafana["📍 HTTPRoute: grafana-route (grafana-shipzen.jeneeldumasia.codes)"]
    end

    GCP_NLB --> Gateway_Core
    EG_Controller -->|"Reconciles and Manages"| Gateway_Core
    EG_Class --> Gateway_Core
    EG_Proxy --> Gateway_Core
    
    Gateway_Core --> GW_Listener_80
    Gateway_Core --> GW_Listener_443
    TLS_Cert_Secret -.->|"Mounts TLS Certificate"| GW_Listener_443
    Rate_Limit_Policy -->|"Applies Global Throttling"| Gateway_Core
    GW_Listener_80 -->|"Enforces 301 Redirect"| HTTP_Redirect_Route
    
    GW_Listener_443 --> HTTPRoute_UI
    GW_Listener_443 --> HTTPRoute_API
    GW_Listener_443 --> HTTPRoute_Argo
    GW_Listener_443 --> HTTPRoute_Grafana

    %% ──────────────────────────────────────────────────────────────────────────
    %% 3. FRONTEND TIER (Next.js 14 App Router)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph UI_Tier ["🖥️ Frontend UI Dashboard (Namespace: shipzen-system)"]
        UI_Service["🔌 Service: shipzen-ui (Port 3000)"]
        UI_Deploy["📦 Deployment: shipzen-ui (Next.js 14 / React 18)"]
        UI_PDB["🛡️ PodDisruptionBudget: shipzen-ui-pdb"]
        
        subgraph UI_Modules ["Dashboard Modules and Pages"]
            UI_Auth["🔑 NextAuth.js (GitHub OAuth / Local Stub Auth)"]
            UI_Dashboard["📊 App Dashboard (/dashboard, ActivityFeed)"]
            UI_Projects["📁 Projects Manager (/projects, EnvVars, Webhooks)"]
            UI_LiveLogs["📟 Live Telemetry (/deployments/[id], LiveLogPanel, SSE/WS)"]
            UI_Admin["👑 Admin Center (/admin, Users RBAC, Deployments, Audit)"]
            UI_Observability["📈 Observability View (/observability, Embedded Grafana)"]
            UI_Palette["⌨️ Command Palette (Cmd+K Global Shortcuts)"]
        end
    end

    HTTPRoute_UI --> UI_Service
    UI_Service --> UI_Deploy
    UI_Deploy --- UI_PDB
    UI_Deploy --- UI_Auth
    UI_Deploy --- UI_Dashboard
    UI_Deploy --- UI_Projects
    UI_Deploy --- UI_LiveLogs
    UI_Deploy --- UI_Admin
    UI_Deploy --- UI_Observability
    UI_Deploy --- UI_Palette

    %% ──────────────────────────────────────────────────────────────────────────
    %% 4. API CONTROL PLANE (FastAPI REST and Real-time Server)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph API_Tier ["⚡ API Control Plane (Namespace: shipzen-system)"]
        API_Service["🔌 Service: shipzen-api (Port 8000)"]
        API_Deploy["📦 Deployment: shipzen-api (FastAPI / Uvicorn)"]
        API_PDB["🛡️ PodDisruptionBudget: shipzen-api-pdb"]
        API_SA["👤 ServiceAccount: shipzen-api-sa (Workload Identity)"]
        API_NetPol["🛡️ NetworkPolicy: api-networkpolicy"]

        subgraph API_Internal_Modules ["API Engine Submodules"]
            API_Limiter["⏱️ SlowAPI Rate Limiter"]
            API_Auth_Module["🔐 Auth Module (auth.py: Circuit Breaker, 60s Token Cache, RBAC)"]
            API_Analyzer["🔍 Repo Analyzer (analyzer.py: Dockerfile, Buildpacks, Go, Maven, Static, Railpack)"]
            API_Audit_Module["📜 Audit Logger (audit.py: Non-blocking log_audit_event)"]
            API_DB_Pool["🏊 DB Connection Pool (database.py: ThreadedConnectionPool)"]
            API_Webhooks["🪝 Webhook Dispatcher (HMAC Signature Verification)"]
            API_Realtime["📡 Realtime Server (WebSocket / SSE Log and Status Streaming)"]
        end
    end

    HTTPRoute_API --> API_Service
    UI_Deploy -->|"API Proxy Requests and WS Streams"| API_Service
    API_Service --> API_Deploy
    API_Deploy --- API_PDB
    API_Deploy --- API_SA
    API_Deploy --- API_NetPol
    API_Deploy --- API_Limiter
    API_Deploy --- API_Auth_Module
    API_Deploy --- API_Analyzer
    API_Deploy --- API_Audit_Module
    API_Deploy --- API_DB_Pool
    API_Deploy --- API_Webhooks
    API_Deploy --- API_Realtime

    %% ──────────────────────────────────────────────────────────────────────────
    %% 5. PERSISTENCE, MESSAGING and STORAGE SUBSYSTEM
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Data_Storage_Subsystem ["💾 Persistence and Messaging Subsystem"]
        subgraph Postgres_Cluster ["🐘 PostgreSQL 15 (Source of Truth)"]
            PG_Instance["PostgreSQL Engine (Cloud SQL or Bitnami StatefulSet)"]
            Schema_Job["⚙️ Job: shipzen-schema-bootstrap (ArgoCD PostSync Hook)"]
            
            subgraph PG_Tables ["Database Tables and Schema"]
                T_Users["👤 users (id, email, role: user/admin)"]
                T_Projects["📁 projects (id, owner_id, name, namespace, status, branch)"]
                T_Members["👥 project_members (project_id, user_id, role: owner/editor/viewer)"]
                T_Deployments["🚀 deployments (deployment_id, repo, image, replicas, port, state)"]
                T_Builds["🔨 builds (build_id, deployment_id, gcs_log_uri, status)"]
                T_Outbox["📤 outbox_events (stream_name, event_type, payload)"]
                T_Audit["📜 audit_logs (append-only, trigger trg_audit_logs_append_only)"]
            end
        end

        subgraph Redis_Cluster ["🔴 Redis Master (Standalone + AOF EverySec)"]
            Redis_Instance["Redis In-Memory Engine (Port 6379, redis-auth)"]
            Stream_Deploy["📨 Stream: deploy_stream (Active Deployment Tasks)"]
            Stream_DLQ["💀 Stream: deploy_stream_dlq (Dead Letter Queue after 3 Retries)"]
            PubSub_Reconcile["📢 Pub/Sub: shipzen:events:project_reconcile (Instant Reconcile)"]
            PubSub_Logs["📢 Pub/Sub: shipzen:logs:{deployment_id} (Live Log Broadcast)"]
        end

        subgraph GCP_Cloud_Storage ["🪣 Google Cloud Storage (GCS)"]
            GCS_Build_Logs["GCS Bucket: shipzen-build-logs-* (30-day Retention)"]
            GCS_Velero_Backups["GCS Bucket: shipzen-velero-backups (Cluster DR)"]
        end

        subgraph GCP_Artifact_Registry ["📦 Google Cloud Artifact Registry (GAR)"]
            GAR_Builds["GAR Repo: shipzen-builds (Tenant OCI Images)"]
            GAR_Platform["GAR Repo: shipzen-platform (Platform Container Images)"]
        end

        subgraph GCP_Secret_Manager ["🔒 Google Cloud Secret Manager"]
            GCP_SM_Project["Secrets: shipzen-project-{id} (Tenant Secrets Key/Values)"]
            GCP_SM_DB["Secrets: shipzen-db-credentials"]
            GCP_SM_Redis["Secrets: shipzen-redis-password"]
            GCP_SM_Cert["Secrets: shipzen-cloudflare-origin-cert"]
            GCP_SM_GitHub["Secrets: github-app-repo-creds (Private Key)"]
        end
    end

    Schema_Job -->|"Applies schema.sql"| PG_Instance
    PG_Instance --- T_Users
    PG_Instance --- T_Projects
    PG_Instance --- T_Members
    PG_Instance --- T_Deployments
    PG_Instance --- T_Builds
    PG_Instance --- T_Outbox
    PG_Instance --- T_Audit

    Redis_Instance --- Stream_Deploy
    Redis_Instance --- Stream_DLQ
    Redis_Instance --- PubSub_Reconcile
    Redis_Instance --- PubSub_Logs

    API_Deploy -->|"Write Desired State / Read Projects and Audits"| PG_Instance
    API_Deploy -->|"XADD Deployment Task"| Stream_Deploy
    API_Deploy -->|"Subscribe for Live Logs"| PubSub_Logs
    API_Deploy -->|"Fetch Stored Logs"| GCS_Build_Logs
    API_Deploy -->|"Read/Write Tenant Secrets"| GCP_SM_Project

    %% ──────────────────────────────────────────────────────────────────────────
    %% 6. WORKER ENGINE (Asynchronous Job Processor)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Worker_Tier ["⚙️ Worker Engine (Namespace: shipzen-system)"]
        Worker_Deploy["📦 Deployment: shipzen-worker (Python Daemon)"]
        Worker_PDB["🛡️ PodDisruptionBudget: shipzen-worker-pdb"]
        Worker_SA["👤 ServiceAccount: shipzen-worker-sa (Workload Identity)"]
        Worker_RBAC["🔑 Worker RBAC (BatchV1 Jobs, Pods, Logs Watch)"]
        
        subgraph Worker_Modules ["Worker Engine Submodules"]
            Worker_Health["🩺 Healthz Server (/healthz Redis Ping + Loop Tick, /metrics)"]
            Worker_Queue["📬 QueueClient (XREADGROUP consumer from worker_group, XACK, DLQ)"]
            Worker_SM["🔄 StateMachine (Queued -> Building -> Deploying -> Verifying -> Running)"]
            Worker_Pool["🧵 ThreadPoolExecutor (Concurrency Limit: 20 Workers)"]
            Worker_Builder_Orch["🏗️ Builder Orchestrator (BatchV1 Job Manifest Generator)"]
            Worker_Log_Streamer["📡 Log Streamer (K8s Watch -> Redis Pub/Sub + GCS Upload)"]
        end
    end

    Stream_Deploy -->|"XREADGROUP (worker_group)"| Worker_Queue
    Worker_Queue --> Worker_SM
    Worker_SM --> Worker_Pool
    Worker_Pool --> Worker_Builder_Orch
    Worker_Deploy --- Worker_PDB
    Worker_Deploy --- Worker_SA
    Worker_Deploy --- Worker_RBAC
    Worker_Deploy --- Worker_Health
    Worker_Deploy --- Worker_Log_Streamer
    Worker_Queue -->|"Max Retries Exceeded (3)"| Stream_DLQ

    Worker_Deploy -->|"Update Deployment Lifecycle State"| PG_Instance
    Worker_Log_Streamer -->|"Broadcast Line-by-Line"| PubSub_Logs
    Worker_Log_Streamer -->|"Archive Full Build Log"| GCS_Build_Logs

    %% ──────────────────────────────────────────────────────────────────────────
    %% 7. EPHEMERAL BUILDER POOL (Namespace: shipzen-build)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Builder_Subsystem ["🏗️ Ephemeral Builder Subsystem (Namespace: shipzen-build)"]
        Builder_Job["⚙️ Kubernetes Job: build-{deployment_id} (activeDeadlineSeconds: 1800)"]
        Builder_SA["👤 ServiceAccount: shipzen-builder-sa (Workload Identity)"]
        Builder_Taint["🏷️ Node Toleration: shipzen.jeneeldumasia.codes/dedicated=builder:NoSchedule"]
        Builder_Policy_Ex["🛡️ Kyverno PolicyException: shipzen-build-buildkit-exception (Unconfined Seccomp)"]
        
        subgraph Builder_Pod ["Builder Pod Container Pipeline"]
            Init_Git["📥 InitContainer: git-clone (alpine/git:2.43.0 with GitHub App JWT Auth)"]
            Vol_Workspace["📁 Shared Volume: workspace (emptyDir)"]
            
            subgraph Builder_Engines ["Pluggable Builder Engine"]
                Engine_Kaniko["🐳 Dockerfile Builder: Kaniko Executor (gcr.io/kaniko-project/executor:v1.23.2)"]
                Engine_Nixpacks["📦 Nixpacks Builder: (ghcr.io/railwayapp/nixpacks:latest + Kaniko)"]
            end
        end
    end

    Worker_Builder_Orch -->|"Creates BatchV1 Job"| Builder_Job
    Builder_Job --- Builder_SA
    Builder_Job --- Builder_Taint
    Builder_Job --- Builder_Policy_Ex
    Builder_Job --- Init_Git
    Init_Git -->|"Clones Repository"| Vol_Workspace
    Vol_Workspace --> Engine_Kaniko
    Vol_Workspace --> Engine_Nixpacks
    Init_Git -.->|"Auth via GitHub App Token"| GitHub_VCS

    Engine_Kaniko -->|"Builds and Pushes OCI Image + Layer Cache"| GAR_Builds
    Engine_Nixpacks -->|"Builds and Pushes OCI Image + Layer Cache"| GAR_Builds
    Worker_Log_Streamer -->|"Tail Container Logs (CoreV1Api.read_namespaced_pod_log)"| Builder_Job

    %% ──────────────────────────────────────────────────────────────────────────
    %% 8. RECONCILIATION ENGINE / CUSTOM CONTROLLER
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Controller_Tier ["🎮 Kubernetes Custom Controller (Namespace: shipzen-system)"]
        Controller_Deploy["📦 Deployment: shipzen-controller (HA Replicas 2-5)"]
        Controller_HPA["📈 HPA: shipzen-controller-hpa (CPU Target: 80%)"]
        Controller_PDB["🛡️ PodDisruptionBudget: shipzen-controller-pdb"]
        Controller_SA["👤 ServiceAccount: shipzen-controller-sa"]
        Controller_CR["🔑 ClusterRole: shipzen-controller-role (Cluster-Wide Resource Admin)"]
        
        subgraph Controller_Modules ["Controller Submodules"]
            Leader_Elector["👑 LeaderElector (coordination.k8s.io Lease: shipzen-controller-leader)"]
            Work_Queue["📥 Internal WorkQueue (_work_queue)"]
            Event_Listener["👂 Event Listener (Redis Pub/Sub shipzen:events:project_reconcile)"]
            Reconcile_Sweeper["🧹 Sweeper Loop (15s Periodic Sweep + Timeout Sweeper)"]
            O1_Bulk_Lister["⚡ Bulk State Cache (O(1) list_deployment_for_all_namespaces)"]
            Jinja_Renderer["📝 Jinja2 Template Engine (tenant.yaml.j2, app-deployment.yaml.j2)"]
            Direct_K8s_Applier["🛠️ Direct K8s Reconciler (create_from_yaml / patch_namespaced_*)"]
            GitOps_Committer["🐙 GitOps Committer (commit_manifests_to_git via GitHub App)"]
            GAR_Cleaner["🗑️ GAR Package Cleaner (delete_gar_repository on Project Deletion)"]
        end
    end

    Controller_Deploy --- Controller_HPA
    Controller_Deploy --- Controller_PDB
    Controller_Deploy --- Controller_SA
    Controller_Deploy --- Controller_CR
    Controller_Deploy --- Leader_Elector
    
    PubSub_Reconcile -->|"Instant Trigger"| Event_Listener
    Event_Listener --> Work_Queue
    Work_Queue --> Jinja_Renderer
    Reconcile_Sweeper --> Jinja_Renderer
    
    PG_Instance -->|"Reads Desired State"| Reconcile_Sweeper
    O1_Bulk_Lister -->|"Compares Actual vs Desired (Drift Detection)"| Reconcile_Sweeper
    
    Jinja_Renderer -->|"Renders K8s YAML"| Direct_K8s_Applier
    Jinja_Renderer -->|"Commits Manifests"| GitOps_Committer
    Reconcile_Sweeper -->|"On Project Teardown"| GAR_Cleaner
    GAR_Cleaner -->|"Purges Images"| GAR_Builds

    %% ──────────────────────────────────────────────────────────────────────────
    %% 9. GITOPS CONTINUOUS DEPLOYMENT (ArgoCD)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph GitOps_Subsystem ["🐙 GitOps Continuous Deployment (Namespace: argocd)"]
        Argo_Server["🖥️ ArgoCD Server (Insecure Mode behind Envoy Gateway)"]
        HTTPRoute_Argo -->|"Admin Dashboard UI"| Argo_Server
        
        GitOps_Repo["📁 GitOps Manifests Repo: github.com/jeneeldumasia/shipzen-tenants"]
        Platform_Repo["📁 Platform Repo: github.com/jeneeldumasia/ShipZen-GCP"]
        
        Argo_App_Platform["📦 Argo Application: shipzen-platform (Path: infra/)"]
        Argo_AppSet_Tenants["📦 Argo ApplicationSet: tenant-namespaces (Path: namespaces/*)"]
    end

    GitOps_Committer -->|"Pushes Tenant Manifests (namespaces/{namespace}/)"| GitOps_Repo
    Platform_Repo -->|"Watched by"| Argo_App_Platform
    GitOps_Repo -->|"Watched by"| Argo_AppSet_Tenants
    
    Argo_App_Platform -->|"Automated Sync and Prune"| Gateway_API_System
    Argo_App_Platform -->|"Automated Sync and Prune"| UI_Tier
    Argo_App_Platform -->|"Automated Sync and Prune"| API_Tier
    Argo_App_Platform -->|"Automated Sync and Prune"| Worker_Tier
    Argo_App_Platform -->|"Automated Sync and Prune"| Controller_Tier

    %% ──────────────────────────────────────────────────────────────────────────
    %% 10. MULTI-TENANT APPLICATION RUNTIME (Isolated Namespaces)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Multi_Tenant_Runtime ["🛡️ Multi-Tenant Workload Runtime (Namespaces: tenant-*)"]
        subgraph Tenant_Namespace ["Namespace: tenant-{project_name} (pod-security: restricted)"]
            Tenant_SA["👤 ServiceAccount: default (automountServiceAccountToken: false)"]
            Tenant_Quota["📊 ResourceQuota: tenant-quota (4-8 CPU, 8-16Gi RAM, 20 Pods, 10 Svcs)"]
            Tenant_LimitRange["📏 LimitRange: tenant-limit-range (Default: 500m CPU / 512Mi RAM)"]
            Tenant_NetPol["🛡️ NetworkPolicy: tenant-isolation (Deny VPC and IMDS 169.254.169.254, Allow Ingress from Envoy)"]
            Tenant_RBAC["🔑 Role and RoleBinding: tenant-runner (ConfigMaps read only, ZERO Secret access)"]
            
            subgraph Tenant_Secrets_Sync ["Secret Synchronization (ESO)"]
                Tenant_ExtSecret["🔐 ExternalSecret: {deployment}-secrets (refreshInterval: 1h)"]
                Tenant_K8s_Secret["🔑 K8s Secret: {deployment}-secrets-sync (Owner Policy)"]
            end

            subgraph Tenant_Workload ["User Application Pods"]
                Tenant_Deploy["📦 Deployment: {deployment_name} (Replicas: 1-N)"]
                Tenant_PDB["🛡️ PodDisruptionBudget: maxUnavailable: 1"]
                Tenant_Pod_Toleration["🏷️ Toleration: shipzen.jeneeldumasia.codes/dedicated=tenant:NoSchedule"]
                Tenant_Container["🐳 Container: app (RunAsNonRoot: 1000, ReadOnlyRootFilesystem, Drop ALL Caps)"]
                Tenant_Probe["🩺 ReadinessProbe: HTTP GET {{ health_check_path }}"]
            end

            Tenant_Svc["🔌 Service: {deployment_name}-svc (Port 80 -> containerPort)"]
            Tenant_HTTPRoute["📍 HTTPRoute: {deployment_name}-route (Host: {subdomain}-shipzen.jeneeldumasia.codes)"]
            Tenant_PodMonitor["📈 PodMonitor: tenant-pod-monitor (Scrapes app /metrics)"]
        end
    end

    Direct_K8s_Applier -->|"Direct State Enforcement"| Tenant_Namespace
    Argo_AppSet_Tenants -->|"GitOps Sync and Self-Heal"| Tenant_Namespace
    
    Tenant_ExtSecret -->|"Extracts Secret"| GCP_SM_Project
    Tenant_ExtSecret -->|"Generates"| Tenant_K8s_Secret
    Tenant_K8s_Secret -.->|"Injected via envFrom"| Tenant_Container
    GAR_Builds -->|"Pulls App Image"| Tenant_Deploy
    
    Tenant_Deploy --- Tenant_PDB
    Tenant_Deploy --- Tenant_Pod_Toleration
    Tenant_Deploy --- Tenant_Container
    Tenant_Container --- Tenant_Probe
    
    Tenant_Deploy --> Tenant_Svc
    Tenant_Svc --> Tenant_HTTPRoute
    Tenant_HTTPRoute -.->|"Attaches as route to"| Gateway_Core
    Tenant_Workload --- Tenant_Quota
    Tenant_Workload --- Tenant_LimitRange
    Tenant_Workload --- Tenant_NetPol
    Tenant_Workload --- Tenant_RBAC

    %% ──────────────────────────────────────────────────────────────────────────
    %% 11. PLATFORM OPERATORS and CONTROLLERS
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Platform_Operators ["⚙️ Cluster Operators and Platform Add-ons"]
        subgraph ESO_Operator ["External Secrets Operator (Namespace: external-secrets)"]
            ESO_Controller["🎮 ESO Controller (v0.9.20)"]
            ESO_SA["👤 ServiceAccount: external-secrets-sa (Workload Identity)"]
            ClusterSecretStore["🏛️ ClusterSecretStore: gcp-secret-manager (gcpsm Provider)"]
        end

        subgraph KEDA_Operator ["KEDA Autoscaler (Namespace: keda)"]
            KEDA_Controller["🎮 KEDA Controller (v2.14.2)"]
            ScaledObject_Worker["📈 ScaledObject (Optional: Scales Workers based on Redis Stream Depth)"]
        end

        subgraph Kyverno_Operator ["Kyverno Policy Engine (Namespace: kyverno)"]
            Kyverno_Controller["🎮 Kyverno Admission Controller and ValidatingPolicies (Enforce Mode)"]
            Policy_No_Root["🛡️ ClusterPolicy: Disallow Root and Privileged Pods"]
            Policy_Drop_Caps["🛡️ ClusterPolicy: Require Dropping Capabilities"]
        end

        subgraph ExternalDNS_Operator ["ExternalDNS (Namespace: external-dns)"]
            ExtDNS_Controller["🎮 ExternalDNS (v1.14.3 with Cloudflare Provider)"]
        end

        subgraph Velero_Operator ["Velero Backup and Disaster Recovery (Namespace: velero)"]
            Velero_Controller["🎮 Velero Controller (v7.2.1 with GCP Plugin)"]
            Velero_SA["👤 ServiceAccount: velero (Workload Identity)"]
        end
    end

    ESO_SA -->|"Workload Identity Access"| GCP_Secret_Manager
    ClusterSecretStore --> ESO_Controller
    Tenant_ExtSecret -.->|"Managed by"| ClusterSecretStore

    KEDA_Controller -.->|"Monitors Queue Depth"| Stream_Deploy
    
    Kyverno_Controller -->|"Enforces Admission Rules on all Pods"| Multi_Tenant_Runtime
    Kyverno_Controller -->|"Honors PolicyException"| Builder_Policy_Ex

    Tenant_HTTPRoute -.->|"Watched by"| ExtDNS_Controller
    ExtDNS_Controller -->|"Automatically registers DNS records"| CF_DNS

    Velero_Controller --- Velero_SA
    Velero_SA -->|"Backups Kubernetes Resources and PVCs"| GCS_Velero_Backups

    %% ──────────────────────────────────────────────────────────────────────────
    %% 12. OBSERVABILITY, METRICS and ALERTING STACK
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph Observability_Tier ["📊 Observability and Reliability Stack (Namespace: observability)"]
        Prometheus_Server["🔥 Prometheus (kube-prometheus-stack, 30d Retention, 10Gi PVC)"]
        Grafana_Server["📈 Grafana (Domain: grafana-shipzen.jeneeldumasia.codes, 2Gi PVC)"]
        Alertmanager_Server["🚨 Alertmanager (Slack / Webhook Alerts)"]
        Loki_Server["📋 Loki (Centralized Log Aggregation)"]
        
        HTTPRoute_Grafana -->|"Grafana UI"| Grafana_Server

        subgraph Service_Monitors ["Service and Pod Scrape Targets"]
            SM_API["🎯 ServiceMonitor: shipzen-api (Port 8000 /metrics)"]
            SM_Controller["🎯 ServiceMonitor: shipzen-controller (Port 9090 /metrics)"]
            SM_Worker["🎯 ServiceMonitor: shipzen-worker (Port 8000 /metrics)"]
            PM_Tenant["🎯 PodMonitor: tenant-pod-monitor (Tenant Pods /metrics)"]
            SM_NodeExporter["🎯 NodeExporter (Cluster Node CPU/RAM/Disk)"]
        end

        subgraph Alert_Rules ["PrometheusRules and Alerts"]
            Rule_Platform["⚠️ shipzen-platform-alerts (QueueBacklog, DLQGrowing, RedisDown, PGDown, EnvoyDown, DriftHigh)"]
            Rule_Secrets["⚠️ external-secrets-alerts (ExternalSecretSyncFailed, SM_API_Errors, SecretExpiring)"]
            Rule_SLOs["🎯 shipzen-slos (Availability > 99.9%, Queue Latency < 10s p95, Retry Rate < 5%, DLQ = 0)"]
        end

        subgraph Dashboards_Config ["Grafana Dashboards Sidecar"]
            Dashboards_CM["📊 ConfigMap: shipzen-grafana-dashboards (Folder: Infrastructure Advanced)"]
        end
    end

    API_Deploy -.->|"Exposes /metrics"| SM_API
    Controller_Deploy -.->|"Exposes /metrics"| SM_Controller
    Worker_Deploy -.->|"Exposes /metrics"| SM_Worker
    Tenant_Deploy -.->|"Exposes /metrics"| PM_Tenant

    SM_API --> Prometheus_Server
    SM_Controller --> Prometheus_Server
    SM_Worker --> Prometheus_Server
    PM_Tenant --> Prometheus_Server
    SM_NodeExporter --> Prometheus_Server

    Prometheus_Server --> Rule_Platform
    Prometheus_Server --> Rule_Secrets
    Prometheus_Server --> Rule_SLOs
    Rule_Platform --> Alertmanager_Server
    Rule_Secrets --> Alertmanager_Server
    Rule_SLOs --> Alertmanager_Server

    Prometheus_Server -->|"Metrics Data Source"| Grafana_Server
    Dashboards_CM -->|"Sidecar Auto-Import"| Grafana_Server
    UI_Observability -.->|"Embeds iFrame Dashboards"| Grafana_Server

    %% ──────────────────────────────────────────────────────────────────────────
    %% 13. CLOUD INFRASTRUCTURE (GCP Networking and GKE Topology)
    %% ──────────────────────────────────────────────────────────────────────────
    subgraph GCP_Cloud_Infrastructure ["☁️ Google Cloud Platform (us-central1)"]
        subgraph GCP_VPC ["VPC Network: shipzen-vpc (10.0.0.0/16)"]
            GCP_Subnet["Subnet: shipzen-subnet (10.0.0.0/16)"]
            GCP_Router["Cloud Router: shipzen-router"]
            GCP_NAT["Cloud NAT: shipzen-nat (Egress Internet Access)"]
        end

        subgraph GKE_Cluster ["GKE Cluster: shipzen-cluster (Workload Identity Enabled)"]
            subgraph NodePool_Platform ["NodePool: platform-nodes (1-3 Nodes Autoscaling)"]
                Node_Platform_Desc["Label: shipzen.jeneeldumasia.codes/node-type=platform<br/>Hosts: System, Observability, Operators, Controllers"]
            end
            
            subgraph NodePool_Builders ["Dedicated Builder Node Pool"]
                Node_Builder_Desc["Taint: shipzen.jeneeldumasia.codes/dedicated=builder:NoSchedule<br/>Hosts: Ephemeral Kaniko and Nixpacks Jobs"]
            end

            subgraph NodePool_Tenants ["Dedicated Tenant Node Pool"]
                Node_Tenant_Desc["Taint: shipzen.jeneeldumasia.codes/dedicated=tenant:NoSchedule<br/>Hosts: Isolated User Application Workloads"]
            end
        end

        subgraph GCP_IAM ["IAM and Workload Identity Federation (GCP Project .svc.id.goog)"]
            IAM_Node_SA["GCP SA: shipzen-node-sa (Logging, Monitoring, Artifact Registry Reader)"]
            IAM_Builder_SA["GCP SA: shipzen-builder-sa (Artifact Registry Writer, Storage Object Admin)"]
            IAM_ESO_SA["GCP SA: shipzen-eso-sa (Secret Manager Secret Accessor)"]
            IAM_Velero_SA["GCP SA: velero-backup-sa (Storage Object Admin)"]
        end
    end

    GCP_Subnet --- GCP_Router
    GCP_Router --- GCP_NAT
    GCP_Subnet --- GKE_Cluster
    
    API_SA -.->|"Workload Identity"| IAM_Builder_SA
    Worker_SA -.->|"Workload Identity"| IAM_Builder_SA
    Builder_SA -.->|"Workload Identity"| IAM_Builder_SA
    ESO_SA -.->|"Workload Identity"| IAM_ESO_SA
    Velero_SA -.->|"Workload Identity"| IAM_Velero_SA

    %% Styling and Class Definitions
    classDef edgeClass fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef gatewayClass fill:#0f172a,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef uiClass fill:#1e1b4b,stroke:#a855f7,stroke-width:2px,color:#f8fafc;
    classDef apiClass fill:#172554,stroke:#3b82f6,stroke-width:2px,color:#f8fafc;
    classDef workerClass fill:#14532d,stroke:#22c55e,stroke-width:2px,color:#f8fafc;
    classDef builderClass fill:#701a75,stroke:#ec4899,stroke-width:2px,color:#f8fafc;
    classDef controllerClass fill:#7c2d12,stroke:#f97316,stroke-width:2px,color:#f8fafc;
    classDef dataClass fill:#042f2e,stroke:#14b8a6,stroke-width:2px,color:#f8fafc;
    classDef tenantClass fill:#312e81,stroke:#6366f1,stroke-width:2px,color:#f8fafc;
    classDef obsClass fill:#3f3f46,stroke:#fbbf24,stroke-width:2px,color:#f8fafc;
    classDef opsClass fill:#18181b,stroke:#a1a1aa,stroke-width:2px,color:#f8fafc;

    class Developer,GitHub_VCS,CF_DNS,CF_Proxy,CF_SSL,CF_Origin_CA,GCP_NLB edgeClass;
    class EG_Controller,EG_Class,EG_Proxy,Gateway_Core,GW_Listener_80,GW_Listener_443,Rate_Limit_Policy,HTTP_Redirect_Route,HTTPRoute_UI,HTTPRoute_API,HTTPRoute_Argo,HTTPRoute_Grafana gatewayClass;
    class UI_Deploy,UI_Service,UI_Auth,UI_Dashboard,UI_Projects,UI_LiveLogs,UI_Admin,UI_Observability,UI_Palette uiClass;
    class API_Deploy,API_Service,API_Limiter,API_Auth_Module,API_Analyzer,API_Audit_Module,API_DB_Pool,API_Webhooks,API_Realtime apiClass;
    class Worker_Deploy,Worker_Health,Worker_Queue,Worker_SM,Worker_Pool,Worker_Builder_Orch,Worker_Log_Streamer workerClass;
    class Builder_Job,Init_Git,Engine_Kaniko,Engine_Nixpacks builderClass;
    class Controller_Deploy,Leader_Elector,Event_Listener,Reconcile_Sweeper,O1_Bulk_Lister,Jinja_Renderer,Direct_K8s_Applier,GitOps_Committer,GAR_Cleaner controllerClass;
    class PG_Instance,Redis_Instance,GCS_Build_Logs,GCS_Velero_Backups,GAR_Builds,GAR_Platform,GCP_SM_Project,GCP_SM_DB,GCP_SM_Redis,GCP_SM_Cert,GCP_SM_GitHub dataClass;
    class Tenant_Deploy,Tenant_Container,Tenant_Svc,Tenant_HTTPRoute,Tenant_ExtSecret,Tenant_K8s_Secret,Tenant_Quota,Tenant_LimitRange,Tenant_NetPol,Tenant_RBAC tenantClass;
    class Prometheus_Server,Grafana_Server,Alertmanager_Server,Loki_Server,SM_API,SM_Controller,SM_Worker,PM_Tenant,Rule_Platform,Rule_Secrets,Rule_SLOs,Dashboards_CM obsClass;
    class ESO_Controller,ClusterSecretStore,KEDA_Controller,Kyverno_Controller,ExtDNS_Controller,Velero_Controller,Argo_Server,Argo_App_Platform,Argo_AppSet_Tenants opsClass;
```

---

## 3. Component Breakdown by Layer

### Layer 1: External Edge, DNS & Network Load Balancing
- **Cloudflare Edge Proxy & DNS:** Manages the root and wildcard DNS zones (`jeneeldumasia.codes` and `*.shipzen.jeneeldumasia.codes`). Enforces TLS 1.3, DDoS protection, edge caching, and automated HTTPS upgrades.
- **Cloudflare Origin CA Certificate:** A 15-year RSA wildcard certificate provisioned via Terraform and stored securely in GCP Secret Manager, mounted directly by Kubernetes as `shipzen-tls-cert`. This avoids Let's Encrypt rate limits and ACME webhook race conditions.
- **GCP External Network Load Balancer (NLB):** Layer 4 TCP load balancer created by GKE for the Envoy Gateway proxy service, distributing traffic across cluster nodes with preservation of client IP addresses.

### Layer 2: Ingress & Kubernetes Gateway API (Envoy Gateway)
- **Envoy Gateway Controller (`envoy-gateway-system`):** Implements the official Kubernetes Gateway API (`gateway.networking.k8s.io/v1`).
- **`Gateway` (`shipzen-gateway`):** Dual listener configuration on port 80 (HTTP) and port 443 (HTTPS) with TLS termination.
- **`BackendTrafficPolicy` (`global-rate-limit`):** Protects the platform by restricting traffic to 100 requests per minute globally.
- **`HTTPRoute` Routing Table:**
  - `shipzen-http-redirect`: Catch-all rule returning 301 redirects to HTTPS for unencrypted port 80 traffic.
  - `shipzen-ui-route`: Routes `shipzen.jeneeldumasia.codes` traffic to `shipzen-ui:3000`.
  - `shipzen-api-route`: Routes path `/api/v1` to `shipzen-api:8000`.
  - `argocd-route`: Routes `argocd.jeneeldumasia.codes` to `argocd-server:80`.
  - `grafana-route`: Routes `grafana-shipzen.jeneeldumasia.codes` to Grafana.
  - Tenant HTTPRoutes: Dynamically bound per tenant deployment.

### Layer 3: Frontend Presentation Tier (Next.js 14)
- **Next.js 14 App Router (`ui/`):** React 18, Tailwind CSS, TypeScript dashboard.
- **NextAuth.js (`ui/src/auth.ts`):** Supports GitHub OAuth 2.0 with JWT session tokens and a local dev stub credential provider.
- **User Dashboard (`ui/src/app/dashboard`):** Real-time project overview and system activity feed.
- **Project Manager (`ui/src/app/projects`):** Project provisioning status tracker, environment variable editor, and webhook configuration.
- **Live Telemetry & Logs (`ui/src/app/projects/[id]/deployments/[depId]`):** Real-time deployment progress bar, live build terminal streaming via WebSockets / Server-Sent Events, rollbacks, and cancellations.
- **Admin Console (`ui/src/app/admin`):** Cross-tenant project oversight, deployment queue monitor, user RBAC role promotion, and audit log browser.
- **Global Command Palette (`ui/src/components/CommandPalette.tsx`):** `Cmd+K` keyboard shortcut navigation across all projects and views.

### Layer 4: API Control Plane (FastAPI)
- **FastAPI Core (`api/main.py`):** High-performance asynchronous REST and WebSocket API.
- **Security & Rate Limiting:** `SlowAPI` decorator limiting request rates per client IP.
- **Auth Engine (`api/auth.py`):** GitHub token validation with an in-memory 60-second `TTLCache`, circuit breaker (`_github_cb_open`) to isolate against GitHub API degradation, and immediate cache eviction (`evict_user_token_cache`) on role changes.
- **Repository Analyzer (`api/analyzer.py`):** Analyzes cloned repo structures to detect frameworks (Next.js, Vite, Express, FastAPI, Django, Flask, Go, Java Maven, Railpack, or static HTML) and validates optional `shipzen.yaml` configuration files.
- **Database Connection Pool (`api/database.py`):** `ThreadedConnectionPool` (psycopg2) ensuring thread-safe access with `PooledConnectionWrapper` to prevent pool exhaustion.
- **Append-Only Audit Engine (`api/audit.py`):** Logs every administrative or deployment action asynchronously with non-blocking error containment.
- **Real-time Telemetry:** Exposes WebSocket endpoints (`/ws/projects/{project_id}/deployments/{deployment_id}/logs` and `/status`) and SSE streams for continuous log and state broadcast.

### Layer 5: Persistence, Messaging & Storage
- **PostgreSQL 15 (Source of Truth):**
  - Manages relational metadata across 7 core tables: `users`, `projects`, `project_members`, `deployments`, `builds`, `outbox_events`, and `audit_logs`.
  - Enforces single-active deployment invariant via partial unique index `idx_deployments_one_active_per_project`.
  - Guarantees tamper-evidence on `audit_logs` using PostgreSQL trigger `trg_audit_logs_append_only` which raises an exception on any `UPDATE` or `DELETE`.
  - Automated schema bootstrapping via ArgoCD `PostSync` hook Job `shipzen-schema-bootstrap`.
- **Redis Master (Standalone + AOF EverySec):**
  - Message broker for `deploy_stream` consumer groups.
  - Dead Letter Queue (`deploy_stream_dlq`) for unrecoverable tasks.
  - Pub/Sub channels: `shipzen:events:project_reconcile` (event-driven controller trigger) and `shipzen:logs:{deployment_id}` (real-time worker log broadcast).
- **Google Cloud Storage (GCS):**
  - Bucket `shipzen-build-logs-*`: Durable cold storage for complete build logs with 30-day lifecycle auto-purge.
  - Bucket `shipzen-velero-backups`: Backup repository for Velero cluster state and volume snapshots.
- **Google Cloud Artifact Registry (GAR):**
  - Docker repository `shipzen-builds`: Stores tenant application OCI container images.
  - Docker repository `shipzen-platform`: Stores ShipZen internal system images (`api`, `controller`, `worker`, `ui`).
- **Google Cloud Secret Manager:**
  - Encrypted storage for tenant project secrets (`shipzen-project-{id}`), database credentials, Redis passwords, GitHub App private keys, and TLS origin certificates.

### Layer 6: Asynchronous Worker Engine
- **Worker Daemon (`worker/main.py`):** Multi-threaded background engine processing deployment jobs from Redis Streams using consumer group `worker_group`.
- **Healthz & Metrics Server:** Serves `/healthz` verifying Redis connectivity and main loop tick freshness (< 120s), and `/metrics` exposing Prometheus metrics.
- **Queue Client (`worker/queue_client.py`):** Implements reliable processing with `XREADGROUP`, `XACK`, exponential retry backoff, and DLQ routing after 3 consecutive failures.
- **Finite State Machine (`worker/state_machine.py`):** Governs strict deployment states: `Queued` ➔ `Building` ➔ `Deploying` ➔ `Verifying` ➔ `Running` (or `Failed` / `Retry` / `DLQ`).
- **Concurrency Limiting:** `ThreadPoolExecutor` and `Semaphore` capped at 20 concurrent tasks to prevent memory leaks and database connection pool starvation.
- **Log Streaming Engine:** Watches Kubernetes Pod logs line-by-line via `CoreV1Api`, republishes them to Redis Pub/Sub, and streams the aggregated output directly to GCS upon build completion.

### Layer 7: Ephemeral Builder Subsystem (Isolated Sandbox)
- **Isolation Namespace (`shipzen-build`):** Separate namespace dedicated solely to building container images.
- **Dedicated Node Pool Taint:** Tainted with `shipzen.jeneeldumasia.codes/dedicated=builder:NoSchedule` so untrusted build processes cannot co-locate with control plane or tenant runtime pods.
- **Kyverno Policy Exception:** `shipzen-build-buildkit-exception` grants seccomp `Unconfined` only for `Job` and `Pod` resources in `shipzen-build` to allow Rootless BuildKit unshare/mount calls while strictly denying root privileges.
- **Workload Identity:** Kubernetes ServiceAccount `shipzen-builder-sa` maps to GCP IAM Service Account `shipzen-builder-sa`, granting `roles/artifactregistry.writer` and `roles/storage.objectAdmin` without hardcoded static keys.
- **Pluggable Build Engines:**
  - **InitContainer (`git-clone`):** Clones user repository authenticated using short-lived GitHub App RS256 installation tokens.
  - **`DockerfileBuilder`:** Kaniko executor (`gcr.io/kaniko-project/executor:v1.23.2`) with layer caching (`:cache`).
  - **`NixpacksBuilder`:** Railway Nixpacks (`ghcr.io/railwayapp/nixpacks:latest`) automatically synthesizing multi-language dependencies, building a lightweight Dockerfile, and generating Kaniko jobs.

### Layer 8: Reconciliation Controller Engine (Custom Controller)
- **High-Availability Leader Election (`controller/main.py`):** Uses Kubernetes `coordination.k8s.io/v1` `Lease` named `shipzen-controller-leader` so only the active leader executes reconciliations while standbys remain ready.
- **Dual Reconciliation Trigger:**
  1. **Event-Driven Workqueue:** Instant zero-latency reconciliation via Redis Pub/Sub subscription `shipzen:events:project_reconcile`.
  2. **15-Second Sweeper Loop:** Proactively scans the database to correct drift, prune terminated tenant namespaces, and fail deployments stuck in `Queued` or `Building` state for over 60 minutes.
- **O(1) Global Cluster Listing:** Pre-fetches all cluster Deployments, Services, HTTPRoutes, and Namespaces in single list calls, eliminating Kubernetes API server rate limiting.
- **Jinja2 Manifest Templates:**
  - `tenant.yaml.j2`: Generates isolated namespace, default service account, `ResourceQuota`, `LimitRange`, `NetworkPolicy`, `Role`, `RoleBinding`, and `PodMonitor`.
  - `app-deployment.yaml.j2`: Generates `ExternalSecret`, tenant `Deployment`, `Service`, `HTTPRoute`, and `PodDisruptionBudget`.
- **GitOps Committer (`commit_manifests_to_git`):** Encodes rendered manifests in Base64 and commits them via GitHub REST API to `github.com/jeneeldumasia/shipzen-tenants` under `namespaces/<namespace>/`.
- **Direct Manifest Reconciler (`apply_manifests`):** Concurrently creates or patches Kubernetes resources directly via the Kubernetes Python client for instant user feedback.
- **Artifact Registry Purger (`delete_gar_repository`):** Automatically cleans up tenant image packages in GCP Artifact Registry when a project is deleted.

### Layer 9: GitOps Pipeline & ArgoCD
- **ArgoCD Server (`argocd`):** Installed via Helm with reconciliation timeout tuned to 15s.
- **Platform Application (`shipzen-platform`):** Continuously reconciles the core infrastructure manifests from `ShipZen-GCP.git/infra`.
- **Tenant ApplicationSet (`tenant-namespaces`):**
  - Watches `shipzen-tenants.git` at path `namespaces/*`.
  - Dynamically provisions, updates, and deletes tenant applications based on Git directory contents.
  - Enables `automated: {prune: true, selfHeal: true}` and `CreateNamespace=true`.
  - Configured with `github-app-repo-creds` for private repository access.

### Layer 10: Multi-Tenant Workload Runtime
- **Namespace per Project (`tenant-{project_name}`):**
  - Pod Security Admission: `pod-security.kubernetes.io/enforce: restricted`.
- **Hard Resource Quotas (`ResourceQuota: tenant-quota`):** Capped at 4 requests / 8 limits CPU, 8Gi requests / 16Gi limits RAM, max 20 pods, 10 services.
- **Limit Ranges (`LimitRange: tenant-limit-range`):** Default container limits of 500m CPU / 512Mi RAM, and default requests of 100m CPU / 128Mi RAM.
- **Network Isolation (`NetworkPolicy: tenant-isolation`):**
  - **Ingress:** Denies all traffic except traffic arriving from Envoy Gateway pods in `shipzen-system`.
  - **Egress:** Explicitly denies all private network CIDRs (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`) and blocks the cloud metadata IMDS endpoint `169.254.169.254/32`. Allows public outbound internet and port 53 DNS.
- **Zero-Secret RBAC (`Role: tenant-runner`):** Tenant pods are restricted to reading `ConfigMaps` only; secret reading permissions are strictly removed.
- **Secret Sync (`ExternalSecret`):** Synced from GCP Secret Manager via `ClusterSecretStore` into in-namespace Secret `{{ deployment_name }}-secrets-sync` and mounted as environment variables.
- **Disruption Protection (`PodDisruptionBudget`):** Configured with `maxUnavailable: 1` to permit node consolidation without risking downtime.
- **Prometheus Telemetry (`PodMonitor: tenant-pod-monitor`):** Automatically discovers application metrics on `/metrics`.

### Layer 11: Platform Operators & Security Admission
- **External Secrets Operator (ESO v0.9.20):** Synchronizes secrets from Google Cloud Secret Manager to native Kubernetes secrets using Workload Identity (`shipzen-eso-sa`).
- **KEDA (v2.14.2):** Event-driven autoscaler monitoring Redis Streams queue depth to horizontally autoscale worker pods during deployment bursts.
- **Horizontal Pod Autoscaler (HPA):** Dynamically scales `shipzen-controller` between 2 and 5 replicas based on CPU target (80%).
- **Kyverno Policy Engine:** Enforces admission control rules cluster-wide (`disallow-root-execution`, `drop-all-capabilities`).
- **ExternalDNS (v1.14.3):** Integrates with Cloudflare to automatically create and update DNS CNAME records when new `HTTPRoute` resources are registered.
- **Velero (v7.2.1):** Manages scheduled cluster backups and disaster recovery snapshots to GCS bucket `shipzen-velero-backups`.

### Layer 12: Observability, Metrics, Dashboards & Alerting
- **Prometheus (kube-prometheus-stack):** 30-day metrics retention with persistent 10Gi standard storage, scraping all cluster ServiceMonitors and PodMonitors.
- **Alertmanager:** Dispatches alerts across severity levels (`critical`, `high`, `warning`).
- **PrometheusRules:**
  - `shipzen-platform-alerts`: Triggers on queue backlog (> 100), DLQ growth (> 0), high builder failures, Redis down, PostgreSQL down, Envoy Gateway down, and continuous reconciliation drift.
  - `external-secrets-alerts`: Triggers on `ExternalSecretSyncFailed` and GCP Secret Manager throttling.
  - `shipzen-slos`: Tracks platform availability (> 99.9%), 95th percentile queue latency (< 10s), deployment retry rate (< 5%), and DLQ depth (= 0).
- **Grafana:** Domain `grafana-shipzen.jeneeldumasia.codes`, persistent 2Gi storage, embedding enabled for the ShipZen UI, with automated dashboard discovery sidecar loading `observability/dashboards/grafana-dashboards.yaml`.
- **Loki:** Centralized log storage and indexing for cluster system containers.

### Layer 13: Cloud Infrastructure & Networking (Terraform)
- **VPC & Subnets:** `shipzen-vpc` with private subnet `shipzen-subnet` (10.0.0.0/16), Cloud Router `shipzen-router`, and Cloud NAT `shipzen-nat` for secure outbound internet access without public IPs on cluster nodes.
- **GKE Cluster:** `shipzen-cluster` with Workload Identity enabled (`${gcp_project}.svc.id.goog`).
- **Dedicated Node Pools:**
  - `platform-nodes`: Hosts control plane, operators, and databases.
  - Dedicated Builder Node Pool: Tainted for builder workloads.
  - Dedicated Tenant Node Pool: Tainted for tenant application pods.
- **Workload Identity Federation:** Mappings between Kubernetes ServiceAccounts (`shipzen-builder-sa`, `shipzen-worker-sa`, `shipzen-api-sa`, `shipzen-eso-sa`, `velero`) and Google Cloud Service Accounts.

---

## 4. End-to-End Lifecycle & Data Flows

### Flow A: Deployment Ingestion & Build Pipeline
1. **User Action:** Developer triggers deployment via UI or pushes code to GitHub.
2. **API Ingestion:** `POST /projects/{id}/deployments` verifies project access, creates a record in `deployments` (state: `Queued`), and appends a task to Redis Stream `deploy_stream` via `XADD`.
3. **Queue Ingestion:** Worker consumes task via `XREADGROUP`, transitions state to `Building`, and triggers `builder.py`.
4. **Builder Job Launch:** Worker calls Kubernetes `BatchV1Api` to create Job `build-{deployment_id}` in `shipzen-build`.
5. **InitContainer Execution:** `git-clone` uses a short-lived GitHub App RS256 token to clone the repository to `/workspace`.
6. **Container Build:** Kaniko or Nixpacks compiles source, creates OCI image, and pushes layers directly to GCP Artifact Registry `shipzen-builds`.
7. **Log Collection:** Worker tails pod logs, streams them to Redis Pub/Sub, and uploads complete log file to GCS bucket `shipzen-build-logs-*`.

### Flow B: Dual Reconciliation & GitOps Synchronization
1. **State Update:** Worker updates deployment state in PostgreSQL to `Deploying` and publishes event to Redis Pub/Sub `shipzen:events:project_reconcile`.
2. **Controller Trigger:** Active leader controller receives event, reads desired state from PostgreSQL, and renders Jinja2 templates (`tenant.yaml.j2`, `app-deployment.yaml.j2`).
3. **Fast-Path Apply:** Controller immediately applies/patches Kubernetes manifests (Deployment, Service, HTTPRoute, ExternalSecret) directly to the cluster.
4. **GitOps Commit:** Controller commits rendered YAML manifests to `github.com/jeneeldumasia/shipzen-tenants` (`namespaces/<namespace>/`).
5. **ArgoCD Reconciliation:** ArgoCD ApplicationSet detects Git commit and continuously reconciles, prunes, and self-heals tenant resources.
6. **Health Verification:** Controller verifies pod readiness probes and updates database status to `Running`.

### Flow C: Live Log Telemetry (K8s Watch to WebSockets)
1. **Source:** Ephemeral builder pod writes build stdout/stderr to `/dev/stdout`.
2. **Tail:** Worker container monitoring thread watches the pod via Kubernetes `read_namespaced_pod_log(follow=True)`.
3. **Publish:** Worker publishes each log line to Redis Pub/Sub channel `shipzen:logs:{deployment_id}`.
4. **Forward:** API server WebSocket endpoint `/ws/projects/{project_id}/deployments/{deployment_id}/logs` listens on Redis Pub/Sub and pushes messages directly to the client browser.
5. **Fallback:** If a build has finished, the API transparently retrieves and streams the complete log file from Google Cloud Storage.

### Flow D: Secret Ingestion, Encryption & In-Cluster Sync
1. **Input:** Developer enters environment variables or secrets in Next.js UI (`PUT /projects/{id}/env` or `POST /projects/{id}/secrets`).
2. **GCP Storage:** API writes the secret payload as JSON to GCP Secret Manager under secret name `shipzen-project-{id}`.
3. **ESO Synchronization:** In-cluster External Secrets Operator polls Secret Manager every 1 hour (or upon manual refresh) via Workload Identity.
4. **K8s Secret Generation:** ESO synthesizes Kubernetes secret `{deployment_name}-secrets-sync` inside the tenant namespace.
5. **Pod Injection:** Tenant pods inject secrets as environment variables using `envFrom: secretRef`.

### Flow E: Failure Recovery & Dead Letter Queue (DLQ)
1. **Failure Event:** Build job fails (e.g. exit code 1 or Kaniko timeout at 1800s).
2. **Retry Evaluation:** Worker records failure reason in `deployments.last_error`.
3. **Retry Threshold:** If retry count < 3, deployment state transitions to `Retry` with exponential backoff.
4. **DLQ Routing:** If retry count reaches 3, deployment is marked `Failed`, the task is moved to `deploy_stream_dlq`, and `shipzen_dlq_depth` is incremented.
5. **Prometheus Alert:** `DLQGrowing` alert fires in Alertmanager to notify platform administrators.

---

## 5. Codebase File & Component Cross-Reference

| Architectural Component | Primary Source File(s) | Kubernetes / Cloud Resource |
| :--- | :--- | :--- |
| **Edge & Ingress Routing** | [`infra/system/gateway.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/gateway.yaml) | `Gateway`, `GatewayClass`, `EnvoyProxy`, `HTTPRoute` |
| **Rate Limiting** | [`infra/system/rate-limit.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/rate-limit.yaml) | `BackendTrafficPolicy` (`global-rate-limit`) |
| **API Entry Point & Routes** | [`api/main.py`](file:///home/jeneeld7492/ShipZen-GCP/api/main.py) | `Deployment` `shipzen-api`, `Service` `shipzen-api:8000` |
| **Authentication & RBAC** | [`api/auth.py`](file:///home/jeneeld7492/ShipZen-GCP/api/auth.py) | GitHub OAuth 2.0, Bearer Auth, Circuit Breaker |
| **Repository Detection** | [`api/analyzer.py`](file:///home/jeneeld7492/ShipZen-GCP/api/analyzer.py) | Monorepo analyzer, `shipzen.yaml` validator |
| **Database Pool & DAL** | [`api/database.py`](file:///home/jeneeld7492/ShipZen-GCP/api/database.py) | `ThreadedConnectionPool` |
| **Audit Logger** | [`api/audit.py`](file:///home/jeneeld7492/ShipZen-GCP/api/audit.py) | Table `audit_logs`, trigger `trg_audit_logs_append_only` |
| **Database Schema** | [`api/schema.sql`](file:///home/jeneeld7492/ShipZen-GCP/api/schema.sql) | PostgreSQL 15 schema, indexes, and triggers |
| **Schema Bootstrap Job** | [`infra/system/schema-job.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/schema-job.yaml) | `Job` `shipzen-schema-bootstrap` (ArgoCD `PostSync`) |
| **Frontend UI (Next.js)** | [`ui/src/app/`](file:///home/jeneeld7492/ShipZen-GCP/ui/src/app) | `Deployment` `shipzen-ui`, `Service` `shipzen-ui:3000` |
| **UI NextAuth Config** | [`ui/src/auth.ts`](file:///home/jeneeld7492/ShipZen-GCP/ui/src/auth.ts) | NextAuth OAuth provider configuration |
| **Worker Engine** | [`worker/main.py`](file:///home/jeneeld7492/ShipZen-GCP/worker/main.py) | `Deployment` `shipzen-worker` |
| **Builder Orchestrator** | [`worker/builder.py`](file:///home/jeneeld7492/ShipZen-GCP/worker/builder.py) | `Job` `build-{deployment_id}` (Kaniko / Nixpacks) |
| **Queue & DLQ Client** | [`worker/queue_client.py`](file:///home/jeneeld7492/ShipZen-GCP/worker/queue_client.py) | Redis Stream `deploy_stream`, DLQ `deploy_stream_dlq` |
| **Deployment State Machine**| [`worker/state_machine.py`](file:///home/jeneeld7492/ShipZen-GCP/worker/state_machine.py) | State transitions (`Queued` ➔ `Running`) |
| **Worker Metrics** | [`worker/metrics.py`](file:///home/jeneeld7492/ShipZen-GCP/worker/metrics.py) | Prometheus metrics (`shipzen_build_duration_seconds`, etc.) |
| **Custom Controller** | [`controller/main.py`](file:///home/jeneeld7492/ShipZen-GCP/controller/main.py) | `Deployment` `shipzen-controller` |
| **Leader Election** | [`controller/main.py`](file:///home/jeneeld7492/ShipZen-GCP/controller/main.py#L50-L144) | `Lease` `shipzen-controller-leader` (`coordination.k8s.io`) |
| **Tenant Templates** | [`controller/templates/tenant.yaml.j2`](file:///home/jeneeld7492/ShipZen-GCP/controller/templates/tenant.yaml.j2) | Jinja2 template for isolated tenant namespaces |
| **Workload Templates** | [`controller/templates/app-deployment.yaml.j2`](file:///home/jeneeld7492/ShipZen-GCP/controller/templates/app-deployment.yaml.j2) | Jinja2 template for tenant deployments, services, routes |
| **GitOps Integration** | [`shipzen_common/github_app.py`](file:///home/jeneeld7492/ShipZen-GCP/shipzen_common/github_app.py) | GitHub App RS256 token generator |
| **ArgoCD Tenant Sync** | [`infra/system/applicationset.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/applicationset.yaml) | `ApplicationSet` `tenant-namespaces` |
| **Platform ArgoCD App** | [`argocd-app.yaml`](file:///home/jeneeld7492/ShipZen-GCP/argocd-app.yaml) | `Application` `shipzen-platform` |
| **Kyverno Admission Policy**| [`terraform/security.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/security.tf) | `PolicyException` `shipzen-build-buildkit-exception` |
| **External Secrets (ESO)** | [`terraform/operators.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/operators.tf#L98-L154) | `ClusterSecretStore` `gcp-secret-manager` |
| **Service Monitors** | [`infra/system/servicemonitors.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/servicemonitors.yaml) | `ServiceMonitor` for API, Worker, and Controller |
| **Platform Alert Rules** | [`observability/alerts/platform-alerts.yaml`](file:///home/jeneeld7492/ShipZen-GCP/observability/alerts/platform-alerts.yaml) | `PrometheusRule` `shipzen-platform-alerts` |
| **SLO Tracking Rules** | [`observability/slos.yaml`](file:///home/jeneeld7492/ShipZen-GCP/observability/slos.yaml) | `PrometheusRule` `shipzen-slos` |
| **Grafana Dashboards** | [`observability/dashboards/grafana-dashboards.yaml`](file:///home/jeneeld7492/ShipZen-GCP/observability/dashboards/grafana-dashboards.yaml) | `ConfigMap` `shipzen-grafana-dashboards` |
| **Loki Log Aggregator** | [`infra/system/loki.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/system/loki.yaml) | `StatefulSet` `loki` |
| **Disaster Recovery Backup**| [`terraform/backups.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/backups.tf) | Velero operator, GCS bucket `shipzen-velero-backups` |
| **Terraform IaC (Main)** | [`terraform/main.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/main.tf) | GKE Cluster, VPC, Subnets, Cloud Storage, Artifact Registry |
| **Database Terraform** | [`terraform/postgres.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/postgres.tf) | Cloud SQL PostgreSQL / Bitnami Helm PostgreSQL |
| **Redis Terraform** | [`terraform/redis.tf`](file:///home/jeneeld7492/ShipZen-GCP/terraform/redis.tf) | Bitnami Redis Helm chart, Secret Manager password |
| **Autoscaling (HPA)** | [`infra/scale/hpa.yaml`](file:///home/jeneeld7492/ShipZen-GCP/infra/scale/hpa.yaml) | `HorizontalPodAutoscaler` `shipzen-controller-hpa` |

---
