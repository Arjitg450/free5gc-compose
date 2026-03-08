#!/bin/bash
# Convert a validated qcow2 into student-facing release assets and checksums.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  package-release-assets.sh \
    --arch <arm64|amd64> \
    --version <vX.Y.Z> \
    --qcow2 <path/to/image.qcow2> \
    [--vm-name <vm name>] \
    [--output-dir <dir>] \
    [--memory <mb>] \
    [--cpus <n>] \
    [--virtualbox-ostype <ostype>] \
    [--skip-ova]

This script keeps the qcow2 as the canonical artifact and derives:
  - qcow2
  - vmdk
  - vdi
  - ovf
  - mf
  - ova (unless --skip-ova is set)
  - SHA256SUMS
  - release metadata
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
  else
    shasum -a 256 "$@"
  fi
}

copy_qcow2_asset() {
  local src="$1"
  local dst="$2"

  if cp -c "$src" "$dst" 2>/dev/null; then
    return 0
  fi

  if cp --reflink=auto "$src" "$dst" 2>/dev/null; then
    return 0
  fi

  cp "$src" "$dst"
}

file_size_bytes() {
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

available_space_bytes() {
  local dir="$1"
  df -Pk "$dir" | awk 'NR==2 {print $4 * 1024}'
}

ARCH=""
VERSION=""
QCOW2=""
VM_NAME=""
OUTPUT_DIR=""
MEMORY="4096"
CPUS="4"
VBOX_OSTYPE=""
SKIP_OVA=0

while [ $# -gt 0 ]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --qcow2) QCOW2="$2"; shift 2 ;;
    --vm-name) VM_NAME="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --memory) MEMORY="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --virtualbox-ostype) VBOX_OSTYPE="$2"; shift 2 ;;
    --skip-ova) SKIP_OVA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[ -n "$ARCH" ] || { echo "--arch is required" >&2; exit 1; }
[ -n "$VERSION" ] || { echo "--version is required" >&2; exit 1; }
[ -n "$QCOW2" ] || { echo "--qcow2 is required" >&2; exit 1; }
[ -f "$QCOW2" ] || { echo "qcow2 not found: $QCOW2" >&2; exit 1; }

case "$ARCH" in
  arm64|amd64) ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

require_cmd qemu-img
require_cmd jq
require_cmd tar

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
VM_NAME="${VM_NAME:-free5gc-lab-${VERSION}-${ARCH}}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/ovf/release/output/${VERSION}/${ARCH}}"
mkdir -p "$OUTPUT_DIR"

BASE_NAME="free5gc-lab-${VERSION}-${ARCH}"
QCOW2_OUT="$OUTPUT_DIR/${BASE_NAME}.qcow2"
VMDK_OUT="$OUTPUT_DIR/${BASE_NAME}.vmdk"
VDI_OUT="$OUTPUT_DIR/${BASE_NAME}.vdi"
OVF_OUT="$OUTPUT_DIR/${BASE_NAME}.ovf"
MF_OUT="$OUTPUT_DIR/${BASE_NAME}.mf"
OVA_OUT="$OUTPUT_DIR/${BASE_NAME}.ova"
METADATA_OUT="$OUTPUT_DIR/${BASE_NAME}.metadata"
CHECKSUMS_OUT="$OUTPUT_DIR/SHA256SUMS"

case "$ARCH" in
  amd64)
    VIRTUAL_SYSTEM_TYPE="virtualbox-2.2"
    CPU_ARCHITECTURE="x86_64"
    GUEST_OS="${VBOX_OSTYPE:-Ubuntu_64}"
    GUEST_DESCRIPTION="Ubuntu_64"
    ;;
  arm64)
    VIRTUAL_SYSTEM_TYPE="virtualbox-2.2"
    CPU_ARCHITECTURE="aarch64"
    GUEST_OS="${VBOX_OSTYPE:-OtherLinux_64}"
    GUEST_DESCRIPTION="OtherLinux_64"
    ;;
esac

DISK_INFO_JSON="$(qemu-img info --output json "$QCOW2")"
DISK_CAPACITY_BYTES="$(printf '%s' "$DISK_INFO_JSON" | jq -r '."virtual-size"')"
QCOW2_ACTUAL_BYTES="$(printf '%s' "$DISK_INFO_JSON" | jq -r '."actual-size"')"
DISK_ID="vmdisk1"
FILE_ID="file1"
INSTANCE_ID="${BASE_NAME}"
REQUIRED_FREE_BYTES=$((QCOW2_ACTUAL_BYTES * 4 + 2147483648))
AVAILABLE_FREE_BYTES="$(available_space_bytes "$OUTPUT_DIR")"

if [ "$AVAILABLE_FREE_BYTES" -lt "$REQUIRED_FREE_BYTES" ]; then
  echo "Not enough free space in $OUTPUT_DIR" >&2
  echo "Need at least $REQUIRED_FREE_BYTES bytes, have $AVAILABLE_FREE_BYTES bytes." >&2
  echo "The release packager duplicates the image into qcow2, vmdk, vdi, and ovf/ova assets." >&2
  exit 1
fi

echo "[release] Converting qcow2 -> vmdk..."
qemu-img convert -p -O vmdk -o subformat=streamOptimized "$QCOW2" "$VMDK_OUT" &
VMDK_PID=$!

echo "[release] Converting qcow2 -> vdi..."
qemu-img convert -p -O vdi "$QCOW2" "$VDI_OUT" &
VDI_PID=$!

wait "$VMDK_PID"
wait "$VDI_PID"

echo "[release] Creating qcow2 release asset..."
copy_qcow2_asset "$QCOW2" "$QCOW2_OUT"

VMDK_SIZE_BYTES="$(file_size_bytes "$VMDK_OUT")"

cat >"$METADATA_OUT" <<EOF
version=${VERSION}
git_commit=${COMMIT}
architecture=${ARCH}
vm_name=${VM_NAME}
memory_mb=${MEMORY}
cpus=${CPUS}
supported_hypervisors=qemu,virtualbox,vmware
source_qcow2=$(basename "$QCOW2_OUT")
derived_vmdk=$(basename "$VMDK_OUT")
derived_vdi=$(basename "$VDI_OUT")
descriptor_ovf=$(basename "$OVF_OUT")
descriptor_manifest=$(basename "$MF_OUT")
EOF

cat >"$OVF_OUT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1"
          xmlns:cim="http://schemas.dmtf.org/wbem/wscim/1/common"
          xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1"
          xmlns:rasd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
          xmlns:vssd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
          xmlns:vmw="http://www.vmware.com/schema/ovf"
          xmlns:vbox="http://www.virtualbox.org/ovf/machine">
  <References>
    <File ovf:href="$(basename "$VMDK_OUT")" ovf:id="${FILE_ID}" ovf:size="${VMDK_SIZE_BYTES}"/>
  </References>
  <DiskSection>
    <Info>Virtual disk information</Info>
    <Disk ovf:capacity="${DISK_CAPACITY_BYTES}" ovf:capacityAllocationUnits="byte"
          ovf:diskId="${DISK_ID}" ovf:fileRef="${FILE_ID}"
          ovf:format="http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized"/>
  </DiskSection>
  <NetworkSection>
    <Info>Logical networks</Info>
    <Network ovf:name="NAT">
      <Description>Default NAT network</Description>
    </Network>
  </NetworkSection>
  <VirtualSystem ovf:id="${INSTANCE_ID}">
    <Info>free5GC student lab appliance</Info>
    <Name>${VM_NAME}</Name>
    <OperatingSystemSection ovf:id="94" vmw:osType="${GUEST_OS}">
      <Info>Ubuntu 22.04 guest</Info>
      <Description>${GUEST_DESCRIPTION}</Description>
    </OperatingSystemSection>
    <VirtualHardwareSection>
      <Info>Virtual hardware requirements</Info>
      <System>
        <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>
        <vssd:InstanceID>0</vssd:InstanceID>
        <vssd:VirtualSystemIdentifier>${VM_NAME}</vssd:VirtualSystemIdentifier>
        <vssd:VirtualSystemType>${VIRTUAL_SYSTEM_TYPE}</vssd:VirtualSystemType>
      </System>
      <Item>
        <rasd:AllocationUnits>hertz * 10^6</rasd:AllocationUnits>
        <rasd:Description>Number of virtual CPUs</rasd:Description>
        <rasd:ElementName>${CPUS} virtual CPU(s)</rasd:ElementName>
        <rasd:InstanceID>1</rasd:InstanceID>
        <rasd:ResourceType>3</rasd:ResourceType>
        <rasd:VirtualQuantity>${CPUS}</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:AllocationUnits>byte * 2^20</rasd:AllocationUnits>
        <rasd:Description>Memory Size</rasd:Description>
        <rasd:ElementName>${MEMORY} MB of memory</rasd:ElementName>
        <rasd:InstanceID>2</rasd:InstanceID>
        <rasd:ResourceType>4</rasd:ResourceType>
        <rasd:VirtualQuantity>${MEMORY}</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:Address>0</rasd:Address>
        <rasd:Description>SATA Controller</rasd:Description>
        <rasd:ElementName>SATA Controller</rasd:ElementName>
        <rasd:InstanceID>3</rasd:InstanceID>
        <rasd:ResourceSubType>AHCI</rasd:ResourceSubType>
        <rasd:ResourceType>20</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:Description>Disk Image</rasd:Description>
        <rasd:ElementName>Hard disk</rasd:ElementName>
        <rasd:HostResource>ovf:/disk/${DISK_ID}</rasd:HostResource>
        <rasd:InstanceID>4</rasd:InstanceID>
        <rasd:Parent>3</rasd:Parent>
        <rasd:ResourceType>17</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AutomaticAllocation>true</rasd:AutomaticAllocation>
        <rasd:Connection>NAT</rasd:Connection>
        <rasd:Description>E1000 Ethernet adapter</rasd:Description>
        <rasd:ElementName>ethernet0</rasd:ElementName>
        <rasd:InstanceID>5</rasd:InstanceID>
        <rasd:ResourceSubType>E1000</rasd:ResourceSubType>
        <rasd:ResourceType>10</rasd:ResourceType>
      </Item>
    </VirtualHardwareSection>
    <AnnotationSection>
      <Info>Release metadata</Info>
      <Annotation>Version ${VERSION}, commit ${COMMIT}, architecture ${ARCH}, guest CPU ${CPU_ARCHITECTURE}</Annotation>
    </AnnotationSection>
  </VirtualSystem>
</Envelope>
EOF

(
  cd "$OUTPUT_DIR"
  sha256_file "$(basename "$OVF_OUT")" "$(basename "$VMDK_OUT")" >"$MF_OUT"
)

if [ $SKIP_OVA -eq 0 ]; then
  echo "[release] Assembling OVA..."
  (
    cd "$OUTPUT_DIR"
    rm -f "$(basename "$OVA_OUT")"
    tar -cf "$(basename "$OVA_OUT")" \
      "$(basename "$OVF_OUT")" \
      "$(basename "$MF_OUT")" \
      "$(basename "$VMDK_OUT")"
  )
else
  echo "[release] Skipping OVA export (--skip-ova set)."
fi

(
  cd "$OUTPUT_DIR"
  rm -f "$CHECKSUMS_OUT"
  if [ -f "$(basename "$OVA_OUT")" ]; then
    sha256_file \
      "$(basename "$QCOW2_OUT")" \
      "$(basename "$VMDK_OUT")" \
      "$(basename "$VDI_OUT")" \
      "$(basename "$OVF_OUT")" \
      "$(basename "$MF_OUT")" \
      "$(basename "$OVA_OUT")" \
      "$(basename "$METADATA_OUT")" >"$CHECKSUMS_OUT"
  else
    sha256_file \
      "$(basename "$QCOW2_OUT")" \
      "$(basename "$VMDK_OUT")" \
      "$(basename "$VDI_OUT")" \
      "$(basename "$OVF_OUT")" \
      "$(basename "$MF_OUT")" \
      "$(basename "$METADATA_OUT")" >"$CHECKSUMS_OUT"
  fi
)

echo "[release] Assets created in $OUTPUT_DIR"
