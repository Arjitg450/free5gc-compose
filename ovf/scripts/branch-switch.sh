#!/bin/bash
# Switch free5gc-compose branch (bootcamp or ieee-10175424).
# For ieee-10175424: optionally build compromised SMF and use attack compose.
# Usage: branch-switch.sh <bootcamp|ieee-10175424>
set -euo pipefail

TARGET_DIR="${TARGET_DIR:-/opt/free5gc-compose}"
BRANCH="${1:-}"

if [ -z "${BRANCH}" ]; then
  echo "Usage: $0 <bootcamp|ieee-10175424>"
  echo "Current branch: $(git -C "${TARGET_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
  exit 1
fi

case "${BRANCH}" in
  bootcamp|ieee-10175424) ;;
  *) echo "Invalid branch. Use bootcamp or ieee-10175424"; exit 1 ;;
esac

echo "[branch-switch] Switching to branch: ${BRANCH}"
cd "${TARGET_DIR}"
git fetch origin
git checkout -f "${BRANCH}" 2>/dev/null || git checkout -B "${BRANCH}" "origin/${BRANCH}"

if [ "${BRANCH}" = "ieee-10175424" ]; then
  echo "[branch-switch] IEEE branch: building compromised SMF if not present..."
  if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q 'free5gc/smf:compromised'; then
    if [ -f "${TARGET_DIR}/attack_poc/build_compromised_smf.sh" ]; then
      chmod +x "${TARGET_DIR}/attack_poc/build_compromised_smf.sh"
      "${TARGET_DIR}/attack_poc/build_compromised_smf.sh"
    else
      echo "[branch-switch] WARNING: attack_poc/build_compromised_smf.sh not found. Run it manually for attack stack."
    fi
  else
    echo "[branch-switch] free5gc/smf:compromised already built."
  fi
  echo "[branch-switch] To run attack stack: docker compose -f attack_poc/docker-compose-attack.yaml --project-name attack_poc --project-directory ${TARGET_DIR} up -d"
fi

echo "[branch-switch] Done. Restart free5gc-compose service to use new branch: sudo systemctl restart free5gc-compose"
