#!/usr/bin/env bash

set -euo pipefail

NIC_NAME="${1:-enp0s3}"

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

info() {
  printf '[INFO] %s\n' "$*"
}

command -v ip >/dev/null 2>&1 || die "The 'ip' command is required."
command -v dhclient >/dev/null 2>&1 || die "The 'dhclient' command is required."

if [[ "${EUID}" -ne 0 ]]; then
  die "Run this script with sudo so it can manage ${NIC_NAME}."
fi

if ! ip link show "${NIC_NAME}" >/dev/null 2>&1; then
  die "Interface ${NIC_NAME} was not found."
fi

state="$(ip -br link show dev "${NIC_NAME}" | awk '{print $2}')"
if [[ "${state}" != "UP" ]]; then
  info "Bringing ${NIC_NAME} up..."
  ip link set "${NIC_NAME}" up
else
  info "${NIC_NAME} is already up."
fi

ipv4="$(ip -4 -o addr show dev "${NIC_NAME}" scope global 2>/dev/null | awk '{print $4}' | paste -sd, -)"
if [[ -z "${ipv4}" ]]; then
  info "No IPv4 address is present on ${NIC_NAME}; requesting DHCP..."
  dhclient -v "${NIC_NAME}" || die "DHCP failed on ${NIC_NAME}."
fi

final_ipv4="$(ip -4 -o addr show dev "${NIC_NAME}" scope global 2>/dev/null | awk '{print $4}' | paste -sd, -)"
if [[ -z "${final_ipv4}" ]]; then
  die "DHCP completed but ${NIC_NAME} still has no IPv4 address."
fi

info "Final IPv4 state:"
ip -4 -br a show "${NIC_NAME}"