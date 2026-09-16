#!/usr/bin/env bash
# =============================================================================
# LocalStack initialisation script
# Runs automatically when LocalStack reaches the "ready" state.
# Mounts into the container at: /etc/localstack/init/ready.d/
# =============================================================================
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
BUCKET="shipzen-logs"

echo "=== ShipZen LocalStack init ==="

# ── S3: create the build-log bucket ──────────────────────────────────────────
echo "[s3] Creating bucket: $BUCKET"
aws --endpoint-url="$ENDPOINT" \
    --region "$REGION" \
    s3api create-bucket \
    --bucket "$BUCKET" \
    2>/dev/null || echo "[s3] Bucket $BUCKET already exists — skipping"

# Enable versioning so log objects are never silently overwritten
aws --endpoint-url="$ENDPOINT" \
    --region "$REGION" \
    s3api put-bucket-versioning \
    --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled \
    2>/dev/null || true

echo "[s3] Bucket $BUCKET is ready"

# ── Secrets Manager: pre-create a demo project secret ────────────────────────
# This mirrors what the API creates at `PUT /projects/{id}/env`.
# Use a well-known project UUID so the seed script and manual tests can
# reference it without having to look up a dynamic ID.
DEMO_PROJECT_ID="00000000-0000-0000-0000-000000000001"
SECRET_ID="shipzen/project/${DEMO_PROJECT_ID}"

echo "[secretsmanager] Creating demo secret: $SECRET_ID"
aws --endpoint-url="$ENDPOINT" \
    --region "$REGION" \
    secretsmanager create-secret \
    --name "$SECRET_ID" \
    --secret-string '{"DEMO_KEY":"demo-value","NODE_ENV":"development"}' \
    2>/dev/null || echo "[secretsmanager] Secret $SECRET_ID already exists — skipping"

echo "=== LocalStack init complete ==="
