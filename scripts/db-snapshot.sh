#!/usr/bin/env bash
# Keep ShipZen's Postgres data across teardowns at zero idle cost.
#
#   bash scripts/db-snapshot.sh backup  PROJECT_ID   # before terraform destroy
#   bash scripts/db-snapshot.sh restore PROJECT_ID   # right after a new instance is created
#
# Teardown deletes the Cloud SQL instance (a stopped instance still bills for
# storage). Before that happens we export the database to a GCS bucket that is
# NOT in Terraform state, so teardown never deletes it. A few small SQL dumps
# stay well inside the 5 GB GCS free tier in us-central1, so idle cost is $0.
#
# backup  exits non-zero if the instance exists but the export fails (after
#         retries). The teardown workflows alert and continue anyway: zero idle
#         cost has priority, and latest.sql.gz still holds the previous backup.
# restore is a no-op when there is no backup yet (first ever deploy).
set -euo pipefail

cmd="${1:?usage: db-snapshot.sh backup|restore PROJECT_ID}"
P="${2:?usage: db-snapshot.sh backup|restore PROJECT_ID}"
INSTANCE="shipzen-postgres"
DB="shipzen"
DB_USER="shipzen"
BUCKET="gs://${P}-shipzen-db-backups"
LATEST="$BUCKET/latest.sql.gz"

instance_exists() {
  gcloud sql instances describe "$INSTANCE" --project "$P" >/dev/null 2>&1
}

ensure_bucket() {
  if gcloud storage buckets describe "$BUCKET" --project "$P" >/dev/null 2>&1; then
    return
  fi
  echo "Creating backup bucket $BUCKET"
  gcloud storage buckets create "$BUCKET" --project "$P" --location=us-central1 \
    --default-storage-class=STANDARD --uniform-bucket-level-access \
    --public-access-prevention
  # Timestamped copies expire after 30 days; latest.sql.gz is kept until replaced.
  lifecycle=$(mktemp)
  echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30,"matchesPrefix":["history/"]}}]}' > "$lifecycle"
  gcloud storage buckets update "$BUCKET" --project "$P" --lifecycle-file="$lifecycle"
  rm -f "$lifecycle"
}

# Every new Cloud SQL instance has its own service account, and that account
# (not the caller) reads and writes the dump files.
grant_instance_access() {
  local sa
  sa=$(gcloud sql instances describe "$INSTANCE" --project "$P" --format='value(serviceAccountEmailAddress)')
  gcloud storage buckets add-iam-policy-binding "$BUCKET" --project "$P" \
    --member="serviceAccount:$sa" --role=roles/storage.objectAdmin >/dev/null
}

case "$cmd" in
  backup)
    if ! instance_exists; then
      echo "No Cloud SQL instance $INSTANCE: nothing to back up."
      exit 0
    fi
    ensure_bucket
    grant_instance_access
    obj="$BUCKET/history/shipzen-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
    echo "Exporting database $DB to $obj"
    # --clean --if-exists: the dump drops each object before recreating it, so it
    # can be imported even if the schema job already created empty tables.
    # Retry: a failed export blocks teardown (and the cluster keeps billing), so
    # ride out transient errors such as "another operation is in progress".
    for attempt in 1 2 3; do
      if gcloud sql export sql "$INSTANCE" "$obj" --project "$P" --database="$DB" \
          --clean --if-exists --quiet; then
        break
      fi
      if [ "$attempt" = 3 ]; then
        echo "::error::Database export failed 3 times; latest.sql.gz still holds the previous backup."
        exit 1
      fi
      echo "Export attempt $attempt failed; retrying in 60s"
      sleep 60
    done
    gcloud storage cp "$obj" "$LATEST" --project "$P"
    echo "Backup saved: $LATEST"
    ;;
  restore)
    if ! gcloud storage objects describe "$LATEST" --project "$P" >/dev/null 2>&1; then
      echo "No backup at $LATEST: starting with an empty database."
      exit 0
    fi
    if ! instance_exists; then
      echo "::error::Cloud SQL instance $INSTANCE does not exist; cannot restore."
      exit 1
    fi
    grant_instance_access
    echo "Restoring $LATEST into database $DB"
    gcloud sql import sql "$INSTANCE" "$LATEST" --project "$P" --database="$DB" \
      --user="$DB_USER" --quiet
    echo "Restore complete."
    ;;
  *)
    echo "usage: db-snapshot.sh backup|restore PROJECT_ID" >&2
    exit 2
    ;;
esac
