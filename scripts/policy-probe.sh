#!/usr/bin/env bash
# Prove the tenant Kyverno policies (infra/system/tenant-policies.yaml) are
# enforced: send good and bad HTTPRoutes and ExternalSecrets to a tenant
# namespace as server-side dry runs. Admission (Kyverno) judges them; nothing
# is ever created. Exits non-zero if a bad one is accepted or a good one refused.
set -u
FAIL=0
NS="$(kubectl get ns -l shipzen.jeneeldumasia.codes/tenant=true -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
if [ -z "$NS" ]; then echo "SKIP | no tenant namespace to probe"; exit 0; fi
SLUG="$(kubectl get ns "$NS" -o jsonpath='{.metadata.labels.shipzen\.jeneeldumasia\.codes/slug}')"
PID="$(kubectl get ns "$NS" -o jsonpath='{.metadata.labels.shipzen\.jeneeldumasia\.codes/project-id}')"

for kind in validatingpolicies.policies.kyverno.io; do
  for p in tenant-externalsecret-own-project restrict-tenant-hostnames; do
    if ! kubectl get "$kind" "$p" >/dev/null 2>&1; then
      echo "FAIL | policy     | $p is not installed"; FAIL=1
    fi
  done
done

expect() {  # expect <allow|deny> <description> <manifest>
  local want="$1" what="$2" out got
  out="$(printf '%s\n' "$3" | kubectl apply --dry-run=server -n "$NS" -f - 2>&1)"
  if [ $? -eq 0 ]; then got=allow; else got=deny; fi
  # Only a policy denial counts as "deny"; any other error is a probe failure.
  if [ "$got" = deny ] && ! printf '%s' "$out" | grep -qiE 'kyverno|denied|policy'; then
    echo "FAIL | $what: error, not a policy decision: $(printf '%s' "$out" | tail -n1)"; FAIL=1; return
  fi
  if [ "$got" = "$want" ]; then echo "PASS | $what ($got)"; else echo "FAIL | $what: expected $want, got $got"; FAIL=1; fi
}

route() {  # route <hostname>
  cat <<YAML
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: {name: policy-probe}
spec:
  parentRefs: [{name: shipzen-gateway, namespace: shipzen-system}]
  hostnames: ["$1"]
YAML
}
secret() {  # secret <store> <key>
  cat <<YAML
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata: {name: policy-probe}
spec:
  secretStoreRef: {name: $1, kind: ClusterSecretStore}
  target: {name: policy-probe}
  dataFrom: [{extract: {key: $2}}]
YAML
}

echo "Tenant namespace: $NS"
expect allow "route on its own release hostname" "$(route "abcdef12-$SLUG-shipzen.jeneeldumasia.codes")"
expect deny  "route on the platform's hostname"   "$(route "shipzen.jeneeldumasia.codes")"
expect deny  "route on another project's hostname" "$(route "abcdef12-someone-else-shipzen.jeneeldumasia.codes")"
expect allow "ExternalSecret for its own secret"   "$(secret gcp-secret-manager-tenants "shipzen-project-$PID")"
expect deny  "ExternalSecret for another project"  "$(secret gcp-secret-manager-tenants "shipzen-project-00000000-0000-0000-0000-000000000000")"
expect deny  "ExternalSecret via the platform store" "$(secret gcp-secret-manager "shipzen-project-$PID")"
exit $FAIL
