#!/usr/bin/env bash
# 00-provision.sh — end-to-end Datum GCP provisioning wrapper.
#
# Usage:
#   export PROJECT_ID=your-project-id
#   export BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX
#   gcloud auth login     # browser flow; do this first
#   gcloud config set project "$PROJECT_ID"
#   gcloud beta billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
#   bash scripts/gcp/00-provision.sh
#
# The script is idempotent. Re-running after a partial failure picks up
# where it left off — each resource check-before-creates.
#
# To tear down: bash scripts/gcp/99-teardown.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"

say "Datum GCP provisioning → project $PROJECT_ID in $REGION"
echo

for phase in 01-apis 02-vpc 03-psc-sql 04-service-accounts 05-secrets 06-cloud-sql 07-vms; do
  echo
  say "Phase: $phase"
  bash "$HERE/${phase}.sh"
done

echo
ok "Provisioning complete."
echo
echo "Next steps:"
echo "  1. Populate secret values:"
for s in "${SECRETS[@]}"; do
  if [[ "$s" != "db-url" ]]; then
    echo "       echo -n 'VALUE' | gcloud secrets versions add $s --data-file=- --project=$PROJECT_ID"
  fi
done
echo "  2. SSH to a VM and confirm connectivity:"
echo "       gcloud compute ssh $RUNTIME_VM --zone=$ZONE --project=$PROJECT_ID --tunnel-through-iap"
echo "  3. Verify Cloud SQL reachable from datum-runtime:"
echo "       gcloud compute ssh $RUNTIME_VM --zone=$ZONE --tunnel-through-iap -- \\"
echo "         'sudo apt-get update && sudo apt-get install -y postgresql-client && \\"
echo "          psql \"\$(gcloud secrets versions access latest --secret=db-url)\" -c \"select 1;\"'"
