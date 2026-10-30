#!/usr/bin/env bash
# Find (and optionally delete) persistent disks that GKE created for a cluster's
# PersistentVolumeClaims and that nothing uses any more.
#
# Why: Prometheus, Grafana, Loki and Redis keep their data on PVC-backed disks.
# If a cluster is deleted before the CSI driver has released them, the disks
# outlive it and are billed until someone deletes them.
#
# A disk is only selected when ALL of these hold, so nothing else in the
# project can be touched:
#   - GKE labelled it as a volume of this cluster (goog-k8s-cluster-name, goog-gke-volume)
#   - it was created for a Kubernetes PVC (description)
#   - no VM is using it (no users)
#   - its PV was not marked Retain
# With --delete it also refuses to run while the cluster still exists: an
# unattached disk of a live cluster can belong to a scaled-down StatefulSet.
#
# Usage:
#   scripts/cleanup-orphaned-disks.sh PROJECT [CLUSTER]            # report only (default)
#   scripts/cleanup-orphaned-disks.sh --delete PROJECT [CLUSTER]   # delete them
# Works from Linux, macOS, WSL or Git Bash on Windows; needs an authenticated gcloud.
set -euo pipefail

DELETE=false
if [ "${1:-}" = "--delete" ]; then DELETE=true; shift; fi
PROJECT="${1:?usage: $0 [--delete] PROJECT [CLUSTER]}"
CLUSTER="${2:-shipzen-cluster}"
REGION="${REGION:-us-central1}"

summary() { [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$*" >> "$GITHUB_STEP_SUMMARY"; echo "$*"; }

VOLUMES="labels.goog-k8s-cluster-name=$CLUSTER AND labels.goog-gke-volume:* \
AND description~'kubernetes.io/created-for/pvc'"
FILTER="$VOLUMES AND -users:* AND -labels.reclaim-policy-gke-io=retain"

# Context for the report: how many of this cluster's PVC disks are in use.
IN_USE=$(gcloud compute disks list --project "$PROJECT" --filter="$VOLUMES AND users:*" --format='value(name)' | grep -c . || true)
echo "PVC disks of $CLUSTER in use: $IN_USE"

DISKS="$(gcloud compute disks list --project "$PROJECT" --filter="$FILTER" \
  --format='value(name,zone.basename(),sizeGb)')"

if [ -z "$DISKS" ]; then
  summary "Orphaned disks for $CLUSTER: none."
  exit 0
fi

COUNT=$(wc -l <<<"$DISKS" | tr -d ' ')
GB=$(awk '{s += $3} END {print s}' <<<"$DISKS")
summary "Orphaned disks for $CLUSTER: $COUNT ($GB GB)"
while read -r NAME ZONE SIZE; do summary "- $NAME ($ZONE, ${SIZE} GB)"; done <<<"$DISKS"

if [ "$DELETE" != "true" ]; then
  echo "Report only. Re-run with --delete to remove them."
  exit 0
fi

if gcloud container clusters describe "$CLUSTER" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  summary "Not deleting: cluster $CLUSTER still exists, so these may belong to scaled-down workloads."
  exit 1
fi

FAILED=0
while read -r NAME ZONE SIZE; do
  if gcloud compute disks delete "$NAME" --zone "$ZONE" --project "$PROJECT" --quiet; then
    echo "deleted $NAME"
  else
    FAILED=$((FAILED + 1))
  fi
done <<<"$DISKS"

summary "Deleted $((COUNT - FAILED)) of $COUNT orphaned disks ($GB GB)."
[ "$FAILED" -eq 0 ]
