#!/bin/bash
# ============================================================================
# verify_attack.sh — Verify the Tunnel Swap Attack
# ============================================================================
#
# This script captures GTP-U traffic on the N3 interface and checks if the
# TEIDs are swapped between UPF1 and UPF2.
#
# Usage:
#   chmod +x attack_poc/verify_attack.sh
#   ./attack_poc/verify_attack.sh
# ============================================================================

set -euo pipefail

CAPTURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/captures"
mkdir -p "${CAPTURE_DIR}"

echo "============================================"
echo " Tunnel Swap Attack Verification"
echo "============================================"
echo ""

# ─────────────────────────────────────────────
# Step 1: Check SMF logs for attack indicators
# ─────────────────────────────────────────────
echo "── Step 1: Check SMF Logs for Attack Indicators ──"
echo ""
echo "Looking for [ATTACK] markers in SMF logs..."
echo ""

docker logs smf 2>&1 | grep -i "ATTACK" | tail -20 || echo "  (No attack markers found — SMF may not have processed both sessions yet)"

echo ""

# ─────────────────────────────────────────────
# Step 2: Show PFCP association status
# ─────────────────────────────────────────────
echo "── Step 2: Check PFCP Associations ──"
echo ""
echo "SMF should have PFCP associations with both UPF1 and UPF2:"
docker logs smf 2>&1 | grep -i "PFCP\|association\|UPF" | tail -10 || true

echo ""

# ─────────────────────────────────────────────
# Step 3: Capture GTP-U on the N3 interface
# ─────────────────────────────────────────────
echo "── Step 3: Capture GTP-U Traffic (10 seconds) ──"
echo ""

PCAP_FILE="${CAPTURE_DIR}/n3_attack_capture.pcap"

echo "Capturing GTP-U (port 2152) on br-free5gc for 10 seconds..."
echo "  Output: ${PCAP_FILE}"
echo ""

# Capture on the bridge interface (sees all N3 traffic)
timeout 12 tcpdump -i br-free5gc -w "${PCAP_FILE}" \
    "udp port 2152" \
    -c 100 2>/dev/null &
TCPDUMP_PID=$!

# Generate some traffic from both UEs
echo "  Generating uplink traffic from UE1..."
docker exec ueransim-ue1 ping -I uesimtun0 -c 3 -W 2 8.8.8.8 2>/dev/null || echo "    (UE1 ping may fail if PDU session not fully up)"

echo "  Generating uplink traffic from UE2..."
docker exec ueransim-ue2 ping -I uesimtun0 -c 3 -W 2 8.8.8.8 2>/dev/null || echo "    (UE2 ping may fail if PDU session not fully up)"

# Wait for tcpdump to finish
sleep 5
kill ${TCPDUMP_PID} 2>/dev/null || true
wait ${TCPDUMP_PID} 2>/dev/null || true

echo ""

# ─────────────────────────────────────────────
# Step 4: Analyze the capture
# ─────────────────────────────────────────────
echo "── Step 4: Analyze GTP-U Capture ──"
echo ""

if [ -f "${PCAP_FILE}" ]; then
    echo "GTP-U packets captured. Analyzing TEIDs and destinations..."
    echo ""
    
    # Show GTP-U packets with TEID and IP info
    echo "All GTP-U packets (showing src→dst and TEID):"
    echo "─────────────────────────────────────────────────────"
    tcpdump -r "${PCAP_FILE}" -n -v "udp port 2152" 2>/dev/null | head -30 || true
    echo ""
    
    echo "─────────────────────────────────────────────────────"
    echo ""
    echo "KEY VERIFICATION POINTS:"
    echo ""
    echo "  UPF1 IP: 10.100.200.101"
    echo "  UPF2 IP: 10.100.200.102"
    echo "  gNB  IP: (see gnb.free5gc.org resolution)"
    echo ""
    echo "  WITHOUT attack (normal):"
    echo "    UE1 uplink: gNB → UPF1 (10.100.200.101) with TEID_A"
    echo "    UE2 uplink: gNB → UPF2 (10.100.200.102) with TEID_B"
    echo ""
    echo "  WITH attack (swapped):"
    echo "    UE1 uplink: gNB → UPF2 (10.100.200.102) with TEID_B  ← SWAPPED!"
    echo "    UE2 uplink: gNB → UPF1 (10.100.200.101) with TEID_A  ← SWAPPED!"
    echo ""
    echo "  Check the destination IPs of GTP-U packets from the gNB."
    echo "  If UE1's traffic goes to 10.100.200.102 (UPF2), the attack worked."
    echo ""
else
    echo "  No capture file found. Ensure the topology is running."
fi

# ─────────────────────────────────────────────
# Step 5: Check tunnel endpoints from UERANSIM
# ─────────────────────────────────────────────
echo "── Step 5: Check UE PDU Session Info ──"
echo ""

echo "UE1 network interfaces:"
docker exec ueransim-ue1 ip addr show uesimtun0 2>/dev/null || echo "  (uesimtun0 not found — PDU session may not be established)"
echo ""

echo "UE2 network interfaces:"
docker exec ueransim-ue2 ip addr show uesimtun0 2>/dev/null || echo "  (uesimtun0 not found — PDU session may not be established)"
echo ""

echo "============================================"
echo " Verification Complete"
echo "============================================"
echo ""
echo "For detailed Wireshark analysis:"
echo "  Open ${PCAP_FILE} in Wireshark"
echo "  Filter: gtp"
echo "  Check: GTP-U → TEID field in each packet"
echo "  Verify: destination IPs match the SWAPPED UPF assignment"
