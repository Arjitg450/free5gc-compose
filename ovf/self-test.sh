#!/bin/bash
# self-test.sh: Verify Docker, compose stack health, and optional UE ping. Exit 0 = PASS, non-zero = FAIL.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/free5gc-compose}"
REASONS=()

# 1. Docker running
if ! docker info >/dev/null 2>&1; then
  REASONS+=("Docker is not running or not accessible")
fi

if [ ${#REASONS[@]} -gt 0 ]; then
  echo "FAIL: ${REASONS[*]}"
  exit 1
fi

# 2. Compose stack
if [ ! -d "${COMPOSE_DIR}" ]; then
  echo "FAIL: ${COMPOSE_DIR} not found"
  exit 1
fi

cd "${COMPOSE_DIR}"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "bootcamp")

if [ "${BRANCH}" = "ieee-10175424" ] && [ -f "attack_poc/docker-compose-attack.yaml" ]; then
  COMPOSE_FILE="attack_poc/docker-compose-attack.yaml"
  PROJECT_NAME="attack_poc"
  # Expected key containers for attack stack
  EXPECTED_CONTAINERS="mongodb nrf amf smf upf1 upf2 ueransim-gnb"
else
  COMPOSE_FILE="docker-compose.yaml"
  PROJECT_NAME="free5gc-compose"
  # Core containers per report (at least these)
  EXPECTED_CONTAINERS="mongodb nrf amf smf upf ueransim"
fi

if ! docker compose -f "${COMPOSE_FILE}" --project-name "${PROJECT_NAME}" --project-directory "${COMPOSE_DIR}" ps --format json 2>/dev/null | grep -q '"State":"running"'; then
  REASONS+=("No compose containers running")
fi

# Count running
RUNNING=$(docker compose -f "${COMPOSE_FILE}" --project-name "${PROJECT_NAME}" --project-directory "${COMPOSE_DIR}" ps -q 2>/dev/null | wc -l)
if [ "${RUNNING}" -lt 3 ]; then
  REASONS+=("Too few containers running (${RUNNING})")
fi

# 3. Optional: UE attach/ping (set RUN_UE_PING=1 to enable; not required for PASS on fresh import)
if [ "${RUN_UE_PING:-0}" = "1" ] && [ "${BRANCH}" = "bootcamp" ]; then
  if docker ps --format '{{.Names}}' | grep -q '^ueransim$'; then
    if ! docker exec ueransim pgrep -x nr-ue >/dev/null 2>&1; then
      docker exec -d ueransim bash -lc "nohup ./nr-ue -c config/uecfg.yaml > /tmp/ue.log 2>&1"
      sleep 20
    fi
    if docker exec ueransim ip addr show uesimtun0 >/dev/null 2>&1; then
      if ! docker exec ueransim ping -I uesimtun0 -c 2 -W 3 8.8.8.8 >/dev/null 2>&1; then
        REASONS+=("UE ping to 8.8.8.8 failed")
      fi
    fi
  fi
fi

if [ ${#REASONS[@]} -gt 0 ]; then
  echo "FAIL: ${REASONS[*]}"
  exit 1
fi

echo "PASS"
exit 0
