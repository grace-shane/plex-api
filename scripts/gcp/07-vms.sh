#!/usr/bin/env bash
# 07-vms.sh — create datum-runtime (e2-micro, always-on) and datum-dev
# (e2-standard-2, scheduled start/stop in a later phase).
# Both are Ubuntu 24.04 LTS, no public IP, IAP-only SSH, attached to the
# custom subnet with their own service accounts.
set -euo pipefail
source "$(dirname "$0")/env.sh"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DEV_EMAIL="${DEV_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# ── datum-runtime ──────────────────────────────────────────────────────────
ensure \
  "gcloud compute instances describe $RUNTIME_VM \
     --zone=$ZONE --project=$PROJECT_ID" \
  "gcloud compute instances create $RUNTIME_VM \
     --project=$PROJECT_ID \
     --zone=$ZONE \
     --machine-type=$RUNTIME_MACHINE_TYPE \
     --image-family=$VM_IMAGE_FAMILY \
     --image-project=$VM_IMAGE_PROJECT \
     --subnet=$SUBNET_NAME \
     --no-address \
     --service-account=$RUNTIME_EMAIL \
     --scopes=cloud-platform \
     --tags=ssh-access \
     --boot-disk-size=30GB \
     --boot-disk-type=pd-standard \
     --metadata=enable-oslogin=TRUE" \
  "VM $RUNTIME_VM"

# ── datum-dev ──────────────────────────────────────────────────────────────
ensure \
  "gcloud compute instances describe $DEV_VM \
     --zone=$ZONE --project=$PROJECT_ID" \
  "gcloud compute instances create $DEV_VM \
     --project=$PROJECT_ID \
     --zone=$ZONE \
     --machine-type=$DEV_MACHINE_TYPE \
     --image-family=$VM_IMAGE_FAMILY \
     --image-project=$VM_IMAGE_PROJECT \
     --subnet=$SUBNET_NAME \
     --no-address \
     --service-account=$DEV_EMAIL \
     --scopes=cloud-platform \
     --tags=ssh-access,dev-schedule \
     --boot-disk-size=50GB \
     --boot-disk-type=pd-balanced \
     --metadata=enable-oslogin=TRUE" \
  "VM $DEV_VM"

ok "VMs ready"
echo
echo "SSH via IAP:"
echo "  gcloud compute ssh $RUNTIME_VM --zone=$ZONE --project=$PROJECT_ID --tunnel-through-iap"
echo "  gcloud compute ssh $DEV_VM     --zone=$ZONE --project=$PROJECT_ID --tunnel-through-iap"
