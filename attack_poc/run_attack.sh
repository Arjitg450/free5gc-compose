#!/bin/bash
# ============================================================================
# run_attack.sh — One-Click Compromised SMF Attack Demo
# ============================================================================
#
# This script runs the complete attack from start to finish:
#   1. Builds the compromised SMF Docker image
#   2. Runs the deterministic full proof workflow
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

echo "━━━ Step 1/2: Building compromised SMF image ━━━"
./attack_poc/build_compromised_smf.sh
echo ""

echo "━━━ Step 2/2: Running deterministic attack workflow ━━━"
exec ./attack_poc/run_attack_from_scratch.sh