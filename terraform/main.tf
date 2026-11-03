terraform {
  cloud {
    organization = "jeneel-shipzen"
    workspaces {
      name = "ShipZen-GCP"
    }
  }
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Enable required GCP APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "iamcredentials.googleapis.com",    # For Workload Identity Federation
    "servicenetworking.googleapis.com", # For Cloud SQL private VPC connection
  ])

  project            = var.gcp_project
  service            = each.key
  disable_on_destroy = false
}

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "shipzen-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "subnet" {
  name          = "shipzen-subnet"
  region        = var.gcp_region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.0.0.0/16"
}

resource "google_compute_router" "router" {
  name    = "shipzen-router"
  region  = var.gcp_region
  network = google_compute_network.vpc.name
}

resource "google_compute_router_nat" "nat" {
  name                               = "shipzen-nat"
  router                             = google_compute_router.router.name
  region                             = var.gcp_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# ── GKE ───────────────────────────────────────────────────────────────────────
resource "google_container_cluster" "primary" {
  name = "shipzen-cluster"
  # Zonal cluster: GKE's free tier covers one zonal control plane, a regional one
  # costs $0.10/hour. The nodes were already single-zone. Changing this forces a
  # new cluster, so it takes effect on the next Deploy Platform Infra.
  location   = var.gcp_zone
  network    = google_compute_network.vpc.name
  subnetwork = google_compute_subnetwork.subnet.name

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false # Prevent accidental cluster destruction

  # Workload Identity enabled for the cluster
  workload_identity_config {
    workload_pool = "${var.gcp_project}.svc.id.goog"
  }

  # GKE Dataplane V2 (eBPF/Cilium): enforces the NetworkPolicies in infra/ and
  # in every tenant namespace. Without it they are accepted but do nothing.
  datapath_provider = "ADVANCED_DATAPATH"

  lifecycle {
    # Switching the datapath requires a new cluster. Ignore it on an existing
    # cluster so "Apply Infrastructure Changes" never replaces a live cluster;
    # the next Deploy Platform Infra (after a teardown) creates it with Dataplane V2.
    ignore_changes = [datapath_provider]
  }

  depends_on = [google_project_service.apis]
}

resource "google_container_node_pool" "platform_nodes" {
  name       = "platform-nodes"
  location   = var.gcp_zone
  cluster    = google_container_cluster.primary.name
  node_count = 1 # Single zone, 1 node total for dev

  autoscaling {
    min_node_count = 1 # Single zone
    max_node_count = 3 # Single zone, max 3 nodes total for burst
  }

  node_config {
    machine_type    = var.platform_machine_type
    disk_size_gb    = 50            # Smaller disk to save costs
    disk_type       = "pd-standard" # Standard HDD instead of SSD
    service_account = google_service_account.node_sa.email

    labels = {
      "shipzen.jeneeldumasia.codes/node-type" = "platform"
    }

    # Enable Workload Identity
    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    # OAuth scopes for node service account
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform", # Full GCP API access (includes GAR)
    ]

    # Use spot instances for even more savings (optional, can be preempted)
    # spot = true
  }
  depends_on = [google_project_iam_member.node_sa_roles]
}

resource "google_service_account" "node_sa" {
  account_id   = "shipzen-node-sa"
  display_name = "ShipZen GKE Node Service Account"
}

resource "google_project_iam_member" "node_sa_roles" {
  for_each = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer"
  ])
  project = var.gcp_project
  role    = each.key
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

data "google_client_config" "default" {}

provider "kubernetes" {
  host                   = "https://${google_container_cluster.primary.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth.0.cluster_ca_certificate)
}

resource "time_sleep" "wait_for_cluster_auth" {
  depends_on      = [google_container_node_pool.platform_nodes]
  create_duration = "60s"
}

# ── Artifact Registry ─────────────────────────────────────────────────────────
resource "google_artifact_registry_repository" "shipzen_builds" {
  location      = var.gcp_region
  repository_id = "shipzen-builds"
  description   = "Verified tenant images. Only the platform writes here; apps run them by digest."
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# Build output lands here first. Builds run untrusted Dockerfiles and can push
# here and nowhere else; the worker then copies the exact digest each build
# reported into shipzen-builds (security finding C4). Images only need to live
# until that copy, so they're deleted after a day.
resource "google_artifact_registry_repository" "shipzen_staging" {
  location      = var.gcp_region
  repository_id = "shipzen-staging"
  description   = "Untrusted build output, copied by digest to shipzen-builds"
  format        = "DOCKER"

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "delete-after-a-day"
    action = "DELETE"
    condition {
      older_than = "86400s"
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "platform" {
  location      = var.gcp_region
  repository_id = "shipzen-platform"
  description   = "Docker repository for ShipZen platform services"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ── GCS Bucket for Build Logs ─────────────────────────────────────────────────
# The name is deterministic (project-scoped, like the Velero bucket). A random
# suffix made every lost-state redeploy create a NEW bucket and strand the old
# one; a fixed name lets scripts/adopt-orphaned-resources.sh re-import it.
resource "google_storage_bucket" "build_logs" {
  name                        = "${var.gcp_project}-build-logs"
  location                    = var.gcp_region
  force_destroy               = true
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
  depends_on = [google_project_service.apis]
}

# ── Workload Identity: Builder SA ─────────────────────────────────────────────
# Push-only identity for builds, which run untrusted user Dockerfiles. Build
# pods no longer get it through Workload Identity (any RUN step could read it
# from the metadata server, and build pods can't reach that server any more):
# the worker mints a 1-hour token for it per build and hands Kaniko only that.
# It can push to shipzen-staging and do nothing else.
resource "google_service_account" "builder_sa" {
  account_id   = "shipzen-builder-sa"
  display_name = "ShipZen Builder (push to shipzen-staging only)"
}

resource "google_artifact_registry_repository_iam_member" "builder_push" {
  project    = var.gcp_project
  location   = google_artifact_registry_repository.shipzen_staging.location
  repository = google_artifact_registry_repository.shipzen_staging.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder_sa.email}"
}

# ── Workload Identity: Platform SA ────────────────────────────────────────────
# Used by ShipZen's own services (API, worker, controller).
#   API:        creates/updates/deletes per-project secrets; reads build logs
#   worker:     writes build logs; reads image config from shipzen-builds
#   controller: ensures/deletes project secrets; deletes images of deleted projects
resource "google_service_account" "platform_sa" {
  account_id   = "shipzen-platform-sa"
  display_name = "ShipZen Platform Services (API, worker, controller)"
}

resource "google_project_iam_member" "platform_secret_manager" {
  project = var.gcp_project
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.platform_sa.email}"
}

resource "google_storage_bucket_iam_member" "platform_build_logs" {
  bucket = google_storage_bucket.build_logs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.platform_sa.email}"
}

# The worker reads staging to copy verified digests into shipzen-builds, and
# mints the short-lived builder tokens it gives to each build.
resource "google_artifact_registry_repository_iam_member" "platform_staging_reader" {
  project    = var.gcp_project
  location   = google_artifact_registry_repository.shipzen_staging.location
  repository = google_artifact_registry_repository.shipzen_staging.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.platform_sa.email}"
}

resource "google_service_account_iam_member" "platform_mints_builder_tokens" {
  service_account_id = google_service_account.builder_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.platform_sa.email}"
}

resource "google_artifact_registry_repository_iam_member" "platform_builds_admin" {
  project    = var.gcp_project
  location   = google_artifact_registry_repository.shipzen_builds.location
  repository = google_artifact_registry_repository.shipzen_builds.name
  role       = "roles/artifactregistry.repoAdmin"
  member     = "serviceAccount:${google_service_account.platform_sa.email}"
}

resource "google_service_account_iam_binding" "platform_workload_identity" {
  service_account_id = google_service_account.platform_sa.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-system/shipzen-worker-sa]",
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-system/shipzen-api-sa]",
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-system/shipzen-controller-sa]",
  ]
}

resource "kubernetes_namespace" "shipzen_system" {
  depends_on = [time_sleep.wait_for_cluster_auth]
  metadata {
    name = "shipzen-system"
  }
}

resource "kubernetes_namespace" "shipzen_build" {
  depends_on = [time_sleep.wait_for_cluster_auth]
  metadata {
    name = "shipzen-build"
  }
}

# The Kubernetes identity build pods run as. Deliberately no Google identity
# (no Workload Identity annotation) and no Kubernetes API token.
resource "kubernetes_service_account" "builder_k8s_sa" {
  metadata {
    name      = "shipzen-builder-sa"
    namespace = kubernetes_namespace.shipzen_build.metadata[0].name
  }
  automount_service_account_token = false
}

resource "kubernetes_service_account" "worker_k8s_sa" {
  metadata {
    name      = "shipzen-worker-sa"
    namespace = kubernetes_namespace.shipzen_system.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.platform_sa.email
    }
  }
  automount_service_account_token = true
}

resource "kubernetes_service_account" "api_k8s_sa" {
  metadata {
    name      = "shipzen-api-sa"
    namespace = kubernetes_namespace.shipzen_system.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.platform_sa.email
    }
  }
  automount_service_account_token = true
}

resource "kubernetes_service_account" "controller_k8s_sa" {
  metadata {
    name      = "shipzen-controller-sa"
    namespace = kubernetes_namespace.shipzen_system.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.platform_sa.email
    }
  }
  automount_service_account_token = true
}

# ── Cloudflare Origin CA Certificate ──────────────────────────────────────────
resource "tls_private_key" "origin_cert" {
  algorithm = "RSA"
}

resource "tls_cert_request" "origin_cert" {
  private_key_pem = tls_private_key.origin_cert.private_key_pem
  subject {
    common_name  = "shipzen.jeneeldumasia.codes"
    organization = "ShipZen"
  }
}

resource "cloudflare_origin_ca_certificate" "origin_cert" {
  csr                = tls_cert_request.origin_cert.cert_request_pem
  hostnames          = ["*.shipzen.jeneeldumasia.codes", "shipzen.jeneeldumasia.codes"]
  request_type       = "origin-rsa"
  requested_validity = 5475 # 15 years
}

resource "google_secret_manager_secret" "cloudflare_origin_cert" {
  secret_id = "shipzen-cloudflare-origin-cert"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "cloudflare_origin_cert" {
  secret = google_secret_manager_secret.cloudflare_origin_cert.id
  secret_data = jsonencode({
    "cert" = cloudflare_origin_ca_certificate.origin_cert.certificate
    "key"  = tls_private_key.origin_cert.private_key_pem
  })
}

# Allow external secrets operator / cert-manager to read it
resource "google_secret_manager_secret_iam_member" "cert_access" {
  secret_id = google_secret_manager_secret.cloudflare_origin_cert.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.platform_sa.email}"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "gcp_project" {
  value = var.gcp_project
}

output "gar_repository_url" {
  description = "Artifact Registry repository URL for built tenant images"
  value       = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.shipzen_builds.repository_id}"
}

output "build_logs_bucket_name" {
  description = "GCS bucket name for build logs"
  value       = google_storage_bucket.build_logs.name
}

output "cluster_endpoint" {
  description = "GKE cluster endpoint"
  value       = google_container_cluster.primary.endpoint
}
