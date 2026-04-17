#!/usr/bin/env bash
# 06-cloud-sql.sh — create the Cloud SQL Postgres instance with private IP,
# add the `datum` database, create the application user, and push the
# connection string into Secret Manager `db-url`.
#
# Provisioning takes 10–15 minutes. The script blocks until the instance is
# RUNNABLE before creating the database and user.
set -euo pipefail
source "$(dirname "$0")/env.sh"

VPC_SELF_LINK="projects/${PROJECT_ID}/global/networks/${VPC_NAME}"

# ── Instance ───────────────────────────────────────────────────────────────
ensure \
  "gcloud sql instances describe $SQL_INSTANCE --project=$PROJECT_ID" \
  "gcloud sql instances create $SQL_INSTANCE \
     --project=$PROJECT_ID \
     --database-version=$SQL_VERSION \
     --tier=$SQL_TIER \
     --region=$REGION \
     --network=$VPC_SELF_LINK \
     --no-assign-ip \
     --storage-size=$SQL_STORAGE_GB \
     --storage-type=SSD \
     --backup-start-time=03:00 \
     --maintenance-window-day=SUN \
     --maintenance-window-hour=04" \
  "Cloud SQL instance $SQL_INSTANCE"

# Wait for the instance to reach RUNNABLE before doing anything else.
say "waiting for $SQL_INSTANCE to become RUNNABLE (may take several minutes)"
until [[ "$(gcloud sql instances describe "$SQL_INSTANCE" \
             --project="$PROJECT_ID" --format='value(state)')" == "RUNNABLE" ]]; do
  printf '.'; sleep 15
done
echo
ok "$SQL_INSTANCE is RUNNABLE"

# ── Database ───────────────────────────────────────────────────────────────
ensure \
  "gcloud sql databases describe $SQL_DATABASE \
     --instance=$SQL_INSTANCE --project=$PROJECT_ID" \
  "gcloud sql databases create $SQL_DATABASE \
     --instance=$SQL_INSTANCE \
     --project=$PROJECT_ID" \
  "database $SQL_DATABASE"

# ── User ───────────────────────────────────────────────────────────────────
if gcloud sql users list --instance="$SQL_INSTANCE" --project="$PROJECT_ID" \
     --format='value(name)' | grep -qx "$SQL_USER"; then
  skip "user $SQL_USER"
  SQL_PASSWORD=""  # unknown; existing password not retrievable
else
  say "creating user $SQL_USER with generated password"
  SQL_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"
  gcloud sql users create "$SQL_USER" \
    --instance="$SQL_INSTANCE" \
    --project="$PROJECT_ID" \
    --password="$SQL_PASSWORD" >/dev/null
  ok "user $SQL_USER"
fi

# ── Store connection string in Secret Manager ──────────────────────────────
# Only push a new version when we know the password (i.e. just created the
# user). Re-runs on an existing user leave the existing secret in place.
if [[ -n "${SQL_PASSWORD:-}" ]]; then
  PRIVATE_IP="$(gcloud sql instances describe "$SQL_INSTANCE" \
                  --project="$PROJECT_ID" \
                  --format='value(ipAddresses[0].ipAddress)')"
  DB_URL="postgresql://${SQL_USER}:${SQL_PASSWORD}@${PRIVATE_IP}:5432/${SQL_DATABASE}"
  echo -n "$DB_URL" | gcloud secrets versions add db-url \
    --project="$PROJECT_ID" \
    --data-file=- >/dev/null
  ok "db-url secret populated with new connection string"
else
  skip "db-url secret (user pre-existed; secret left as-is)"
fi

ok "Cloud SQL ready"
