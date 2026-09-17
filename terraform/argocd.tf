provider "helm" {
  kubernetes {
    host                   = "https://${google_container_cluster.primary.endpoint}"
    token                  = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth.0.cluster_ca_certificate)
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true

  set {
    name  = "configs.cm.timeout\\.reconciliation"
    value = "15s"
  }

  set {
    name  = "server.extraArgs[0]"
    value = "--insecure"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, helm_release.kube_prometheus_stack]
}

# Configure ArgoCD with GitHub App credentials (preferred method)
resource "null_resource" "argocd_github_app" {
  count = var.github_app_id != "" ? 1 : 0
  
  provisioner "local-exec" {
    command = <<EOT
      gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.gcp_region} --project ${var.gcp_project}
      
      # Create GitHub App credentials for ArgoCD
      kubectl create secret generic github-app-shipzen -n argocd \
        --from-literal=type=git \
        --from-literal=url=https://github.com/jeneeldumasia \
        --from-literal=githubAppID=${var.github_app_id} \
        --from-literal=githubAppInstallationID=${var.github_app_installation_id} \
        --from-literal=githubAppPrivateKey="${var.github_app_private_key}" \
        --dry-run=client -o yaml | kubectl apply -f -
      
      kubectl label secret github-app-shipzen -n argocd argocd.argoproj.io/secret-type=repository --overwrite
    EOT
  }
  
  depends_on = [helm_release.argocd]
}

resource "null_resource" "argocd_apps" {
  triggers = {
    always_run = "${timestamp()}"
  }
  provisioner "local-exec" {
    command = <<EOT
      gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.gcp_region} --project ${var.gcp_project}
      cat <<EOF | kubectl apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shipzen-platform
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "git@github.com:jeneeldumasia/ShipZen-GCP.git"
    targetRevision: HEAD
    path: infra
  destination:
    server: https://kubernetes.default.svc
    namespace: shipzen-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - RespectIgnoreDifferences=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: shipzen-builder
      namespace: shipzen-build
      jsonPointers:
        - /spec/replicas
EOF
EOT
  }
  depends_on = [
    helm_release.argocd,
    helm_release.envoy_gateway,
    helm_release.external_secrets
  ]
}
