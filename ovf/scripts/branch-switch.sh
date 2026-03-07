#!/bin/bash
# Switch free5gc-compose branch (bootcamp or ieee-10175424).
# For ieee-10175424: optionally build compromised SMF and use attack compose.
# Usage: branch-switch.sh <bootcamp|ieee-10175424>
set -euo pipefail

TARGET_DIR="${TARGET_DIR:-/opt/free5gc-compose}"
BRANCH="${1:-}"

resolve_branch_ref() {
  local requested="$1"

  if [ "${requested}" = "ieee-10175424" ]; then
    if git -C "${TARGET_DIR}" show-ref --verify --quiet "refs/heads/feat/ieee-10175424"; then
      echo "feat/ieee-10175424"
      return 0
    fi
    if git -C "${TARGET_DIR}" show-ref --verify --quiet "refs/remotes/origin/feat/ieee-10175424"; then
      echo "origin/feat/ieee-10175424"
      return 0
    fi
  fi

  if git -C "${TARGET_DIR}" show-ref --verify --quiet "refs/heads/${requested}"; then
    echo "${requested}"
    return 0
  fi

  if git -C "${TARGET_DIR}" show-ref --verify --quiet "refs/remotes/origin/${requested}"; then
    echo "origin/${requested}"
    return 0
  fi

  return 1
}

stop_stack() {
  local compose_file="$1"
  local project_name="$2"

  if [ -f "${TARGET_DIR}/${compose_file}" ]; then
    docker compose -f "${TARGET_DIR}/${compose_file}" \
      --project-name "${project_name}" \
      --project-directory "${TARGET_DIR}" \
      down --remove-orphans >/dev/null 2>&1 || true
  fi
}

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
git worktree prune >/dev/null 2>&1 || true

echo "[branch-switch] Stopping both stack variants to avoid branch cross-contamination..."
stop_stack "docker-compose.yaml" "free5gc-compose"
stop_stack "attack_poc/docker-compose-attack.yaml" "attack_poc"

RESOLVED_BRANCH=$(resolve_branch_ref "${BRANCH}") || {
  echo "[branch-switch] ERROR: unable to resolve branch ${BRANCH}" >&2
  exit 1
}

if [[ "${RESOLVED_BRANCH}" == origin/* ]]; then
  git checkout -B "${BRANCH}" "${RESOLVED_BRANCH}"
else
  git checkout -f "${RESOLVED_BRANCH}"
  if [ "${RESOLVED_BRANCH}" != "${BRANCH}" ]; then
    git branch -f "${BRANCH}" "${RESOLVED_BRANCH}" >/dev/null 2>&1 || true
  fi
fi

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
fi

echo "[branch-switch] Restarting free5gc-compose.service for branch ${BRANCH}..."
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart free5gc-compose.service
else
  "${TARGET_DIR}/ovf/scripts/start-free5gc.sh"
fi

echo "[branch-switch] Done."
