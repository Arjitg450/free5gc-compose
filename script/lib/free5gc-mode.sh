#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAB_NETWORK_NAME="free5gc-lab-net"
LAB_SUBNET="10.100.200.0/24"
LAB_NIC="${FREE5GC_LAB_NIC:-enp0s3}"

NORMAL_PROJECT="free5gc-normal"
ATTACK_PROJECT="free5gc-attack"
LEGACY_NORMAL_PROJECT="free5gc-compose"
LEGACY_ATTACK_PROJECT="attack_poc"

NORMAL_COMPOSE_FILE="${REPO_ROOT}/docker-compose.yaml"
ATTACK_COMPOSE_FILE="${REPO_ROOT}/attack_poc/docker-compose-attack.yaml"
NIC_FIX_SCRIPT="${REPO_ROOT}/script/fix-enp0s3.sh"
SMF_ATTACK_IMAGE="free5gc/smf:compromised"

info() {
  printf '[INFO] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

compose_cmd() {
  local project="$1"
  local compose_file="$2"
  shift 2
  docker compose \
    --project-name "${project}" \
    --project-directory "${REPO_ROOT}" \
    -f "${compose_file}" \
    "$@"
}

project_has_resources() {
  local project="$1"
  [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=${project}")" ]] \
    || [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=${project}")" ]]
}

is_repo_project() {
  case "$1" in
    "${NORMAL_PROJECT}"|"${ATTACK_PROJECT}"|"${LEGACY_NORMAL_PROJECT}"|"${LEGACY_ATTACK_PROJECT}")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_repo_network_name() {
  case "$1" in
    "${LAB_NETWORK_NAME}"|"${LEGACY_NORMAL_PROJECT}_privnet"|"${LEGACY_ATTACK_PROJECT}_privnet")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

collect_subnet_networks() {
  local network_id network_name project attached containers count

  while read -r network_id network_name; do
    [[ -n "${network_id}" ]] || continue
    if docker network inspect --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' "${network_id}" 2>/dev/null \
      | grep -Fxq "${LAB_SUBNET}"; then
      project="$(docker network inspect --format '{{index .Labels "com.docker.compose.project"}}' "${network_id}" 2>/dev/null || true)"
      if [[ "${project}" == "<no value>" ]]; then
        project=""
      fi

      attached="$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "${network_id}" 2>/dev/null || true)"
      attached="$(printf '%s\n' "${attached}" | sed '/^$/d')"

      if [[ -n "${attached}" ]]; then
        containers="$(printf '%s\n' "${attached}" | paste -sd, -)"
        count="$(printf '%s\n' "${attached}" | wc -l | tr -d ' ')"
      else
        containers=""
        count="0"
      fi

      printf '%s|%s|%s|%s\n' "${network_name}" "${project}" "${count}" "${containers}"
    fi
  done < <(docker network ls --format '{{.ID}} {{.Name}}')
}

print_subnet_report() {
  local found=0
  info "Inspecting Docker networks that claim ${LAB_SUBNET}..."
  while IFS='|' read -r network_name project count containers; do
    found=1
    if [[ -n "${project}" ]]; then
      info "  - ${network_name} (compose project: ${project}, attached containers: ${count}${containers:+, ${containers}})"
    else
      info "  - ${network_name} (attached containers: ${count}${containers:+, ${containers}})"
    fi
  done < <(collect_subnet_networks)

  if [[ "${found}" -eq 0 ]]; then
    info "No Docker network is currently using ${LAB_SUBNET}."
  fi
}

ensure_docker_ready() {
  command -v docker >/dev/null 2>&1 || die "Docker CLI is not installed or not in PATH."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required. Install the 'docker compose' plugin."
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable. Start Docker and rerun this command."
}

warn_if_lab_nic_unhealthy() {
  if ! command -v ip >/dev/null 2>&1; then
    warn "The 'ip' command is unavailable, so ${LAB_NIC} preflight checks were skipped."
    return
  fi

  if ! ip link show "${LAB_NIC}" >/dev/null 2>&1; then
    warn "Interface ${LAB_NIC} is not present. Ignore this if your VM uses a different management NIC."
    return
  fi

  local state ipv4
  state="$(ip -br link show dev "${LAB_NIC}" | awk '{print $2}')"
  ipv4="$(ip -4 -o addr show dev "${LAB_NIC}" scope global 2>/dev/null | awk '{print $4}' | paste -sd, -)"

  if [[ "${state}" != "UP" || -z "${ipv4}" ]]; then
    warn "Interface ${LAB_NIC} is not healthy for lab access (state=${state:-unknown}, ipv4=${ipv4:-none})."
    warn "Run ${NIC_FIX_SCRIPT} with sudo if you lose SSH or package/Docker connectivity inside the VM."
  else
    info "Management NIC ${LAB_NIC} is up with IPv4 ${ipv4}."
  fi
}

stop_project_if_present() {
  local project="$1"
  local compose_file="$2"
  local label="$3"

  if project_has_resources "${project}"; then
    info "Stopping ${label} (${project})..."
    compose_cmd "${project}" "${compose_file}" down --remove-orphans
  fi
}

cleanup_known_orphan_networks() {
  local removed=0

  while IFS='|' read -r network_name _project count _containers; do
    if is_repo_network_name "${network_name}" && [[ "${count}" == "0" ]]; then
      info "Removing stale repo network ${network_name}."
      docker network rm "${network_name}" >/dev/null
      removed=1
    fi
  done < <(collect_subnet_networks)

  if [[ "${removed}" -eq 1 ]]; then
    info "Repo-owned orphan networks were cleaned up."
  fi
}

ensure_no_blocking_conflicts() {
  local target_project="$1"
  local blocking=0

  while IFS='|' read -r network_name project count containers; do
    if ! is_repo_network_name "${network_name}" && ! is_repo_project "${project}"; then
      warn "Unrelated Docker network '${network_name}' already uses ${LAB_SUBNET}."
      if [[ "${count}" != "0" ]]; then
        warn "Attached containers: ${containers}"
      fi
      blocking=1
      continue
    fi

    if [[ "${count}" != "0" && -n "${project}" && "${project}" != "${target_project}" ]]; then
      warn "Repo network '${network_name}' still has active containers from project '${project}': ${containers}"
      blocking=1
    fi
  done < <(collect_subnet_networks)

  if [[ "${blocking}" -eq 1 ]]; then
    cat >&2 <<EOF
[ERROR] Startup was stopped before Docker tried to allocate ${LAB_SUBNET}.
[ERROR] I only auto-clean repo-owned projects (${NORMAL_PROJECT}, ${ATTACK_PROJECT}, ${LEGACY_NORMAL_PROJECT}, ${LEGACY_ATTACK_PROJECT}).
[ERROR] Inspect the remaining networks with:
  docker network ls
  docker network inspect <network-name>
  docker ps -a --filter network=<network-name>
EOF
    exit 1
  fi
}

ensure_attack_image_present() {
  if ! docker image inspect "${SMF_ATTACK_IMAGE}" >/dev/null 2>&1; then
    die "Missing ${SMF_ATTACK_IMAGE}. Build it first with ${REPO_ROOT}/attack_poc/build_compromised_smf.sh."
  fi
}

preflight() {
  ensure_docker_ready
  warn_if_lab_nic_unhealthy
  print_subnet_report
}

stop_normal_mode() {
  preflight
  stop_project_if_present "${NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" "normal stack"
  stop_project_if_present "${LEGACY_NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" "legacy normal stack"
  cleanup_known_orphan_networks
  print_subnet_report
}

stop_attack_mode() {
  preflight
  stop_project_if_present "${ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "attack stack"
  stop_project_if_present "${LEGACY_ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "legacy attack stack"
  cleanup_known_orphan_networks
  print_subnet_report
}

start_normal_mode() {
  preflight
  stop_project_if_present "${ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "attack stack"
  stop_project_if_present "${LEGACY_ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "legacy attack stack"
  stop_project_if_present "${LEGACY_NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" "legacy normal stack"
  cleanup_known_orphan_networks
  ensure_no_blocking_conflicts "${NORMAL_PROJECT}"
  info "Starting normal stack with project ${NORMAL_PROJECT}..."
  compose_cmd "${NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" up -d
  info "Normal mode is up. Verify with: docker compose --project-name ${NORMAL_PROJECT} --project-directory ${REPO_ROOT} -f ${NORMAL_COMPOSE_FILE} ps"
}

start_attack_mode() {
  preflight
  ensure_attack_image_present
  stop_project_if_present "${NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" "normal stack"
  stop_project_if_present "${LEGACY_NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" "legacy normal stack"
  stop_project_if_present "${LEGACY_ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "legacy attack stack"
  cleanup_known_orphan_networks
  ensure_no_blocking_conflicts "${ATTACK_PROJECT}"
  info "Starting attack stack with project ${ATTACK_PROJECT}..."
  compose_cmd "${ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" up -d
  info "Attack mode is up. Verify with: docker compose --project-name ${ATTACK_PROJECT} --project-directory ${REPO_ROOT} -f ${ATTACK_COMPOSE_FILE} ps"
}

rollback_to_normal_mode() {
  preflight
  stop_project_if_present "${ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "attack stack"
  stop_project_if_present "${LEGACY_ATTACK_PROJECT}" "${ATTACK_COMPOSE_FILE}" "legacy attack stack"
  cleanup_known_orphan_networks
  ensure_no_blocking_conflicts "${NORMAL_PROJECT}"
  info "Starting normal stack after attack rollback..."
  compose_cmd "${NORMAL_PROJECT}" "${NORMAL_COMPOSE_FILE}" up -d
  info "Rollback complete. Normal mode is up."
}