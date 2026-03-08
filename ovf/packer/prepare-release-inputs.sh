#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_TAR="${SCRIPT_DIR}/free5gc-compose-repo.tar"
ARM64_TAR="${SCRIPT_DIR}/free5gc-images-arm64.tar"
AMD64_TAR="${SCRIPT_DIR}/free5gc-images-amd64.tar"

cd "${REPO_ROOT}"

echo "[prepare-release-inputs] Rebuilding staged repo tar..."
TMPDIR_REPO="$(mktemp -d)"
cleanup() {
  rm -rf "${TMPDIR_REPO}"
}
trap cleanup EXIT

mkdir -p "${TMPDIR_REPO}/free5gc-compose"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --delete \
    --exclude '.DS_Store' \
    --exclude 'ovf/packer/output-qemu/' \
    --exclude 'ovf/packer/output-qemu-amd64/' \
    --exclude 'ovf/release/output/' \
    --exclude 'ovf/packer/logs/' \
    --exclude 'ovf/packer/free5gc-compose-repo.tar' \
    --exclude 'ovf/packer/free5gc-images.tar' \
    --exclude 'ovf/packer/free5gc-images-arm64.tar' \
    --exclude 'ovf/packer/free5gc-images-amd64.tar' \
    "${REPO_ROOT}/" "${TMPDIR_REPO}/free5gc-compose/"
else
  cp -a "${REPO_ROOT}/." "${TMPDIR_REPO}/free5gc-compose/"
  rm -rf \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/output-qemu" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/output-qemu-amd64" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/release/output" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/logs"
  rm -f \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/free5gc-compose-repo.tar" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/free5gc-images.tar" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/free5gc-images-arm64.tar" \
    "${TMPDIR_REPO}/free5gc-compose/ovf/packer/free5gc-images-amd64.tar"
fi

rm -f "${REPO_TAR}"
COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 \
  tar -C "${TMPDIR_REPO}" -cf "${REPO_TAR}" free5gc-compose

echo "[prepare-release-inputs] Validating staged repo tar..."
tar -tf "${REPO_TAR}" >/dev/null
TMPDIR_VERIFY="$(mktemp -d)"
tar -xf "${REPO_TAR}" -C "${TMPDIR_VERIFY}"
test -d "${TMPDIR_VERIFY}/free5gc-compose/.git"
rm -rf "${TMPDIR_VERIFY}"

echo "[prepare-release-inputs] Current staged assets:"
ls -lh "${REPO_TAR}" "${ARM64_TAR}" "${AMD64_TAR}"
