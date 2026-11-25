# ── Runtime Security (Kyverno) ────────────────────────────────────────────────
# Google-level runtime security requires admission controllers.
# Kyverno enforces policies like "No root pods" or "Images must come from ECR".

resource "helm_release" "kyverno" {
  name             = "kyverno"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno"
  # Pinned: Kyverno 1.20 (12 Nov 2026) no longer runs kyverno.io ClusterPolicy
  # or PolicyException, which is everything in infra/system/tenant-policies.yaml
  # and the exceptions. Chart 3.8.1 = Kyverno 1.18.1, the newest line that still
  # enforces them. Unpin only after migrating to policies.kyverno.io (roadmap).
  version          = "3.8.1"
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
  version    = "3.8.1" # same release line as the kyverno chart above
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
      # CEL-based ValidatingPolicy instead of the legacy ClusterPolicy, which
      # Kyverno 1.20 no longer runs (needs Kyverno 1.17+). The exceptions in
      # infra/system/*exception*.yaml refer to these policies by name.
      policyType = "ValidatingPolicy"
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
      apiVersion: policies.kyverno.io/v1
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
        policyRefs:
          - name: restrict-seccomp
            kind: ValidatingPolicy
        matchConditions:
          - name: match-builder-jobs
            expression: >
              object.kind == 'Job' || object.kind == 'Pod'
      YAML
    EOF
  }

  depends_on = [helm_release.kyverno_policies, null_resource.cluster_secret_store]
}
