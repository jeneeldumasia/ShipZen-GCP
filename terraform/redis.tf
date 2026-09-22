resource "random_password" "redis_password" {
  length  = 32
  special = false
}

locals {
  redis_password = var.redis_password != "" ? var.redis_password : random_password.redis_password.result
}

resource "google_secret_manager_secret" "redis_password" {
  secret_id = "shipzen-redis-password"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "redis_password" {
  secret      = google_secret_manager_secret.redis_password.id
  secret_data = local.redis_password
}

# The ExternalSecret yaml needs to be adapted for GCP Secret Manager if ESO is used.
# For this migration, we'll provision the Kubernetes secret directly to avoid ESO complexities.
resource "kubernetes_secret" "redis_auth" {
  metadata {
    name      = "redis-auth"
    namespace = kubernetes_namespace.shipzen_system.metadata[0].name
  }
  data = {
    "redis-password" = local.redis_password
  }
  depends_on = [
    time_sleep.wait_for_cluster_auth,
    helm_release.postgresql
  ]
}

resource "helm_release" "redis" {
  name             = "redis"
  repository       = "oci://registry-1.docker.io/bitnamicharts"
  chart            = "redis"
  version          = "27.0.8"
  namespace        = kubernetes_namespace.shipzen_system.metadata[0].name
  create_namespace = false

  # Add retries for transient API server errors
  wait          = true
  wait_for_jobs = true
  timeout       = 900

  # Disable hooks that can fail during high load
  disable_webhooks = true

  set {
    name  = "architecture"
    value = "standalone"
  }

  set {
    name  = "master.persistence.enabled"
    value = "true"
  }

  set {
    name  = "master.persistence.size"
    value = "2Gi"
  }

  # AOF persistence: fsync every second — at most 1s of data loss on crash.
  # This is the correct minimum for a queue/message-broker workload.
  set {
    name  = "master.extraFlags[0]"
    value = "--appendonly yes"
  }

  set {
    name  = "master.extraFlags[1]"
    value = "--appendfsync everysec"
  }

  set {
    name  = "auth.enabled"
    value = "true"
  }

  set {
    name  = "auth.existingSecret"
    value = "redis-auth"
  }

  set {
    name  = "auth.existingSecretPasswordKey"
    value = "redis-password"
  }

  set {
    name  = "master.service.name"
    value = "redis-master"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, kubernetes_secret.redis_auth]
}
