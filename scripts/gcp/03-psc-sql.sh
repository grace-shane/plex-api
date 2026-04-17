#!/usr/bin/env bash
# 03-psc-sql.sh — Private Service Connection for Cloud SQL.
# Reserves an IP range on the VPC and establishes peering with
# servicenetworking.googleapis.com so managed services (Cloud SQL) can
# allocate private IPs inside the VPC.
set -euo pipefail
source "$(dirname "$0")/env.sh"

# ── Reserve the PSC IP range ───────────────────────────────────────────────
ensure \
  "gcloud compute addresses describe $PSC_RANGE_NAME \
     --global --project=$PROJECT_ID" \
  "gcloud compute addresses create $PSC_RANGE_NAME \
     --project=$PROJECT_ID \
     --global \
     --purpose=VPC_PEERING \
     --addresses=$PSC_RANGE_START \
     --prefix-length=$PSC_RANGE_PREFIX \
     --network=$VPC_NAME \
     --description='Reserved range for Cloud SQL private IP'" \
  "PSC IP range $PSC_RANGE_NAME"

# ── Establish VPC peering with servicenetworking ───────────────────────────
# `vpc-peerings connect` is not describe-compatible in the same way, so check
# by listing existing peerings on the network.
if gcloud services vpc-peerings list \
     --network="$VPC_NAME" \
     --service=servicenetworking.googleapis.com \
     --project="$PROJECT_ID" \
     --format="value(reservedPeeringRanges)" 2>/dev/null | grep -q "$PSC_RANGE_NAME"; then
  skip "VPC peering with servicenetworking"
else
  say "creating VPC peering with servicenetworking"
  gcloud services vpc-peerings connect \
    --project="$PROJECT_ID" \
    --service=servicenetworking.googleapis.com \
    --ranges="$PSC_RANGE_NAME" \
    --network="$VPC_NAME"
  ok "VPC peering with servicenetworking"
fi

ok "PSC ready for Cloud SQL"
