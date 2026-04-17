#!/usr/bin/env bash
# 10-populate-secrets.sh — interactively populate Secret Manager slots
# created by 05-secrets.sh.
#
# Run this from a machine that has gcloud auth'd against the target project
# (Shane's Legion laptop as of 2026-04-17). Prompts for each empty slot.
# Skips slots that already have a version unless --force is passed.
# Always skips aps-refresh-token (rotated by the runtime SA, not populated
# manually).
#
# Designed for partial success: a failure on one secret does not abort the
# rest. A summary prints at the end.

set -uo pipefail
source "$(dirname "$0")/env.sh"

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--force]

Interactively populates empty Secret Manager slots in project \$PROJECT_ID.
  --force   overwrite slots that already have a version.

Always skips aps-refresh-token (runtime-rotated).
Enter an empty value at any prompt to skip that secret.
EOF
      exit 0
      ;;
    *) die "unknown arg: $arg" ;;
  esac
done

# Slots we never populate manually.
RUNTIME_ROTATED=(aps-refresh-token)

is_runtime_rotated() {
  local s="$1"
  for r in "${RUNTIME_ROTATED[@]}"; do
    [[ "$s" == "$r" ]] && return 0
  done
  return 1
}

has_version() {
  local s="$1"
  # Returns 0 if at least one enabled version exists.
  gcloud secrets versions list "$s" \
    --project="$PROJECT_ID" \
    --filter="state=ENABLED" \
    --format="value(name)" 2>/dev/null | grep -q .
}

added=()
skipped=()
failed=()

say "populating secrets in project ${PROJECT_ID} (force=${FORCE})"
echo

for SECRET in "${SECRETS[@]}"; do
  if is_runtime_rotated "$SECRET"; then
    skip "$SECRET (runtime-rotated, not populated here)"
    skipped+=("$SECRET")
    continue
  fi

  if has_version "$SECRET" && [[ $FORCE -eq 0 ]]; then
    skip "$SECRET (already has a version — pass --force to overwrite)"
    skipped+=("$SECRET")
    continue
  fi

  printf "\033[1;36m==> value for %s (empty to skip): \033[0m" "$SECRET"
  # -s hides input; -r avoids backslash interpretation.
  read -r -s value
  echo

  if [[ -z "$value" ]]; then
    skip "$SECRET (empty input)"
    skipped+=("$SECRET")
    continue
  fi

  if printf '%s' "$value" | gcloud secrets versions add "$SECRET" \
       --project="$PROJECT_ID" \
       --data-file=- >/dev/null 2>&1; then
    ok "$SECRET"
    added+=("$SECRET")
  else
    printf "\033[1;31m ✗  %s (gcloud error — run again or check access)\033[0m\n" "$SECRET"
    failed+=("$SECRET")
  fi

  unset value
done

echo
say "summary"
printf "  added:   %s\n" "${added[*]:-(none)}"
printf "  skipped: %s\n" "${skipped[*]:-(none)}"
printf "  failed:  %s\n" "${failed[*]:-(none)}"

# Non-zero exit only if something failed. Missing values (skipped) are fine.
[[ ${#failed[@]} -eq 0 ]] || exit 1
