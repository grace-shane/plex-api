#!/usr/bin/env bash
# 02-vpc.sh — custom-mode VPC, primary subnet with secondary ranges reserved
# for future GKE, Cloud Router + Cloud NAT for private egress, and firewall
# rules for IAP SSH and internal traffic.
set -euo pipefail
source "$(dirname "$0")/env.sh"

# ── VPC ────────────────────────────────────────────────────────────────────
ensure \
  "gcloud compute networks describe $VPC_NAME --project=$PROJECT_ID" \
  "gcloud compute networks create $VPC_NAME \
     --project=$PROJECT_ID \
     --subnet-mode=custom \
     --bgp-routing-mode=regional" \
  "VPC $VPC_NAME"

# ── Subnet (primary + secondary ranges for future GKE) ─────────────────────
ensure \
  "gcloud compute networks subnets describe $SUBNET_NAME \
     --region=$REGION --project=$PROJECT_ID" \
  "gcloud compute networks subnets create $SUBNET_NAME \
     --project=$PROJECT_ID \
     --network=$VPC_NAME \
     --region=$REGION \
     --range=$SUBNET_PRIMARY_RANGE \
     --secondary-range=pods=$SUBNET_SECONDARY_PODS,services=$SUBNET_SECONDARY_SVC \
     --enable-private-ip-google-access" \
  "subnet $SUBNET_NAME"

# ── Cloud Router (prerequisite for Cloud NAT) ──────────────────────────────
ensure \
  "gcloud compute routers describe $ROUTER_NAME \
     --region=$REGION --project=$PROJECT_ID" \
  "gcloud compute routers create $ROUTER_NAME \
     --project=$PROJECT_ID \
     --network=$VPC_NAME \
     --region=$REGION" \
  "Cloud Router $ROUTER_NAME"

# ── Cloud NAT — outbound internet for private VMs ──────────────────────────
ensure \
  "gcloud compute routers nats describe $NAT_NAME \
     --router=$ROUTER_NAME --region=$REGION --project=$PROJECT_ID" \
  "gcloud compute routers nats create $NAT_NAME \
     --project=$PROJECT_ID \
     --router=$ROUTER_NAME \
     --region=$REGION \
     --nat-all-subnet-ip-ranges \
     --auto-allocate-nat-external-ips" \
  "Cloud NAT $NAT_NAME"

# ── Firewall rule: allow SSH from IAP range only ───────────────────────────
ensure \
  "gcloud compute firewall-rules describe datum-allow-iap-ssh --project=$PROJECT_ID" \
  "gcloud compute firewall-rules create datum-allow-iap-ssh \
     --project=$PROJECT_ID \
     --network=$VPC_NAME \
     --direction=INGRESS \
     --action=ALLOW \
     --rules=tcp:22 \
     --source-ranges=$IAP_SOURCE_RANGE \
     --target-tags=ssh-access \
     --description='Allow SSH from Google IAP forwarders only'" \
  "firewall rule datum-allow-iap-ssh"

# ── Firewall rule: allow all internal VPC traffic ──────────────────────────
ensure \
  "gcloud compute firewall-rules describe datum-allow-internal --project=$PROJECT_ID" \
  "gcloud compute firewall-rules create datum-allow-internal \
     --project=$PROJECT_ID \
     --network=$VPC_NAME \
     --direction=INGRESS \
     --action=ALLOW \
     --rules=all \
     --source-ranges=$SUBNET_PRIMARY_RANGE \
     --description='Allow all internal traffic within the primary subnet'" \
  "firewall rule datum-allow-internal"

ok "VPC ready"
