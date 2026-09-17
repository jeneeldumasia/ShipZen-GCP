# ── Artifact Registry Config Secrets ──────────────────────────────────────────
# These secrets contain GAR repository URLs and registry hostnames needed by the
# API, Controller, and Builder pods

locals {
  gar_registry_hostname = "${var.gcp_region}-docker.pkg.dev"
  gar_repository_url    = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.shipzen_builds.repository_id}"
}

# Create shipzen-system namespace if it doesn't exist
resource "kubernetes_namespace" "shipzen_system" {
  depends_on = [time_sleep.wait_for_cluster_auth]
  metadata {
    name = "shipzen-system"
  }
}

# Secret for shipzen-system namespace (API & Controller)
resource "kubernetes_secret" "gar_config" {
  metadata {
    name      = "shipzen-gar-config"
    namespace = "shipzen-system"
  }

  data = {
    registry_hostname = local.gar_registry_hostname
    repository_url    = local.gar_repository_url
    project_id        = var.gcp_project
  }

  depends_on = [kubernetes_namespace.shipzen_system, time_sleep.wait_for_cluster_auth]
}

# Duplicate GAR config into the shipzen-build namespace for builder pods
resource "kubernetes_secret" "gar_config_build" {
  metadata {
    name      = "shipzen-gar-config"
    namespace = "shipzen-build"
  }

  data = {
    registry_hostname = local.gar_registry_hostname
    repository_url    = local.gar_repository_url
    project_id        = var.gcp_project
  }

  depends_on = [kubernetes_namespace.shipzen_build, time_sleep.wait_for_cluster_auth]
}

# ── GCS Build Logs Config ──────────────────────────────────────────────────────
# Secret containing the GCS bucket name for build logs

resource "kubernetes_secret" "gcs_config" {
  metadata {
    name      = "shipzen-gcs-config"
    namespace = "shipzen-system"
  }

  data = {
    bucket_name = google_storage_bucket.build_logs.name
  }

  depends_on = [kubernetes_namespace.shipzen_system, time_sleep.wait_for_cluster_auth]
}

# Duplicate GCS config into the shipzen-build namespace for builder pods
resource "kubernetes_secret" "gcs_config_build" {
  metadata {
    name      = "shipzen-gcs-config"
    namespace = "shipzen-build"
  }

  data = {
    bucket_name = google_storage_bucket.build_logs.name
  }

  depends_on = [kubernetes_namespace.shipzen_build, time_sleep.wait_for_cluster_auth]
}
