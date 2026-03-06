#!/bin/bash
# Main Packer provision script: OS, Docker, gtp5g, repo, images, systemd, status/self-test.
# Runs on the VM. Scripts are uploaded to /tmp/free5gc-ovf-scripts by Packer file provisioner.
set -euo pipefail

SCRIPT_DIR="/tmp/free5gc-ovf-scripts"
REPO_URL="${REPO_URL:-https://github.com/Arjitg450/free5gc-compose.git}"
TARGET_DIR="/opt/free5gc-compose"
BRANCH="${BRANCH:-bootcamp}"

export DEBIAN_FRONTEND=noninteractive

echo "=== Provision: OS packages ==="
apt-get update -qq
apt-get install -y -qq \
  curl git jq make gcc net-tools iproute2 python3 python3-pip \
  ca-certificates gnupg lsb-release

echo "=== Provision: Disable unattended-upgrades for reproducibility ==="
apt-get install -y -qq unattended-upgrades 2>/dev/null || true
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
  sed -i 's/^APT::Periodic::Unattended-Upgrade "1";/APT::Periodic::Unattended-Upgrade "0";/' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || true
  echo 'APT::Periodic::Unattended-Upgrade "0";' > /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || true
fi

echo "=== Provision: Docker Engine (pinned) ==="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  VERSION=24.0 sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
  usermod -aG docker ubuntu 2>/dev/null || true
fi
apt-get install -y -qq docker-compose-plugin 2>/dev/null || true
docker --version
docker compose version

echo "=== Provision: gtp5g kernel module ==="
chmod +x "${SCRIPT_DIR}/install-gtp5g.sh"
"${SCRIPT_DIR}/install-gtp5g.sh"

echo "=== Provision: sysctl for forwarding ==="
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-free5gc.conf
sysctl -p /etc/sysctl.d/99-free5gc.conf 2>/dev/null || true

echo "=== Provision: Clone repo and pull images ==="
chmod +x "${SCRIPT_DIR}/clone-and-pull.sh"
REPO_URL="${REPO_URL}" TARGET_DIR="${TARGET_DIR}" "${SCRIPT_DIR}/clone-and-pull.sh" "${BRANCH}"

echo "=== Provision: Install systemd unit ==="
cp "${TARGET_DIR}/ovf/systemd/free5gc-compose.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/free5gc-compose.service
# Ensure start script is executable
chmod +x "${TARGET_DIR}/ovf/scripts/start-free5gc.sh"
systemctl daemon-reload
systemctl enable free5gc-compose.service

echo "=== Provision: Install free5gc-status and self-test.sh ==="
cp "${TARGET_DIR}/ovf/free5gc-status" /usr/local/bin/
cp "${TARGET_DIR}/ovf/self-test.sh" /usr/local/bin/
chmod 755 /usr/local/bin/free5gc-status /usr/local/bin/self-test.sh

echo "=== Provision: Install branch-switch.sh into repo for user convenience ==="
chmod +x "${TARGET_DIR}/ovf/scripts/branch-switch.sh"

echo "=== Provision: Clean up ==="
rm -rf "${SCRIPT_DIR}"
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "=== Provision: Done. First boot will start free5gc-compose.service ==="
