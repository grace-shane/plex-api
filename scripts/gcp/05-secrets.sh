#!/usr/bin/env bash
# 05-secrets.sh — create Secret Manager slots (empty) and grant access.
# Values are populated later via `gcloud secrets versions add`.
# datum-dev-sa does not get aps-refresh-token (token rotation belongs to the
# runtime SA; dev shouldn't contend).
set -euo pipefail
source "$(dirname "$0")/env.sh"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DEV_EMAIL="${DEV_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# Secrets that dev should NOT see. Runtime gets access to everything.
DEV_DENIED=(aps-refresh-token)

is_dev_denied() {
  local s="$1"
  for denied in "${DEV_DENIED[@]}"; do
    [[ "$s" == "$denied" ]] && return 0
  done
  return 1
}

for SECRET in "${SECRETS[@]}"; do
  ensure \
    "gcloud secrets describe $SECRET --project=$PROJECT_ID" \
    "gcloud secrets create $SECRET \
       --project=$PROJECT_ID \
       --replication-policy=automatic" \
    "secret $SECRET"

  # Runtime SA gets access to every secret.
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$RUNTIME_EMAIL" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet >/dev/null

  # Dev SA gets access unless the secret is on the denied list.
  if is_dev_denied "$SECRET"; then
    skip "dev-sa access to $SECRET (denied by policy)"
  else
    gcloud secrets add-iam-policy-binding "$SECRET" \
      --project="$PROJECT_ID" \
      --member="serviceAccount:$DEV_EMAIL" \
      --role="roles/secretmanager.secretAccessor" \
      --condition=None \
      --quiet >/dev/null
  fi
done

ok "Secret Manager slots ready (${#SECRETS[@]} secrets)"
