# ── Runtime Security (Kyverno) ────────────────────────────────────────────────
# Google-level runtime security requires admission controllers.
# Kyverno enforces policies like "No root pods" or "Images must come from ECR".

resource "helm_release" "kyverno" {
  name             = "kyverno"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno"
  namespace        = "kyverno"
  create_namespace = true
  wait             = true

  values = [
    yamlencode({
      installCRDs = true
      features = {
        policyExceptions = {
          enabled = true
        }
      }
      config = {
        resourceFilters = [
          "[Event,*,*]",
          "[*/*,kube-system,*]",
          "[*/*,kube-public,*]",
          "[*/*,kube-node-lease,*]",
          "[Node,*,*]",
          "[*/*,observability,*]",
          "[*/*,velero,*]"
        ]
      }
    })
  ]

  depends_on = [time_sleep.wait_for_cluster_auth]
}

resource "helm_release" "kyverno_policies" {
  name       = "kyverno-policies"
  repository = "https://kyverno.github.io/kyverno/"
  chart      = "kyverno-policies"
  namespace  = "kyverno"

  create_namespace = true

  values = [
    yamlencode({
      # Global: enforce all policies cluster-wide.
      # Exceptions are handled via PolicyException resources below —
      # validationFailureActionOverrides only applies to the legacy
      # kyverno.io/v1 ClusterPolicy CRD. It has NO effect on the newer
      # policies.kyverno.io/v1alpha1 ValidatingPolicy resources that this
      # chart now installs. Use PolicyException instead.
      validationFailureAction = "Enforce"
    })
  ]

  depends_on = [helm_release.kyverno]
}

# ── Builder Namespace PolicyException ─────────────────────────────────────────
# Rootless BuildKit (moby/buildkit:master-rootless) calls unshare() and mount()
# for nested containerisation. These syscalls are blocked by RuntimeDefault
# seccomp, so BuildKit containers must use Unconfined seccomp.
#
# PolicyException is the correct mechanism for both kyverno.io/v1 ClusterPolicy
# AND the newer policies.kyverno.io/v1alpha1 ValidatingPolicy resources.
# Scope: shipzen-build namespace only, builder Jobs only.
# Privileged mode is NOT granted — only seccomp relaxation.
resource "null_resource" "kyverno_builder_exception" {
  triggers = {
    kyverno_ready = helm_release.kyverno_policies.status
  }

  provisioner "local-exec" {
    command = <<-EOF
      kubectl apply -f - <<'YAML'
      apiVersion: kyverno.io/v2
      kind: PolicyException
      metadata:
        name: shipzen-build-buildkit-exception
        namespace: shipzen-build
        annotations:
          shipzen.io/reason: >
            Rootless BuildKit requires Unconfined seccomp to call unshare() and
            mount() for nested container builds. Scoped to builder Jobs in
            shipzen-build only. Privileged mode is NOT granted.
      spec:
        exceptions:
          - policyName: restrict-seccomp
            ruleNames:
              - check-seccomp
              - check-seccomp-strict
        match:
          any:
            - resources:
                kinds:
                  - Job
                  - Pod
                namespaces:
                  - shipzen-build
                selector:
                  matchLabels:
                    shipzen.jeneeldumasia.codes/tier: dockerfile
            - resources:
                kinds:
                  - Job
                  - Pod
                namespaces:
                  - shipzen-build
                selector:
                  matchLabels:
                    shipzen.jeneeldumasia.codes/tier: nixpacks
      YAML
    EOF
  }

  depends_on = [helm_release.kyverno_policies, null_resource.cluster_secret_store]
}
