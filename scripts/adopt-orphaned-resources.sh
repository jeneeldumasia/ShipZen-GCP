#!/usr/bin/env bash
# Adopt GCP resources that exist in the project but are missing from Terraform state.
#
# Why: if a run creates resources but its state never reaches HCP Terraform
# (job killed, lock lost, state reset), the next apply fails with
# "Error 409 ... already exists" for every one of them. This script imports
# each such resource so the apply can continue instead of failing.
#
# Safe to run every time: it only imports a resource when it is (a) absent from
# state and (b) present in GCP. It never creates, changes or deletes anything in GCP.
#
# Run from ./terraform after `terraform init`, with the same TF_VAR_* env as plan.
set -uo pipefail

: "${TF_VAR_gcp_project:?TF_VAR_gcp_project must be set}"
P="$TF_VAR_gcp_project"
R="${TF_VAR_gcp_region:-us-central1}"
CLUSTER_LOC="$R"
USE_CLOUD_SQL="${TF_VAR_use_cloud_sql:-true}"

STATE="$(terraform state list 2>/dev/null || true)"
adopted=0; failed=0

# adopt <terraform address> <import id> <gcloud describe command...>
adopt() {
  local addr="$1" id="$2"; shift 2
  if grep -qxF "$addr" <<<"$STATE"; then return 0; fi
  if ! "$@" >/dev/null 2>&1; then return 0; fi   # not in GCP: Terraform will create it
  echo "::group::Importing $addr"
  local out
  if out="$(terraform import -no-color -input=false "$addr" "$id" 2>&1)"; then
    echo "$out"
    adopted=$((adopted + 1))
  else
    echo "$out"
    # Put the error itself in the annotation so it is readable from the run page/API.
    local err
    err="$(grep -A12 -m1 'Error' <<<"$out" | head -n 14)"
    err="${err//'%'/'%25'}"; err="${err//$'\n'/'%0A'}"
    echo "::warning title=Could not import $addr::$err"
    failed=$((failed + 1))
  fi
  echo "::endgroup::"
}

sa() { echo "projects/$P/serviceAccounts/$1@$P.iam.gserviceaccount.com"; }

# Networking
adopt google_compute_network.vpc            "projects/$P/global/networks/shipzen-vpc" \
  gcloud compute networks describe shipzen-vpc --project "$P"
adopt google_compute_subnetwork.subnet      "projects/$P/regions/$R/subnetworks/shipzen-subnet" \
  gcloud compute networks subnets describe shipzen-subnet --region "$R" --project "$P"
adopt google_compute_router.router          "projects/$P/regions/$R/routers/shipzen-router" \
  gcloud compute routers describe shipzen-router --region "$R" --project "$P"
adopt google_compute_router_nat.nat         "projects/$P/regions/$R/routers/shipzen-router/shipzen-nat" \
  gcloud compute routers nats describe shipzen-nat --router shipzen-router --region "$R" --project "$P"

# GKE
adopt google_container_cluster.primary      "projects/$P/locations/$CLUSTER_LOC/clusters/shipzen-cluster" \
  gcloud container clusters describe shipzen-cluster --region "$CLUSTER_LOC" --project "$P"
adopt google_container_node_pool.platform_nodes "projects/$P/locations/$CLUSTER_LOC/clusters/shipzen-cluster/nodePools/platform-nodes" \
  gcloud container node-pools describe platform-nodes --cluster shipzen-cluster --region "$CLUSTER_LOC" --project "$P"

# Service accounts
adopt google_service_account.node_sa        "$(sa shipzen-node-sa)"    gcloud iam service-accounts describe "shipzen-node-sa@$P.iam.gserviceaccount.com" --project "$P"
adopt google_service_account.builder_sa     "$(sa shipzen-builder-sa)" gcloud iam service-accounts describe "shipzen-builder-sa@$P.iam.gserviceaccount.com" --project "$P"
adopt google_service_account.eso_sa         "$(sa shipzen-eso-sa)"     gcloud iam service-accounts describe "shipzen-eso-sa@$P.iam.gserviceaccount.com" --project "$P"
adopt google_service_account.velero_sa      "$(sa velero-backup-sa)"   gcloud iam service-accounts describe "velero-backup-sa@$P.iam.gserviceaccount.com" --project "$P"

# Artifact Registry
adopt google_artifact_registry_repository.shipzen_builds "projects/$P/locations/$R/repositories/shipzen-builds" \
  gcloud artifacts repositories describe shipzen-builds --location "$R" --project "$P"
adopt google_artifact_registry_repository.platform       "projects/$P/locations/$R/repositories/shipzen-platform" \
  gcloud artifacts repositories describe shipzen-platform --location "$R" --project "$P"

# Storage (the build-logs bucket has a random suffix, so a leftover one is just a new name: nothing to adopt)
adopt google_storage_bucket.velero_backups  "$P-velero-backups" \
  gcloud storage buckets describe "gs://$P-velero-backups" --project "$P"

# Secret Manager containers (Terraform adds a fresh version on apply)
adopt google_secret_manager_secret.cloudflare_origin_cert "projects/$P/secrets/shipzen-cloudflare-origin-cert" \
  gcloud secrets describe shipzen-cloudflare-origin-cert --project "$P"
adopt google_secret_manager_secret.redis_password         "projects/$P/secrets/shipzen-redis-password" \
  gcloud secrets describe shipzen-redis-password --project "$P"

# Cloud SQL (only when enabled)
if [ "$USE_CLOUD_SQL" = "true" ]; then
  adopt 'google_compute_global_address.private_ip_address[0]' "projects/$P/global/addresses/shipzen-private-ip" \
    gcloud compute addresses describe shipzen-private-ip --global --project "$P"
  adopt 'google_sql_database_instance.postgres[0]' "projects/$P/instances/shipzen-postgres" \
    gcloud sql instances describe shipzen-postgres --project "$P"
  adopt 'google_sql_database.database[0]' "projects/$P/instances/shipzen-postgres/databases/shipzen" \
    gcloud sql databases describe shipzen --instance shipzen-postgres --project "$P"
  adopt 'google_sql_user.users[0]' "$P/shipzen-postgres/shipzen" \
    bash -c "gcloud sql users list --instance shipzen-postgres --project '$P' --format='value(name)' | grep -qx shipzen"
fi

echo "Adopted $adopted orphaned resource(s); $failed import(s) failed."
[ "$failed" -eq 0 ]
