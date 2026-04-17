#!/usr/bin/env bash
# 04-service-accounts.sh — per-VM service accounts and IAM bindings.
# datum-runtime-sa    runs the nightly sync and Flask API
# datum-dev-sa        used when Shane SSHes into datum-dev
#
# Project-level roles bound here: Cloud SQL Client, Log Writer.
# Secret Accessor is bound PER-SECRET in 05-secrets.sh so datum-dev-sa can
# be denied access to aps-refresh-token (runtime-only).
set -euo pipefail
source "$(dirname "$0")/env.sh"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DEV_EMAIL="${DEV_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# ── Create service accounts ────────────────────────────────────────────────
ensure \
  "gcloud iam service-accounts describe $RUNTIME_EMAIL --project=$PROJECT_ID" \
  "gcloud iam service-accounts create $RUNTIME_SA \
     --project=$PROJECT_ID \
     --display-name='Datum runtime (sync + API)'" \
  "service account $RUNTIME_SA"

ensure \
  "gcloud iam service-accounts describe $DEV_EMAIL --project=$PROJECT_ID" \
  "gcloud iam service-accounts create $DEV_SA \
     --project=$PROJECT_ID \
     --display-name='Datum dev VM'" \
  "service account $DEV_SA"

# Wait for IAM propagation before binding roles. SA creation returns
# immediately but the SA isn't always visible to add-iam-policy-binding
# for ~30s. A missing SA surfaces as a confusing "Policy modification
# failed" error with a misleading lint-condition hint.
say "waiting for SA propagation (30s)"
sleep 30

# ── Project-level role bindings ────────────────────────────────────────────
# add-iam-policy-binding is effectively idempotent (no-op if the binding
# already exists).
say "binding project-level IAM roles"

for ROLE in roles/cloudsql.client roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$RUNTIME_EMAIL" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEV_EMAIL" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
done

ok "IAM bindings applied"
