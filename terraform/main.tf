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
    "iamcredentials.googleapis.com", # For Workload Identity Federation
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
  name           = "shipzen-cluster"
  location       = var.gcp_region
  node_locations = ["us-central1-a"] # Single zone for dev (was 3 zones)
  network        = google_compute_network.vpc.name
  subnetwork     = google_compute_subnetwork.subnet.name

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false # Prevent accidental cluster destruction

  # Workload Identity enabled for the cluster
  workload_identity_config {
    workload_pool = "${var.gcp_project}.svc.id.goog"
  }

  depends_on = [google_project_service.apis]
}

resource "google_container_node_pool" "platform_nodes" {
  name       = "platform-nodes"
  location   = var.gcp_region
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
  description   = "Docker repository for ShipZen tenant builds"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "platform" {
  location      = var.gcp_region
  repository_id = "shipzen-platform"
  description   = "Docker repository for ShipZen platform services"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ── GCS Bucket for Build Logs ─────────────────────────────────────────────────
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "build_logs" {
  name                        = "shipzen-build-logs-${random_id.bucket_suffix.hex}"
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
resource "google_service_account" "builder_sa" {
  account_id   = "shipzen-builder-sa"
  display_name = "ShipZen Builder Service Account"
}

resource "google_project_iam_member" "builder_ar_writer" {
  project = var.gcp_project
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.builder_sa.email}"
}

resource "google_project_iam_member" "builder_gcs_writer" {
  project = var.gcp_project
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.builder_sa.email}"
}

resource "google_service_account_iam_binding" "builder_workload_identity" {
  service_account_id = google_service_account.builder_sa.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-build/shipzen-builder-sa]",
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-system/shipzen-worker-sa]",
    "serviceAccount:${var.gcp_project}.svc.id.goog[shipzen-system/shipzen-api-sa]"
  ]
}

resource "kubernetes_namespace" "shipzen_build" {
  depends_on = [time_sleep.wait_for_cluster_auth]
  metadata {
    name = "shipzen-build"
  }
}

resource "kubernetes_service_account" "builder_k8s_sa" {
  metadata {
    name      = "shipzen-builder-sa"
    namespace = kubernetes_namespace.shipzen_build.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.builder_sa.email
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
  member    = "serviceAccount:${google_service_account.builder_sa.email}" # Reusing builder_sa for simplicity in this migration
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
