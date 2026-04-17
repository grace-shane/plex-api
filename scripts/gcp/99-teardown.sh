#!/usr/bin/env bash
# 99-teardown.sh — delete everything 00-provision.sh created, in reverse
# dependency order. APIs are left enabled (disabling them is cheap to skip
# and risks knock-on effects on other projects).
#
# REQUIRES EXPLICIT CONFIRMATION. Does not run unless you type the project ID.
set -euo pipefail
source "$(dirname "$0")/env.sh"

echo "This will PERMANENTLY DELETE Datum infrastructure from project: $PROJECT_ID"
echo "  - VMs: $RUNTIME_VM, $DEV_VM"
echo "  - Cloud SQL: $SQL_INSTANCE (all data + backups destroyed)"
echo "  - Secrets: ${SECRETS[*]}"
echo "  - Service accounts: $RUNTIME_SA, $DEV_SA"
echo "  - VPC: $VPC_NAME (subnets, NAT, router, firewall, PSC)"
echo
read -r -p "Type the project ID to confirm: " CONFIRM
[[ "$CONFIRM" == "$PROJECT_ID" ]] || die "Confirmation did not match — aborting"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DEV_EMAIL="${DEV_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# Best-effort deletes: don't bail if a resource is already gone.
safe_delete() {
  local label="$1"; shift
  if "$@" &>/dev/null; then
    ok "deleted $label"
  else
    skip "$label (already gone or delete failed harmlessly)"
  fi
}

# ── VMs ────────────────────────────────────────────────────────────────────
for VM in "$RUNTIME_VM" "$DEV_VM"; do
  safe_delete "VM $VM" \
    gcloud compute instances delete "$VM" \
      --zone="$ZONE" --project="$PROJECT_ID" --quiet
done

# ── Cloud SQL ──────────────────────────────────────────────────────────────
safe_delete "Cloud SQL $SQL_INSTANCE" \
  gcloud sql instances delete "$SQL_INSTANCE" \
    --project="$PROJECT_ID" --quiet

# ── Secrets ────────────────────────────────────────────────────────────────
for SECRET in "${SECRETS[@]}"; do
  safe_delete "secret $SECRET" \
    gcloud secrets delete "$SECRET" --project="$PROJECT_ID" --quiet
done

# ── Service accounts ──────────────────────────────────────────────────────
for EMAIL in "$RUNTIME_EMAIL" "$DEV_EMAIL"; do
  safe_delete "service account $EMAIL" \
    gcloud iam service-accounts delete "$EMAIL" \
      --project="$PROJECT_ID" --quiet
done

# ── VPC peering ────────────────────────────────────────────────────────────
safe_delete "VPC peering with servicenetworking" \
  gcloud services vpc-peerings delete \
    --service=servicenetworking.googleapis.com \
    --network="$VPC_NAME" \
    --project="$PROJECT_ID" --quiet

safe_delete "PSC range $PSC_RANGE_NAME" \
  gcloud compute addresses delete "$PSC_RANGE_NAME" \
    --global --project="$PROJECT_ID" --quiet

# ── Firewall rules ────────────────────────────────────────────────────────
for RULE in datum-allow-iap-ssh datum-allow-internal; do
  safe_delete "firewall rule $RULE" \
    gcloud compute firewall-rules delete "$RULE" \
      --project="$PROJECT_ID" --quiet
done

# ── NAT + router ──────────────────────────────────────────────────────────
safe_delete "Cloud NAT $NAT_NAME" \
  gcloud compute routers nats delete "$NAT_NAME" \
    --router="$ROUTER_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet

safe_delete "Cloud Router $ROUTER_NAME" \
  gcloud compute routers delete "$ROUTER_NAME" \
    --region="$REGION" --project="$PROJECT_ID" --quiet

# ── Subnet + VPC ──────────────────────────────────────────────────────────
safe_delete "subnet $SUBNET_NAME" \
  gcloud compute networks subnets delete "$SUBNET_NAME" \
    --region="$REGION" --project="$PROJECT_ID" --quiet

safe_delete "VPC $VPC_NAME" \
  gcloud compute networks delete "$VPC_NAME" \
    --project="$PROJECT_ID" --quiet

echo
ok "Teardown complete."
