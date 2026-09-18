# Task 3 — Cluster Operators
# KEDA, External Secrets Operator
# All depend on GKE being ready.

# ── KEDA ────────────────────────────────────────────────────────────────────
resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.14.2"
  namespace        = "keda"
  create_namespace = true

  depends_on = [time_sleep.wait_for_cluster_auth]
}

# ── External Secrets Operator ────────────────────────────────────────────────
resource "google_service_account" "eso_sa" {
  account_id   = "shipzen-eso-sa"
  display_name = "ShipZen External Secrets Operator Service Account"
}

resource "google_project_iam_member" "eso_secrets_accessor" {
  project = var.gcp_project
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.eso_sa.email}"
}

resource "google_service_account_iam_binding" "eso_workload_identity" {
  service_account_id = google_service_account.eso_sa.name
  role               = "roles/iam.workloadIdentityUser"
  members = [
    "serviceAccount:${var.gcp_project}.svc.id.goog[external-secrets/external-secrets-sa]"
  ]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = "0.9.20"
  namespace        = "external-secrets"
  create_namespace = true
  wait             = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "external-secrets-sa"
  }

  set {
    name  = "serviceAccount.annotations.iam\\.gke\\.io/gcp-service-account"
    value = google_service_account.eso_sa.email
  }

  depends_on = [time_sleep.wait_for_cluster_auth]
}

# ── Gateway API CRDs ─────────────────────────────────────────────────────────
resource "null_resource" "gateway_api_crds" {
  triggers = {
    cluster_name = google_container_cluster.primary.name
  }
  provisioner "local-exec" {
    command = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.gcp_region} --project ${var.gcp_project} && kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml"
  }
  depends_on = [time_sleep.wait_for_cluster_auth]
}

# ── Envoy Gateway ────────────────────────────────────────────────────────────
resource "helm_release" "envoy_gateway" {
  name             = "eg"
  repository       = "oci://docker.io/envoyproxy"
  chart            = "gateway-helm"
  version          = "v1.1.2"
  namespace        = "envoy-gateway-system"
  create_namespace = true

  depends_on = [time_sleep.wait_for_cluster_auth, null_resource.gateway_api_crds]
}

# ── ClusterSecretStore (ESO) ──────────────────────────────────────────────────
resource "time_sleep" "wait_for_eso_crds" {
  depends_on      = [helm_release.external_secrets]
  create_duration = "60s"
}

resource "null_resource" "cluster_secret_store" {
  triggers = {
    always_run = "${timestamp()}"
  }
  provisioner "local-exec" {
    command = <<EOT
      gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.gcp_region} --project ${var.gcp_project}
      
      echo "Waiting for ClusterSecretStore CRD to be registered..."
      until kubectl get crd clustersecretstores.external-secrets.io >/dev/null 2>&1; do
        echo "Waiting for CRD..."
        sleep 5
      done
      kubectl wait --for condition=established --timeout=120s crd/clustersecretstores.external-secrets.io

      echo "Waiting for API server to serve the new CRD endpoint..."
      until kubectl get clustersecretstores.external-secrets.io >/dev/null 2>&1; do
        echo "Waiting for endpoint..."
        sleep 5
      done

      rm -rf ~/.kube/cache

      MAX_RETRIES=24
      RETRY_COUNT=0
      until cat <<EOF | kubectl apply --server-side -f -
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: gcp-secret-manager
spec:
  provider:
    gcpsm:
      projectID: "${var.gcp_project}"
EOF
      do
        RETRY_COUNT=$((RETRY_COUNT+1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
          echo "Failed to apply ClusterSecretStore after $MAX_RETRIES attempts."
          exit 1
        fi
        echo "Retrying kubectl apply (attempt $RETRY_COUNT/$MAX_RETRIES)..."
        sleep 5
      done
EOT
  }
  depends_on = [time_sleep.wait_for_eso_crds]
}

# ── ExternalDNS ──────────────────────────────────────────────────────────────
resource "helm_release" "external_dns" {
  name             = "external-dns"
  repository       = "https://kubernetes-sigs.github.io/external-dns/"
  chart            = "external-dns"
  version          = "1.14.3"
  namespace        = "external-dns"
  create_namespace = true

  set {
    name  = "provider"
    value = "cloudflare"
  }

  set_sensitive {
    name  = "env[0].name"
    value = "CF_API_TOKEN"
  }

  set_sensitive {
    name  = "env[0].value"
    value = var.cloudflare_api_token
  }

  set {
    name  = "sources[0]"
    value = "service"
  }

  set {
    name  = "sources[1]"
    value = "ingress"
  }

  set {
    name  = "sources[2]"
    value = "gateway-httproute"
  }

  set {
    name  = "domainFilters[0]"
    value = "jeneeldumasia.codes"
  }

  # Ensure it doesn't conflict with other deployments on the same domain
  set {
    name  = "txtOwnerId"
    value = "shipzen-cluster"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, null_resource.gateway_api_crds]
}
