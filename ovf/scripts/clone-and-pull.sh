#!/bin/bash
# Stage free5gc-compose into /opt/free5gc-compose from a local bundle or git repo.
# Usage: clone-and-pull.sh [branch]
# Default branch: bootcamp
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Arjitg450/free5gc-compose.git}"
TARGET_DIR="${TARGET_DIR:-/opt/free5gc-compose}"
LOCAL_REPO_DIR="${LOCAL_REPO_DIR:-}"
PULL_IMAGES="${PULL_IMAGES:-0}"
BRANCH="${1:-bootcamp}"

echo "[clone-and-pull] Target: ${TARGET_DIR}, branch: ${BRANCH}"

copy_local_repo() {
  echo "[clone-and-pull] Copying local repo bundle from ${LOCAL_REPO_DIR}..."
  rm -rf "${TARGET_DIR}"
  mkdir -p "${TARGET_DIR}"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "${LOCAL_REPO_DIR}/" "${TARGET_DIR}/"
  else
    cp -a "${LOCAL_REPO_DIR}/." "${TARGET_DIR}/"
  fi
}

if [ -n "${LOCAL_REPO_DIR}" ] && [ -d "${LOCAL_REPO_DIR}" ]; then
  copy_local_repo
elif [ -d "${TARGET_DIR}/.git" ]; then
  echo "[clone-and-pull] Repository already exists, fetching and checking out ${BRANCH}..."
  git -C "${TARGET_DIR}" fetch origin
  git -C "${TARGET_DIR}" checkout -f "${BRANCH}" || git -C "${TARGET_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
else
  echo "[clone-and-pull] Cloning from ${REPO_URL}..."
  mkdir -p "$(dirname "${TARGET_DIR}")"
  git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}" 2>/dev/null || \
    git clone "${REPO_URL}" "${TARGET_DIR}" && git -C "${TARGET_DIR}" checkout "${BRANCH}"
fi

if [ "${PULL_IMAGES}" = "1" ]; then
  echo "[clone-and-pull] Pulling Docker images (this may take several minutes)..."
  cd "${TARGET_DIR}"
  docker compose pull
else
  echo "[clone-and-pull] Skipping explicit docker compose pull; images will be resolved on first startup."
fi

echo "[clone-and-pull] Done."
