#!/usr/bin/env bash

set -euo pipefail

NIC_NAME="${1:-enp0s3}"
TEST_HOST="${2:-github.com}"
PRIMARY_DNS="${PRIMARY_DNS:-8.8.8.8}"
SECONDARY_DNS="${SECONDARY_DNS:-1.1.1.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "The '$1' command is required."
}

ensure_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Run this script with sudo so it can repair ${NIC_NAME}, routes, and DNS."
  fi
}

has_default_route() {
  ip route show default | grep -q .
}

can_reach_ip() {
  ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1
}

can_resolve_host() {
  getent hosts "${TEST_HOST}" >/dev/null 2>&1
}

repair_dns() {
  info "Repairing DNS configuration for ${TEST_HOST}..."

  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^systemd-resolved'; then
    systemctl restart systemd-resolved || true
  fi

  if [[ -e /run/systemd/resolve/resolv.conf ]]; then
    ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
  else
    cp /etc/resolv.conf "/etc/resolv.conf.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    cat > /etc/resolv.conf <<EOF
nameserver ${PRIMARY_DNS}
nameserver ${SECONDARY_DNS}
EOF
  fi

  if command -v resolvectl >/dev/null 2>&1; then
    resolvectl flush-caches || true
  fi
}

show_state() {
  info "IPv4 state:"
  ip -4 -br a show "${NIC_NAME}"
  info "Routing table:"
  ip route
  info "Resolver configuration:"
  sed -n '1,5p' /etc/resolv.conf 2>/dev/null || true
}

require_cmd ip
require_cmd dhclient
require_cmd ping
require_cmd getent
ensure_root

"${SCRIPT_DIR}/fix-enp0s3.sh" "${NIC_NAME}"

if ! has_default_route; then
  info "No default route was found; requesting DHCP again on ${NIC_NAME}..."
  dhclient -v "${NIC_NAME}" || die "Failed to obtain a default route on ${NIC_NAME}."
fi

if ! has_default_route; then
  die "${NIC_NAME} still has no default route after DHCP."
fi

if ! can_reach_ip; then
  warn "Raw IP connectivity to 8.8.8.8 is still failing. Trying one more DHCP refresh..."
  dhclient -v "${NIC_NAME}" || true
fi

if ! can_reach_ip; then
  show_state
  die "The VM still cannot reach 8.8.8.8. Fix the hypervisor/VDI network before switching branches."
fi

if ! can_resolve_host; then
  repair_dns
fi

if ! can_resolve_host; then
  show_state
  die "DNS is still broken for ${TEST_HOST}."
fi

show_state
info "VDI network recovery complete. ${TEST_HOST} now resolves."