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
    namespace = "shipzen-system"
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
  namespace        = "shipzen-system"
  create_namespace = true

  set {
    name  = "architecture"
    value = "standalone"
  }

  set {
    name  = "master.persistence.enabled"
    value = "false"
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
