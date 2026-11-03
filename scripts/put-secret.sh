#!/usr/bin/env bash
# Store stdin as the value of a Secret Manager secret, keeping exactly one live version.
#
#   printf '%s' "$VALUE" | bash scripts/put-secret.sh SECRET_NAME [--create-only]
#
# Secret Manager bills every version that isn't destroyed (only 6 are free per
# billing account). Adding a version on every deploy piled up ~170 of them, about
# $10/month while the platform was torn down. This script:
#   - creates the secret if it is missing;
#   - adds a version only if the value actually changed;
#   - destroys every older version, so idle cost stays at $0.
# --create-only: set the value only when the secret has no enabled version yet
# (placeholders such as shipzen-alerts that a person fills in later).
#
# The value is never printed.
set -euo pipefail

name="${1:?usage: put-secret.sh SECRET_NAME [--create-only]}"
mode="${2:-}"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/new"

if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
  gcloud secrets create "$name" --replication-policy=automatic >/dev/null
  echo "$name: created"
fi

newest_enabled() {
  gcloud secrets versions list "$name" --filter='state=ENABLED' \
    --sort-by=~createTime --limit=1 --format='value(name.basename())'
}

current=$(newest_enabled)
if [ -n "$current" ] && [ "$mode" = "--create-only" ]; then
  echo "$name: already set, leaving the value alone"
elif [ -n "$current" ] \
  && gcloud secrets versions access "$current" --secret "$name" --out-file "$tmp/old" >/dev/null 2>&1 \
  && cmp -s "$tmp/old" "$tmp/new"; then
  echo "$name: unchanged (version $current)"
else
  gcloud secrets versions add "$name" --data-file="$tmp/new" >/dev/null
  echo "$name: new version stored"
fi

# Keep only the newest enabled version.
keep=$(newest_enabled)
for v in $(gcloud secrets versions list "$name" --filter='state!=DESTROYED' --format='value(name.basename())'); do
  [ "$v" = "$keep" ] && continue
  if gcloud secrets versions destroy "$v" --secret "$name" --quiet >/dev/null 2>&1; then
    echo "$name: destroyed old version $v"
  else
    echo "::warning::$name: could not destroy old version $v (it is still billed)"
  fi
done
