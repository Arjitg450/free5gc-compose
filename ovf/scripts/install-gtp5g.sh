#!/bin/bash
# Build and load gtp5g kernel module (required for free5gc UPF).
# Must run as root. Requires linux-headers for current kernel.
set -euo pipefail

echo "[gtp5g] Installing build dependencies..."
apt-get update -qq
apt-get install -y -qq linux-headers-"$(uname -r)" build-essential git

echo "[gtp5g] Cloning and building gtp5g..."
GTP5G_DIR=/tmp/gtp5g
rm -rf "${GTP5G_DIR}"
git clone --branch v0.9.5 --depth 1 https://github.com/free5gc/gtp5g.git "${GTP5G_DIR}"
cd "${GTP5G_DIR}"
make
make install
cd -
rm -rf "${GTP5G_DIR}"

echo "[gtp5g] Loading module..."
modprobe gtp5g

echo "[gtp5g] Ensuring gtp5g loads at boot..."
echo 'gtp5g' > /etc/modules-load.d/free5gc.conf

echo "[gtp5g] Verifying..."
lsmod | grep -q gtp5g || { echo "ERROR: gtp5g not loaded"; exit 1; }
echo "[gtp5g] Done."
