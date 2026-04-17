# scripts/gcp/env.sh — configuration for the Datum GCP provisioning scripts.
# Source this before running any 0N-*.sh script, or run via 00-provision.sh
# which sources it automatically.
#
# Edit these values before each run. The two that change between personal
# (dry-run) and Grace (production) accounts are PROJECT_ID and BILLING_ACCOUNT.

# ── Account / project ──────────────────────────────────────────────────────
: "${PROJECT_ID:?PROJECT_ID must be set (e.g. export PROJECT_ID=datum-dev-shane)}"
# BILLING_ACCOUNT is documented in 00-provision.sh for the one-time billing
# link step. It's optional at script-run time (billing just needs to be
# linked by the time APIs get enabled).
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"

# ── Region / zone ──────────────────────────────────────────────────────────
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"

# ── VPC / networking ───────────────────────────────────────────────────────
VPC_NAME="datum-vpc"
SUBNET_NAME="datum-${REGION}"
SUBNET_PRIMARY_RANGE="10.10.0.0/20"
SUBNET_SECONDARY_PODS="10.20.0.0/16"
SUBNET_SECONDARY_SVC="10.30.0.0/20"
PSC_RANGE_NAME="datum-psc-range"
PSC_RANGE_START="10.40.0.0"
PSC_RANGE_PREFIX="20"
ROUTER_NAME="datum-router"
NAT_NAME="datum-nat"
IAP_SOURCE_RANGE="35.235.240.0/20"

# ── Service accounts ───────────────────────────────────────────────────────
RUNTIME_SA="datum-runtime-sa"
DEV_SA="datum-dev-sa"

# ── Cloud SQL ──────────────────────────────────────────────────────────────
SQL_INSTANCE="datum-db"
SQL_DATABASE="datum"
SQL_USER="datum_app"
SQL_TIER="db-f1-micro"
SQL_VERSION="POSTGRES_15"
SQL_STORAGE_GB="10"

# ── VMs ────────────────────────────────────────────────────────────────────
RUNTIME_VM="datum-runtime"
DEV_VM="datum-dev"
VM_IMAGE_FAMILY="ubuntu-2404-lts-amd64"
VM_IMAGE_PROJECT="ubuntu-os-cloud"
RUNTIME_MACHINE_TYPE="e2-micro"
DEV_MACHINE_TYPE="e2-standard-2"

# ── Secrets (created as empty slots; values populated later) ───────────────
SECRETS=(
  plex-api-key
  plex-api-secret
  plex-tenant-id
  db-url
  aps-client-id
  aps-client-secret
  aps-refresh-token
)

# ── Helpers ────────────────────────────────────────────────────────────────
# Colored status prints. Keep noise low so piped output stays readable.
say()  { printf "\033[1;36m==> %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m ✓  %s\033[0m\n" "$*"; }
skip() { printf "\033[0;33m -  %s (exists, skipping)\033[0m\n" "$*"; }
die()  { printf "\033[1;31m ✗  %s\033[0m\n" "$*" >&2; exit 1; }

# Idempotency helper: run $2 if $1 returns non-zero (i.e. resource missing).
ensure() {
  local check_cmd="$1"; local create_cmd="$2"; local label="$3"
  if eval "$check_cmd" &>/dev/null; then
    skip "$label"
  else
    say "creating $label"
    eval "$create_cmd" || die "failed to create $label"
    ok "$label"
  fi
}
