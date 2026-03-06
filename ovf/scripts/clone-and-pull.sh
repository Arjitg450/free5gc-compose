#!/bin/bash
# Clone free5gc-compose repo to /opt/free5gc-compose, checkout branch, pull images.
# Usage: clone-and-pull.sh [branch]
# Default branch: bootcamp
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Arjitg450/free5gc-compose.git}"
TARGET_DIR="${TARGET_DIR:-/opt/free5gc-compose}"
BRANCH="${1:-bootcamp}"

echo "[clone-and-pull] Target: ${TARGET_DIR}, branch: ${BRANCH}"

if [ -d "${TARGET_DIR}/.git" ]; then
  echo "[clone-and-pull] Repository already exists, fetching and checking out ${BRANCH}..."
  git -C "${TARGET_DIR}" fetch origin
  git -C "${TARGET_DIR}" checkout -f "${BRANCH}" || git -C "${TARGET_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
else
  echo "[clone-and-pull] Cloning from ${REPO_URL}..."
  mkdir -p "$(dirname "${TARGET_DIR}")"
  git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}" 2>/dev/null || \
    git clone "${REPO_URL}" "${TARGET_DIR}" && git -C "${TARGET_DIR}" checkout "${BRANCH}"
fi

echo "[clone-and-pull] Pulling Docker images (this may take several minutes)..."
cd "${TARGET_DIR}"
docker compose pull

echo "[clone-and-pull] Done."
