#!/usr/bin/env bash
# Runs `terraform destroy` while a background watchdog clears the things that
# make namespace deletion hit "context deadline exceeded": ArgoCD finalizers on
# Applications/AppProjects and namespaces stuck in Terminating.
# Usage: destroy-with-watchdog.sh  (run from the terraform/ directory)
set -uo pipefail

watchdog() {
  while true; do
    # Argo Applications/AppProjects carry resources-finalizer.argocd.argoproj.io,
    # which blocks deletion once the Argo controller is gone.
    for kind in applications.argoproj.io applicationsets.argoproj.io appprojects.argoproj.io; do
      for item in $(kubectl get "$kind" -A --no-headers \
          -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name 2>/dev/null \
          | awk '{print $1"/"$2}'); do
        kubectl patch "$kind" "${item#*/}" -n "${item%%/*}" --type merge \
          -p '{"metadata":{"finalizers":null}}' >/dev/null 2>&1 || true
      done
    done
    # Force-finalize any namespace stuck in Terminating.
    for ns in $(kubectl get ns --no-headers 2>/dev/null | awk '$2=="Terminating"{print $1}'); do
      echo "[watchdog] releasing finalizers on stuck namespace: $ns"
      kubectl get ns "$ns" -o json 2>/dev/null \
        | jq '.spec.finalizers=[]' \
        | kubectl replace --raw "/api/v1/namespaces/$ns/finalize" -f - >/dev/null 2>&1 || true
    done
    sleep 15
  done
}

watchdog &
WATCHDOG_PID=$!
trap 'kill "$WATCHDOG_PID" 2>/dev/null || true' EXIT

terraform destroy -auto-approve
