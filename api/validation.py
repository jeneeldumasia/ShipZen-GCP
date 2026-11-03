"""Input rules shared by the API's request models and endpoints."""
import re

# Repo URL allowlist — same pattern used in builder/main.py
# MED-03 Fix: Use \A and \Z anchors to prevent newline injection
_REPO_URL_RE = re.compile(
    r'\A(https://[a-zA-Z0-9._/:\-@]+\.git'
    r'|https://[a-zA-Z0-9._/:\-@]+'
    r'|git@[a-zA-Z0-9._\-]+:[a-zA-Z0-9._/\-]+\.git)\Z'
)

# Branch name validation regex — shared with webhook handler (CRIT-01)
_BRANCH_RE = re.compile(r'^[a-zA-Z0-9_.\-/]{1,200}$')

# Namespace reservation: tenants cannot claim any name used by the platform at
# the cluster level. Prefixes cover Kubernetes system namespaces; exact names
# cover every infra namespace that Terraform/Helm installs into this cluster.
# This list must be updated whenever a new cluster-level namespace is added.
_RESERVED_NS_PREFIXES: tuple[str, ...] = (
    'kube-',       # Kubernetes system (kube-system, kube-public, kube-node-lease)
    'shipzen-',    # Platform core  (shipzen-system, shipzen-build)
    'gke-',        # GKE managed    (gke-managed-*, gmp-*)
    'gmp-',        # GKE monitoring
    'envoy-',      # Envoy gateway system
)
_RESERVED_NS_EXACT: frozenset[str] = frozenset({
    # Kubernetes system
    'default', 'kube-system', 'kube-public', 'kube-node-lease',
    # Platform infrastructure
    'argocd', 'observability', 'kyverno', 'keda',
    'external-secrets', 'external-dns',
    'velero',
})

# Kubernetes namespace name rules: lowercase alphanumeric and hyphens, 3–63 chars
_NAMESPACE_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$')
# Display names: no quotes, colons, newlines or other YAML-significant characters
_PROJECT_NAME_RE = re.compile(r'\A[A-Za-z0-9][A-Za-z0-9 ._\-]{0,62}\Z')

# Env var key validation: standard POSIX env var names (uppercase, digits, underscore)
_ENV_KEY_RE = re.compile(r'^[A-Z_][A-Z0-9_]{0,254}$')
_ENV_VALUE_MAX = 32 * 1024  # 32 KB — well within Secret Manager's 64 KB limit
