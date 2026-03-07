#!/bin/bash
# Start free5gc-compose stack based on current git branch.
# Used by systemd free5gc-compose.service.
# Waits for Docker and retries compose up.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/free5gc-compose}"
MAX_TRIES=5
SLEEP=10

resolve_branch_name() {
  local requested="$1"

  if [ "${requested}" = "ieee-10175424" ] && git -C "${COMPOSE_DIR}" show-ref --verify --quiet "refs/heads/feat/ieee-10175424"; then
    echo "feat/ieee-10175424"
    return 0
  fi

  echo "${requested}"
}

wait_for_docker() {
  local i=0
  while ! docker info >/dev/null 2>&1; do
    i=$((i + 1))
    [ $i -ge 30 ] && { echo "Docker not ready after 30 attempts"; return 1; }
    sleep 2
  done
  return 0
}

do_compose_up() {
  local project_dir="$1"
  local compose_file="$2"
  local project_name="${3:-free5gc-compose}"
  cd "${project_dir}"
  if [ -n "${compose_file}" ] && [ -f "${compose_file}" ]; then
    docker compose -f "${compose_file}" --project-name "${project_name}" --project-directory "${project_dir}" up -d
  else
    docker compose --project-directory "${project_dir}" up -d
  fi
}

stop_inactive_projects() {
  local active_project="$1"

  if [ "${active_project}" != "free5gc-compose" ] && [ -f "${COMPOSE_DIR}/docker-compose.yaml" ]; then
    docker compose --project-name free5gc-compose --project-directory "${COMPOSE_DIR}" down --remove-orphans >/dev/null 2>&1 || true
  fi

  if [ "${active_project}" != "attack_poc" ] && [ -f "${COMPOSE_DIR}/attack_poc/docker-compose-attack.yaml" ]; then
    docker compose -f "${COMPOSE_DIR}/attack_poc/docker-compose-attack.yaml" \
      --project-name attack_poc \
      --project-directory "${COMPOSE_DIR}" \
      down --remove-orphans >/dev/null 2>&1 || true
  fi
}

echo "[start-free5gc] Waiting for Docker..."
wait_for_docker || exit 1

[ ! -d "${COMPOSE_DIR}" ] && { echo "[start-free5gc] ${COMPOSE_DIR} not found"; exit 1; }

BRANCH=$(git -C "${COMPOSE_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "bootcamp")
BRANCH=$(resolve_branch_name "${BRANCH}")

if [ "${BRANCH}" = "ieee-10175424" ] || [ "${BRANCH}" = "feat/ieee-10175424" ]; then
  COMPOSE_FILE="attack_poc/docker-compose-attack.yaml"
  PROJECT_NAME="attack_poc"
else
  COMPOSE_FILE="docker-compose.yaml"
  PROJECT_NAME="free5gc-compose"
fi

stop_inactive_projects "${PROJECT_NAME}"

tries=0
while [ $tries -lt $MAX_TRIES ]; do
  if do_compose_up "${COMPOSE_DIR}" "${COMPOSE_FILE}" "${PROJECT_NAME}"; then
    echo "[start-free5gc] Stack started (branch=${BRANCH})."
    exit 0
  fi
  tries=$((tries + 1))
  echo "[start-free5gc] Attempt $tries failed, retrying in ${SLEEP}s..."
  sleep "$SLEEP"
done

echo "[start-free5gc] Failed after ${MAX_TRIES} attempts."
exit 1
