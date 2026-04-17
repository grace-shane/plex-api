#!/usr/bin/env bash
# 08-scheduler.sh — Cloud Scheduler jobs to start/stop datum-dev on a
# weekday-only schedule (07:00 / 19:00 America/Chicago, Mon–Fri).
#
# Why: datum-dev is an e2-standard-2 — on at all times it's ~$50/mo.
# Running it only during weekday business hours cuts that to ~$15/mo
# and forces us to keep VM setup scripted (state rots if we leave it
# on for weeks).
#
# Mechanism: two HTTP-target Cloud Scheduler jobs hitting the Compute
# Engine REST API (.../instances/<name>/start and .../stop), authenticating
# with OAuth using the runtime service account.
#
# IAM: the runtime SA is granted roles/compute.instanceAdmin.v1 scoped
# to the datum-dev instance only (not project-level), so it can still
# only touch that one VM.
set -euo pipefail
source "$(dirname "$0")/env.sh"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULE_TZ="America/Chicago"
START_JOB="datum-dev-start"
STOP_JOB="datum-dev-stop"
START_SCHEDULE="0 7 * * 1-5"
STOP_SCHEDULE="0 19 * * 1-5"
DEV_VM_URI="https://compute.googleapis.com/compute/v1/projects/${PROJECT_ID}/zones/${ZONE}/instances/${DEV_VM}"

# ── Instance-level IAM for the runtime SA ──────────────────────────────────
# add-iam-policy-binding is idempotent — re-running is a no-op if the
# binding already exists.
say "granting $RUNTIME_SA start/stop on instance $DEV_VM"
gcloud compute instances add-iam-policy-binding "$DEV_VM" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --member="serviceAccount:$RUNTIME_EMAIL" \
  --role="roles/compute.instanceAdmin.v1" \
  --condition=None \
  --quiet >/dev/null
ok "instance IAM binding applied"

# ── Start job (weekdays 07:00 America/Chicago) ─────────────────────────────
ensure \
  "gcloud scheduler jobs describe $START_JOB --location=$REGION --project=$PROJECT_ID" \
  "gcloud scheduler jobs create http $START_JOB \
     --project=$PROJECT_ID \
     --location=$REGION \
     --schedule='$START_SCHEDULE' \
     --time-zone='$SCHEDULE_TZ' \
     --uri='${DEV_VM_URI}/start' \
     --http-method=POST \
     --oauth-service-account-email=$RUNTIME_EMAIL \
     --description='Start $DEV_VM weekday mornings (07:00 CT)'" \
  "scheduler job $START_JOB"

# ── Stop job (weekdays 19:00 America/Chicago) ──────────────────────────────
ensure \
  "gcloud scheduler jobs describe $STOP_JOB --location=$REGION --project=$PROJECT_ID" \
  "gcloud scheduler jobs create http $STOP_JOB \
     --project=$PROJECT_ID \
     --location=$REGION \
     --schedule='$STOP_SCHEDULE' \
     --time-zone='$SCHEDULE_TZ' \
     --uri='${DEV_VM_URI}/stop' \
     --http-method=POST \
     --oauth-service-account-email=$RUNTIME_EMAIL \
     --description='Stop $DEV_VM weekday evenings (19:00 CT)'" \
  "scheduler job $STOP_JOB"

ok "scheduler jobs ready"
echo
echo "Manual trigger (useful for testing or a one-off late night):"
echo "  gcloud scheduler jobs run $START_JOB --location=$REGION --project=$PROJECT_ID"
echo "  gcloud scheduler jobs run $STOP_JOB  --location=$REGION --project=$PROJECT_ID"
