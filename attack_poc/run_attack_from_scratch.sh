#!/bin/bash
# ============================================================================
# run_attack_from_scratch.sh — Run Compromised SMF attack + generate pcap proof
# ============================================================================
# Usage (from free5gc-compose repo root):
#   ./attack_poc/run_attack_from_scratch.sh
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

CAPTURE_DIR="${REPO_ROOT}/attack_poc/captures"
mkdir -p "${CAPTURE_DIR}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PCAP_FILE="${CAPTURE_DIR}/attack_proof_${TIMESTAMP}.pcap"
PROOF_REPORT="${CAPTURE_DIR}/attack_proof_report_${TIMESTAMP}.txt"

COMPOSE_CMD="docker compose -f attack_poc/docker-compose-attack.yaml --project-name free5gc-attack --project-directory ."
WEBUI_URL="http://localhost:5050"

echo "=============================================="
echo " Compromised SMF Attack — Full Run"
echo "=============================================="

# ─── 1. Tear down + wipe DB volume ──────────────────────────────────────────
echo "[1/8] Tearing down existing stack and wiping DB volume..."
./script/attack-down.sh
${COMPOSE_CMD} down --volumes --remove-orphans 2>/dev/null || true
sleep 3

# ─── 2. Bring up the full stack ─────────────────────────────────────────────
echo "[2/8] Bringing up attack stack..."
./script/attack-up.sh
echo "    Waiting 20s for NFs to initialize..."
sleep 20

# ─── 3. Wait for WebUI to accept login ─────────────────────────────────────
echo "[3/8] Waiting for WebUI login to become available..."
for i in $(seq 1 20); do
  login_resp=$(curl -s -X POST "${WEBUI_URL}/api/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"free5gc"}' 2>/dev/null || echo "")
  if echo "$login_resp" | python3 -c "import sys,json; t=json.load(sys.stdin)['access_token']; assert len(t)>10" 2>/dev/null; then
    echo "    WebUI ready (login OK)."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "FATAL: WebUI not ready after 60s. Aborting."
    ${COMPOSE_CMD} logs webui 2>&1 | tail -20
    exit 1
  fi
  sleep 3
done

# ─── 4. Provision subscribers ───────────────────────────────────────────────
echo "[4/8] Provisioning UE1 and UE2..."
export WEBUI_URL
bash "${REPO_ROOT}/attack_poc/provision_subscribers.sh"
sleep 3

# ─── 5. Restart gNB + UEs sequentially (UE1 first, then UE2) ───────────────
echo "[5/8] Restarting gNB + UEs (UE1 first, then UE2 for attack order)..."
${COMPOSE_CMD} stop ueransim-ue1 ueransim-ue2 2>/dev/null || true
${COMPOSE_CMD} restart ueransim-gnb
sleep 5

echo "    Starting UE1..."
${COMPOSE_CMD} start ueransim-ue1
echo "    Waiting 20s for UE1 registration + PDU session..."
sleep 20

# Check UE1 got a tunnel
if docker exec ueransim-ue1 ip addr show uesimtun0 &>/dev/null; then
  echo "    UE1 uesimtun0 is UP."
else
  echo "    WARNING: UE1 uesimtun0 not found. Checking logs..."
  docker logs ueransim-ue1 2>&1 | tail -10
  echo "    Waiting 15s more..."
  sleep 15
fi

echo "    Starting UE2..."
${COMPOSE_CMD} start ueransim-ue2
echo "    Waiting 20s for UE2 registration + PDU session..."
sleep 20

if docker exec ueransim-ue2 ip addr show uesimtun0 &>/dev/null; then
  echo "    UE2 uesimtun0 is UP."
else
  echo "    WARNING: UE2 uesimtun0 not found. Checking logs..."
  docker logs ueransim-ue2 2>&1 | tail -10
  echo "    Waiting 15s more..."
  sleep 15
fi

# ─── 6. Capture N3 GTP-U traffic via gNB container ─────────────────────────
echo "[6/8] Capturing N3 GTP-U traffic..."

echo "    Installing tcpdump in gNB container..."
docker exec ueransim-gnb apt-get update -qq 2>/dev/null
docker exec ueransim-gnb apt-get install -y -qq tcpdump 2>/dev/null

PCAP_CONTAINER="/ueransim/captures/attack_proof_${TIMESTAMP}.pcap"
docker exec -d ueransim-gnb timeout 40 tcpdump -i any -w "${PCAP_CONTAINER}" 'udp port 2152'
sleep 2

echo "    Generating uplink traffic from UE1..."
docker exec ueransim-ue1 ping -I uesimtun0 -c 10 -W 2 8.8.8.8 2>/dev/null || true
echo "    Generating uplink traffic from UE2..."
docker exec ueransim-ue2 ping -I uesimtun0 -c 10 -W 2 8.8.8.8 2>/dev/null || true
echo "    Waiting for pcap flush..."
sleep 5
docker exec ueransim-gnb killall tcpdump 2>/dev/null || true
sleep 2

# ─── 7. Generate proof report ──────────────────────────────────────────────
echo "[7/8] Gathering attack proof..."

{
  echo "=============================================="
  echo " ATTACK PROOF REPORT — ${TIMESTAMP}"
  echo "=============================================="
  echo ""
  echo "--- SMF [ATTACK] log lines ---"
  docker logs smf 2>&1 | grep -iE "ATTACK|SWAP|Session 1|Session 2" || echo "(no attack log lines)"
  echo ""
  echo "--- PFCP associations (SMF <-> UPFs) ---"
  docker logs smf 2>&1 | grep -E "UPF\(10\.100\.200\.(101|102)\)|association" | tail -5
  echo ""
  echo "--- Pcap: ${PCAP_FILE} ---"
  if [ -s "${PCAP_FILE}" ]; then
    echo "Size: $(stat -c%s "${PCAP_FILE}") bytes"
    PKTS=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | wc -l || echo 0)
    echo "GTP-U packets: ${PKTS}"
    echo ""
    echo "--- Sample GTP-U packets ---"
    docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n -v 2>/dev/null | head -40
  else
    echo "Pcap is empty — PDU sessions may not have established."
  fi
  echo ""
  echo "--- GTP-U traffic destination analysis ---"
  TO_UPF1=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | grep -c "10.100.200.101" || echo 0)
  TO_UPF2=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | grep -c "10.100.200.102" || echo 0)
  echo "  Packets involving UPF1 (10.100.200.101): ${TO_UPF1}"
  echo "  Packets involving UPF2 (10.100.200.102): ${TO_UPF2}"
  if [ "${TO_UPF2}" = "0" ] && [ "${TO_UPF1}" -gt 0 ]; then
    echo "  >>> ATTACK CONFIRMED: ALL GTP-U traffic goes to UPF1 only!"
    echo "  >>> UE2 traffic was swapped from UPF2 to UPF1."
  fi
  echo ""
  echo "--- UPF IP reference ---"
  echo "  UPF1 N3: 10.100.200.101 (S-NSSAI 1/010203)"
  echo "  UPF2 N3: 10.100.200.102 (S-NSSAI 1/112233)"
  echo ""
  echo "--- Expected attack result ---"
  echo "  Without attack: UE1 UL -> UPF1 (10.100.200.101), UE2 UL -> UPF2 (10.100.200.102)"
  echo "  With attack:    UE1 UL -> UPF2 (10.100.200.102), UE2 UL -> UPF1 (10.100.200.101)"
  echo ""
  echo "--- UE PDU session status ---"
  echo "UE1:"
  docker exec ueransim-ue1 ip addr show uesimtun0 2>/dev/null || echo "  (no uesimtun0)"
  echo "UE2:"
  docker exec ueransim-ue2 ip addr show uesimtun0 2>/dev/null || echo "  (no uesimtun0)"
} | tee "${PROOF_REPORT}"

echo ""
echo "[8/8] Done."
echo "=============================================="
echo " Pcap:   ${PCAP_FILE}"
echo " Report: ${PROOF_REPORT}"
echo " Open pcap in Wireshark — filter: gtp"
echo " Check ip.dst and gtp.teid to verify swap."
echo "=============================================="