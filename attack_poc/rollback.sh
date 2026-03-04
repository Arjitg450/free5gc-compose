#!/bin/bash
# ============================================================================
# rollback.sh — Restore the Original (Non-Compromised) free5gc Deployment
# ============================================================================
#
# This script tears down the attack topology and brings back the original
# single-UPF deployment using unmodified Docker Hub images.
#
# Usage:
#   chmod +x attack_poc/rollback.sh
#   ./attack_poc/rollback.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="${SCRIPT_DIR}/.."

echo "============================================"
echo " Rolling Back to Original Deployment"
echo "============================================"
echo ""

# Step 1: Tear down the attack topology
echo "[1/4] Stopping attack topology..."
cd "${COMPOSE_DIR}"
docker-compose -f attack_poc/docker-compose-attack.yaml down -v 2>/dev/null || true

# Step 2: Remove the compromised SMF image (optional)
echo "[2/4] Removing compromised SMF image..."
docker rmi free5gc/smf:compromised 2>/dev/null || echo "  (image not found, skipping)"

# Step 3: Clean up build artifacts (optional)
echo "[3/4] Cleaning build artifacts..."
if [ -d "${SCRIPT_DIR}/smf-build" ]; then
    echo "  Removing ${SCRIPT_DIR}/smf-build/..."
    rm -rf "${SCRIPT_DIR}/smf-build"
fi

# Step 4: Bring up the original topology
echo "[4/4] Starting original deployment..."
docker-compose up -d

echo ""
echo "============================================"
echo " Rollback Complete"
echo "============================================"
echo ""
echo "The original single-UPF deployment is now running."
echo "Verify with: docker ps"
echo ""
