#!/usr/bin/env bash
# 01-apis.sh — enable the GCP APIs Datum depends on.
# Idempotent: `gcloud services enable` is a no-op if the API is already on.
set -euo pipefail
source "$(dirname "$0")/env.sh"

say "Enabling APIs on project $PROJECT_ID"

APIS=(
  compute.googleapis.com
  sqladmin.googleapis.com
  secretmanager.googleapis.com
  iap.googleapis.com
  servicenetworking.googleapis.com
  cloudscheduler.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  logging.googleapis.com
)

gcloud services enable "${APIS[@]}" --project="$PROJECT_ID"
ok "APIs enabled (${#APIS[@]} services)"
