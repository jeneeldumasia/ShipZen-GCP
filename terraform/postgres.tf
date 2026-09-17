resource "random_password" "pg_password" {
  length           = 32
  special          = true
  override_special = "!#%&*()-_=+[]{}<>:?"
}

locals {
  pg_database = "shipzen"
  pg_username = "shipzen"
  pg_password = var.pg_password != "" ? var.pg_password : random_password.pg_password.result
  pg_host     = var.use_cloud_sql ? google_sql_database_instance.postgres[0].private_ip_address : "postgres-postgresql.shipzen-system.svc.cluster.local"
  pg_port     = 5432
}

# ── Cloud SQL PostgreSQL ──────────────────────────────────────────────────────
resource "google_compute_global_address" "private_ip_address" {
  count         = var.use_cloud_sql ? 1 : 0
  name          = "shipzen-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  count                   = var.use_cloud_sql ? 1 : 0
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_address[0].name]
}

resource "google_sql_database_instance" "postgres" {
  count            = var.use_cloud_sql ? 1 : 0
  name             = "shipzen-postgres"
  database_version = "POSTGRES_15"
  region           = var.gcp_region

  settings {
    tier = var.cloud_sql_tier
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
  }

  deletion_protection = false
  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_user" "users" {
  count    = var.use_cloud_sql ? 1 : 0
  name     = local.pg_username
  instance = google_sql_database_instance.postgres[0].name
  password = local.pg_password
}

resource "google_sql_database" "database" {
  count    = var.use_cloud_sql ? 1 : 0
  name     = local.pg_database
  instance = google_sql_database_instance.postgres[0].name
}

# ── In-Cluster PostgreSQL (Helm fallback) ─────────────────────────────────────
resource "helm_release" "postgresql" {
  count            = var.use_cloud_sql ? 0 : 1
  name             = "postgres"
  repository       = "oci://registry-1.docker.io/bitnamicharts"
  chart            = "postgresql"
  version          = "18.7.3"
  namespace        = "shipzen-system"
  create_namespace = true

  set {
    name  = "auth.database"
    value = local.pg_database
  }

  set {
    name  = "auth.username"
    value = local.pg_username
  }

  set {
    name  = "auth.password"
    value = local.pg_password
  }

  set {
    name  = "auth.postgresPassword"
    value = local.pg_password
  }

  set {
    name  = "primary.persistence.enabled"
    value = "true"
  }

  set {
    name  = "primary.persistence.size"
    value = "10Gi"
  }

  set {
    name  = "readReplicas.replicaCount"
    value = "0"
  }

  timeout = 900
  depends_on = [time_sleep.wait_for_cluster_auth]
}

# Full DATABASE_URL connection string — all services mount this as an env var.
resource "kubernetes_secret" "db_credentials" {
  metadata {
    name      = "shipzen-db-credentials"
    namespace = "shipzen-system"
  }

  data = {
    url = "postgresql://${local.pg_username}:${replace(local.pg_password, "@", "%40")}@${local.pg_host}:${local.pg_port}/${local.pg_database}"
  }

  depends_on = [kubernetes_namespace.shipzen_system, time_sleep.wait_for_cluster_auth]
}

# Duplicate DB credentials into the shipzen-build namespace for the builder pods
resource "kubernetes_secret" "db_credentials_build" {
  metadata {
    name      = "shipzen-db-credentials"
    namespace = "shipzen-build"
  }

  data = {
    url = "postgresql://${local.pg_username}:${replace(local.pg_password, "@", "%40")}@${local.pg_host}:${local.pg_port}/${local.pg_database}"
  }

  depends_on = [kubernetes_namespace.shipzen_build, time_sleep.wait_for_cluster_auth]
}
