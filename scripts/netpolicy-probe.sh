#!/usr/bin/env bash
# Prove the NetworkPolicies are enforced, from the inside.
#
# Starts a short-lived, unprivileged curl pod in a tenant namespace and in the
# build namespace, tries connections that must be blocked and ones that must
# work, prints PASS/FAIL per check and exits non-zero on any FAIL. Pods are
# deleted afterwards. Run with kubectl pointed at the cluster.
#
#   scripts/netpolicy-probe.sh [CLOUD_SQL_IP]
#
# Set EXPECT_TENANT_PORT_LIMIT=1 when the controller runs with
# TENANT_EGRESS_PORTS, so tenants are also checked for a blocked odd port.
#
# "Blocked" means the connection attempt timed out (curl exit 28): with
# Dataplane V2 a denied packet is dropped. A refusal, an error reply or a
# success all mean the packet got through.
set -uo pipefail

SQL_IP="${1:-}"
IMAGE="curlimages/curl:8.10.1"
TENANT_NS="$(kubectl get resourcequota -A --field-selector metadata.name=tenant-quota \
  -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null)"
FAIL=0

run_pod() {  # run_pod <namespace> <name>: start an idle restricted-PSS-compliant curl pod
  kubectl delete pod "$2" -n "$1" --ignore-not-found --wait=true >/dev/null 2>&1
  kubectl run "$2" -n "$1" --restart=Never --image="$IMAGE" --overrides='{
    "spec": {
      "automountServiceAccountToken": false,
      "securityContext": {"runAsNonRoot": true, "runAsUser": 100, "seccompProfile": {"type": "RuntimeDefault"}},
      "tolerations": [{"key": "shipzen.jeneeldumasia.codes/dedicated", "operator": "Equal", "value": "builder", "effect": "NoSchedule"}],
      "containers": [{"name": "probe", "image": "'"$IMAGE"'", "command": ["sleep", "300"],
        "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"cpu": "100m", "memory": "64Mi"}},
        "securityContext": {"allowPrivilegeEscalation": false, "capabilities": {"drop": ["ALL"]}, "readOnlyRootFilesystem": true}}]
    }}' >/dev/null
  kubectl wait pod "$2" -n "$1" --for=condition=Ready --timeout=120s >/dev/null
}

check() {  # check <namespace> <pod> <label> <expect: allow|deny> <url>
  local code
  kubectl exec -n "$1" "$2" -- curl -s -o /dev/null --connect-timeout 5 -m 8 "$5" >/dev/null 2>&1
  code=$?
  local got=allow; [ "$code" -eq 28 ] && got=deny
  local mark=PASS; [ "$got" = "$4" ] || { mark=FAIL; FAIL=1; }
  printf '%s | %-11s | %-42s | expected %s, got %s (curl %s)\n' "$mark" "$1" "$3" "$4" "$got" "$code"
}

probe() {  # probe <namespace> <metadata server: allow|deny> [odd internet port: deny|skip]
  local ns="$1" metadata="$2" odd_port="${3:-skip}" pod="netprobe"
  if ! run_pod "$ns" "$pod"; then
    echo "FAIL | $ns | probe pod did not start"; FAIL=1; return
  fi
  check "$ns" "$pod" "platform API (shipzen-system)" deny "http://shipzen-api.shipzen-system.svc.cluster.local/healthz"
  check "$ns" "$pod" "Redis (shipzen-system)"         deny "http://redis-master.shipzen-system.svc.cluster.local:6379/"
  check "$ns" "$pod" "Grafana (observability)"       deny "http://kube-prometheus-stack-grafana.observability.svc.cluster.local/"
  check "$ns" "$pod" "metadata server"                "$metadata" "http://169.254.169.254/"
  [ -n "$SQL_IP" ] && check "$ns" "$pod" "Cloud SQL" deny "http://$SQL_IP:5432/"   # Postgres drops the HTTP request: allowed = error reply, blocked = timeout
  check "$ns" "$pod" "public internet"                allow "https://www.google.com/"
  check "$ns" "$pod" "ShipZen via Cloudflare"         allow "https://shipzen.jeneeldumasia.codes/"
  # portquiz.net answers on every port, so a timeout here really is the policy.
  [ "$odd_port" = deny ] && check "$ns" "$pod" "internet on an odd port (6667)" deny "http://portquiz.net:6667/"
  kubectl delete pod "$pod" -n "$ns" --ignore-not-found --wait=false >/dev/null 2>&1
}

# NetworkPolicies are only enforced by GKE Dataplane V2 (anetd). Without it
# every "deny" below would fail, so say why up front.
if ! kubectl get daemonset anetd -n kube-system >/dev/null 2>&1; then
  echo "FAIL | cluster     | GKE Dataplane V2 (anetd) not found: NetworkPolicies are not enforced"
  FAIL=1
fi

# Neither tenants nor builds may reach the metadata server: builds get only a
# per-build staging push token from the worker (security finding C4).
tenant_odd=skip; [ "${EXPECT_TENANT_PORT_LIMIT:-0}" = 1 ] && tenant_odd=deny
if [ -n "$TENANT_NS" ]; then probe "$TENANT_NS" deny "$tenant_odd"; else echo "SKIP | no tenant namespace to probe"; fi
probe shipzen-build deny deny   # builds: HTTP(S) and SSH only

exit "$FAIL"
