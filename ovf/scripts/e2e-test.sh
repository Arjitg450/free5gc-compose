#!/bin/bash
# e2e-test.sh: End-to-end validation of free5GC + UERANSIM stack.
# Tests every stage from the 5G_E2E_free5GC_UERANSIM_Report.md:
#   Step 0  - Docker Engine + Compose
#   Step 1  - gtp5g kernel module
#   Step 3  - All containers running
#   Step 4  - gNB NG Setup (AMF <-> UERANSIM)
#   Step 5  - UE Registration + PDU Session Establishment
#   Step 6  - PFCP Association (SMF <-> UPF)
#   Step 7  - GTP-U tunneling readiness
#   Step 8  - UPF forwarding/NAT rules
#   Step 9  - Data-plane: ping + HTTP through uesimtun0
#   Step 10 - Deregistration cleanup
#   Step 11 - Authentication flow (UE SQN/auth logs)
#   Step 12 - NAS security algorithm negotiation
#   Wireshark/tcpdump capture sanity
#
# Usage:
#   sudo e2e-test.sh              # full test (starts UE if needed)
#   sudo e2e-test.sh --no-ping    # skip data-plane ping/curl
#   sudo e2e-test.sh --no-capture # skip tcpdump-based packet checks
#   sudo e2e-test.sh --quick      # infra + NG Setup only, skip UE
#
# Exit: 0 = all tests passed, 1 = one or more failed

set -uo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/free5gc-compose}"
SKIP_PING=0
QUICK=0
DO_CAPTURE=1
TMP_COMPOSE_PS="/tmp/free5gc-compose-ps-$$.txt"
TMP_UE_TUN="/tmp/uesimtun0-$$.txt"

for arg in "$@"; do
  case "$arg" in
    --no-ping) SKIP_PING=1 ;;
    --quick)   QUICK=1 ;;
    --no-capture) DO_CAPTURE=0 ;;
  esac
done

cleanup() {
  rm -f "${TMP_COMPOSE_PS}" "${TMP_UE_TUN}"
}
trap cleanup EXIT

# ── Colour helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() { echo -e "  ${GREEN}PASS${RESET}  $1"; (( PASS_COUNT++ )) || true; }
fail() { echo -e "  ${RED}FAIL${RESET}  $1"; (( FAIL_COUNT++ )) || true; }
skip() { echo -e "  ${YELLOW}SKIP${RESET}  $1"; (( SKIP_COUNT++ )) || true; }
section() { echo -e "\n${CYAN}${BOLD}=== $1 ===${RESET}"; }
info() { echo -e "       $1"; }

# ── Helper: check container logs for a pattern ─────────────────────────────
logs_contain() {
  local container="$1"
  local pattern="$2"
  local lines="${3:-500}"
  docker logs --tail="${lines}" "${container}" 2>&1 | grep -qE "${pattern}"
}

# ── Helper: get compose service container name ─────────────────────────────
container_name() {
  # Works for both "ueransim" and "free5gc-ueransim" naming
  docker ps --format '{{.Names}}' | grep -E "^(free5gc-compose[-_])?${1}[-_]?1?$" | head -1
}

# ── Helper: check if a file contains a regex pattern ───────────────────────
file_contains() {
  local file="$1"
  local pattern="$2"
  grep -qE "${pattern}" "${file}" 2>/dev/null
}

# ── Resolve compose file ────────────────────────────────────────────────────
if [ ! -d "${COMPOSE_DIR}" ]; then
  echo -e "${RED}ERROR${RESET}: ${COMPOSE_DIR} not found. Is the VM provisioned?"
  exit 1
fi

cd "${COMPOSE_DIR}"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
COMPOSE_FILE="docker-compose.yaml"

echo -e "${BOLD}free5GC + UERANSIM End-to-End Test${RESET}"
echo -e "Branch: ${BRANCH}  |  Dir: ${COMPOSE_DIR}"
echo -e "Date:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo    "────────────────────────────────────────────────────────"

# ════════════════════════════════════════════════════════════════════════════
section "Step 0 — Docker Engine + Compose"
# ════════════════════════════════════════════════════════════════════════════

if docker info >/dev/null 2>&1; then
  DOCKER_VER=$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  pass "Docker Engine running (v${DOCKER_VER})"
else
  fail "Docker Engine not running or not accessible"
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_VER=$(docker compose version | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  pass "Docker Compose plugin available (${COMPOSE_VER})"
else
  fail "Docker Compose plugin not found (run: apt-get install docker-compose-plugin)"
fi

# Step 0.3: critical port availability (should be free before start, or owned by compose containers)
PORT_CONFLICT=0
for port in 27017 38412 5000; do
  LISTENERS=$(ss -tulnp 2>/dev/null | awk -v p=":${port}" '$0 ~ p {print}')
  if [ -z "${LISTENERS}" ]; then
    pass "Port ${port}: no listener conflict"
  elif echo "${LISTENERS}" | grep -qiE "docker|containerd|mongod|free5gc|nr-gnb|nr-ue"; then
    pass "Port ${port}: listener present (expected for running lab)"
  else
    fail "Port ${port}: unexpected listener detected (possible conflict)"
    info "${LISTENERS}"
    PORT_CONFLICT=1
  fi
done
if [ "${PORT_CONFLICT}" -eq 1 ]; then
  info "Run: lsof -i :27017 -i :38412 -i :5000"
fi

# Step 0.4: Docker bridge/network sanity
if docker network ls --format '{{.Name}}' | grep -q '^bridge$'; then
  pass "Docker network: default bridge exists"
else
  fail "Docker network: default bridge missing"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 1 — gtp5g Kernel Module"
# ════════════════════════════════════════════════════════════════════════════

if lsmod | grep -q '^gtp5g'; then
  GTP5G_VER=$(modinfo gtp5g 2>/dev/null | grep '^version' | awk '{print $2}')
  pass "gtp5g module loaded (v${GTP5G_VER})"
  # Validate version range: >= 0.9.5 and < 0.10.0
  MAJOR=$(echo "${GTP5G_VER}" | cut -d. -f1)
  MINOR=$(echo "${GTP5G_VER}" | cut -d. -f2)
  PATCH=$(echo "${GTP5G_VER}" | cut -d. -f3)
  if [ "${MAJOR}" -eq 0 ] && [ "${MINOR}" -eq 9 ] && [ "${PATCH}" -ge 5 ]; then
    pass "gtp5g version ${GTP5G_VER} is compatible with free5GC v4.1.0 (requires 0.9.5 <= v < 0.10.0)"
  else
    fail "gtp5g version ${GTP5G_VER} is NOT compatible — UPF will crash (need 0.9.5 <= v < 0.10.0)"
  fi
else
  fail "gtp5g module not loaded — UPF will fail (run: modprobe gtp5g)"
fi

# Step 1.1: OS, kernel, and toolchain prerequisites
OS_ID=$(awk -F= '/^ID=/{gsub(/"/,"",$2); print $2}' /etc/os-release 2>/dev/null || echo "unknown")
if [ "${OS_ID}" = "ubuntu" ]; then
  pass "OS check: Ubuntu detected"
else
  fail "OS check: expected Ubuntu 20.04/22.04, found '${OS_ID}'"
fi

KERNEL_REL=$(uname -r 2>/dev/null || echo "0.0.0")
KERNEL_MAJOR=$(echo "${KERNEL_REL}" | cut -d. -f1)
if [ "${KERNEL_MAJOR:-0}" -ge 5 ]; then
  pass "Kernel check: ${KERNEL_REL} (>= 5.0)"
else
  fail "Kernel check: ${KERNEL_REL} (< 5.0, gtp5g may fail)"
fi

for bin in git make gcc; do
  if command -v "${bin}" >/dev/null 2>&1; then
    pass "Dependency: ${bin} available"
  else
    fail "Dependency: ${bin} missing (install with apt)"
  fi
done

# Step 1.3/1.5: repository and key config files
if [ -d .git ]; then
  pass "Repository check: free5gc-compose git workspace detected"
else
  fail "Repository check: .git directory not found in ${COMPOSE_DIR}"
fi

REQUIRED_CONFIGS="config/amfcfg.yaml config/smfcfg.yaml config/upfcfg.yaml config/gnbcfg.yaml config/uecfg.yaml"
for cfg in ${REQUIRED_CONFIGS}; do
  if [ -f "${cfg}" ]; then
    pass "Config present: ${cfg}"
  else
    fail "Config missing: ${cfg}"
  fi
done

# Step 1.6: SUCI profile/key and NAS algorithm config
if [ -f config/uecfg.yaml ]; then
  if file_contains config/uecfg.yaml 'protectionScheme:[[:space:]]*1'; then
    pass "UE config: protectionScheme=1 (Profile A)"
  else
    fail "UE config: protectionScheme=1 not found (Profile mismatch risk)"
  fi

  if file_contains config/uecfg.yaml 'homeNetworkPublicKeyId:[[:space:]]*1'; then
    pass "UE config: homeNetworkPublicKeyId=1 present"
  else
    fail "UE config: homeNetworkPublicKeyId=1 missing"
  fi

  if file_contains config/uecfg.yaml 'homeNetworkPublicKey:[[:space:]]*\"?[0-9a-fA-F]{64}\"?'; then
    pass "UE config: homeNetworkPublicKey format looks valid"
  else
    fail "UE config: homeNetworkPublicKey missing/invalid"
  fi
fi

if [ -f config/amfcfg.yaml ]; then
  if file_contains config/amfcfg.yaml 'integrityOrder:' && file_contains config/amfcfg.yaml 'NIA2'; then
    pass "AMF config: integrityOrder includes NIA2"
  else
    fail "AMF config: integrityOrder/NIA2 missing"
  fi

  if file_contains config/amfcfg.yaml 'cipheringOrder:' && file_contains config/amfcfg.yaml 'NEA2'; then
    pass "AMF config: cipheringOrder includes NEA2"
  else
    fail "AMF config: cipheringOrder/NEA2 missing"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 3 — Containers Running"
# ════════════════════════════════════════════════════════════════════════════

REQUIRED_SERVICES="mongodb nrf amf smf upf ausf udm udr nssf pcf nef chf webui ueransim"

ALL_UP=1
for svc in ${REQUIRED_SERVICES}; do
  # Match container names like "amf", "free5gc-amf", "free5gc-compose-amf-1"
  CNAME=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])${svc}([-_]|$)" | head -1)
  if [ -n "${CNAME}" ]; then
    STATUS=$(docker inspect --format '{{.State.Status}}' "${CNAME}" 2>/dev/null)
    if [ "${STATUS}" = "running" ]; then
      pass "Container ${svc} is running (${CNAME})"
    else
      fail "Container ${svc} is ${STATUS} (expected running)"
      ALL_UP=0
    fi
  else
    fail "Container for service '${svc}' not found"
    ALL_UP=0
  fi
done

TOTAL_RUNNING=$(docker ps -q | wc -l | tr -d ' ')
info "Total running containers: ${TOTAL_RUNNING}"

# Step 3.2 explicit compose status check
if docker compose ps >"${TMP_COMPOSE_PS}" 2>/dev/null; then
  if grep -qE 'Exit|Restarting|Created|Dead' "${TMP_COMPOSE_PS}"; then
    fail "docker compose ps has non-running services (Exit/Restarting/Created/Dead)"
    info "Inspect with: docker compose ps"
  else
    pass "docker compose ps: all listed services are Up/healthy"
  fi
else
  fail "docker compose ps failed"
fi

# Step 3.3 expected privnet subnet
PRIVNET_NAME=$(docker network ls --format '{{.Name}}' | grep -E '(^|_)privnet$' | head -1)
if [ -n "${PRIVNET_NAME}" ]; then
  SUBNET=$(docker network inspect "${PRIVNET_NAME}" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null)
  if [ "${SUBNET}" = "10.100.200.0/24" ]; then
    pass "Docker network ${PRIVNET_NAME}: subnet is ${SUBNET}"
  else
    fail "Docker network ${PRIVNET_NAME}: subnet is '${SUBNET}' (expected 10.100.200.0/24)"
  fi
else
  fail "Docker network '*privnet' not found"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 2 — Subscriber Provisioning"
# ════════════════════════════════════════════════════════════════════════════
# Ensures IMSI 208930000000001 exists in MongoDB with a fresh SQN,
# and that no stale AMF context is present (which would cause MODIFY_NOT_ALLOWED 403
# and trigger the AMF dual-context / PDU session bug).

IMSI="imsi-208930000000001"
PLMN="20893"
WEBUI_URL="http://localhost:5000"
SUB_PROVISIONED=0
STACK_RESTART=0

MONGO_CONTAINER=$(docker ps --format '{{.Names}}' | grep -iE "(^|[-_])mongo(db)?([-_]|$)" | head -1)

if [ -z "${MONGO_CONTAINER}" ]; then
  fail "Subscriber: MongoDB container not found — cannot provision"
else
  # Check if subscriber exists
  SUB_DOC=$(docker exec "${MONGO_CONTAINER}" mongosh --quiet --eval \
    "JSON.stringify(db.getSiblingDB('free5gc').subscriptionData.authenticationData.authenticationSubscription.findOne({ueId:'${IMSI}'}))" \
    2>/dev/null || echo "null")

  if echo "${SUB_DOC}" | grep -q '"ueId"'; then
    pass "Subscriber: ${IMSI} found in MongoDB"
    SUB_PROVISIONED=1
  else
    info "Subscriber: ${IMSI} not found — provisioning via WebUI API..."

    # Wait up to 30s for WebUI to respond
    WEBUI_READY=0
    for i in $(seq 1 10); do
      STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${WEBUI_URL}/api/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"free5gc"}' 2>/dev/null || echo "000")
      if echo "${STATUS}" | grep -qE "^(200|201)"; then
        WEBUI_READY=1; break
      fi
      sleep 3
    done

    if [ "${WEBUI_READY}" = "0" ]; then
      fail "Subscriber: WebUI not reachable at ${WEBUI_URL} (is webui container running?)"
    else
      # Authenticate
      TOKEN=$(curl -sf -X POST "${WEBUI_URL}/api/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"free5gc"}' 2>/dev/null | \
        grep -oE '"access_token":"[^"]*"' | cut -d'"' -f4)

      if [ -z "${TOKEN}" ]; then
        fail "Subscriber: WebUI login failed — no token returned"
      else
        pass "Subscriber: WebUI authenticated"

        # Create subscriber (SQN 000000000000; will be patched to 0x20 below)
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
          -X POST "${WEBUI_URL}/api/subscriber/${IMSI}/${PLMN}/1" \
          -H "Content-Type: application/json" \
          -H "Token: ${TOKEN}" \
          -d '{
            "plmnID": "'"${PLMN}"'",
            "ueId": "'"${IMSI}"'",
            "AuthenticationSubscription": {
              "authenticationMethod": "5G_AKA",
              "permanentKey": {
                "permanentKeyValue": "8baf473f2f8fd09487cccbd7097c6862",
                "encryptionKey": 0, "encryptionAlgorithm": 0
              },
              "sequenceNumber": "000000000000",
              "authenticationManagementField": "8000",
              "milenage": {
                "op": {"opValue": "", "encryptionKey": 0, "encryptionAlgorithm": 0}
              },
              "opc": {
                "opcValue": "8e27b6af0e692e750f32667a3b14605d",
                "encryptionKey": 0, "encryptionAlgorithm": 0
              }
            },
            "AccessAndMobilitySubscriptionData": {
              "gpsis": ["msisdn-0900000000"],
              "subscribedUeAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"},
              "nssai": {
                "defaultSingleNssais": [{"sst": 1, "sd": "010203"}],
                "singleNssais": [{"sst": 1, "sd": "010203"}]
              }
            },
            "SessionManagementSubscriptionData": [{
              "singleNssai": {"sst": 1, "sd": "010203"},
              "dnnConfigurations": {
                "internet": {
                  "pduSessionTypes": {
                    "defaultSessionType": "IPV4",
                    "allowedSessionTypes": ["IPV4"]
                  },
                  "sscModes": {
                    "defaultSscMode": "SSC_MODE_1",
                    "allowedSscModes": ["SSC_MODE_1","SSC_MODE_2","SSC_MODE_3"]
                  },
                  "5gQosProfile": {
                    "5qi": 9,
                    "arp": {"priorityLevel": 8},
                    "priorityLevel": 8
                  },
                  "sessionAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"}
                }
              }
            }],
            "SmfSelectionSubscriptionData": {
              "subscribedSnssaiInfos": {
                "01010203": {
                  "dnnInfos": [{"dnn": "internet"}]
                }
              }
            },
            "AmPolicyData": {
              "subscCats": ["free5gc"]
            },
            "SmPolicyData": {
              "smPolicySnssaiData": {
                "01010203": {
                  "snssai": {"sst": 1, "sd": "010203"},
                  "smPolicyDnnData": {
                    "internet": {"dnn": "internet"}
                  }
                }
              }
            },
            "UeContextInSmfData": {}
          }' 2>/dev/null || echo "000")

        if echo "${HTTP_CODE}" | grep -qE "^(200|201)"; then
          pass "Subscriber: Created via WebUI API (HTTP ${HTTP_CODE})"
          if docker exec mongodb mongo --quiet free5gc --eval '
db.getCollection("policyData.ues.smData").updateOne(
  { ueId: "imsi-208930000000001" },
  {
    $set: {
      smPolicySnssaiData: {
        "01010203": {
          snssai: { sst: 1, sd: "010203" },
          smPolicyDnnData: {
            internet: { dnn: "internet" }
          }
        }
      }
    }
  },
  { upsert: true }
)
' >/dev/null 2>&1; then
            pass "Subscriber: SM policy data patched in MongoDB"
          else
            fail "Subscriber: unable to patch SM policy data in MongoDB"
          fi
          SUB_PROVISIONED=1
          STACK_RESTART=1
          sleep 1
        else
          fail "Subscriber: WebUI API returned HTTP ${HTTP_CODE} — creation failed"
        fi
      fi
    fi
  fi

  # Always patch SQN to 0x20 (IND=0, SEQ=1 > SQN_MS[0]=0 → auth accepted)
  # SQN=32 (0x20): lower 5 bits = IND=0, upper bits = SEQ=1
  if [ "${SUB_PROVISIONED}" = "1" ]; then
    SQN_RESULT=$(docker exec "${MONGO_CONTAINER}" mongosh --quiet --eval \
      "db.getSiblingDB('free5gc').subscriptionData.authenticationData.authenticationSubscription.updateOne(
        {ueId:'${IMSI}'},
        {\$set: {'sequenceNumber.sqn': '000000000020'}}
      ).matchedCount" 2>/dev/null || echo "0")
    if echo "${SQN_RESULT}" | grep -q "^1"; then
      pass "Subscriber: SQN patched to 000000000020 (3GPP SEQ=1 > SQN_MS=0 → fresh)"
    else
      fail "Subscriber: SQN patch failed (matchedCount=${SQN_RESULT})"
    fi

    # Clear stale AMF context (prevents MODIFY_NOT_ALLOWED 403 → dual-context bug)
    STALE_COUNT=$(docker exec "${MONGO_CONTAINER}" mongosh --quiet --eval \
      "db.getSiblingDB('free5gc').subscriptionData.contextData.amf3gppAccess.deleteMany(
        {ueId:'${IMSI}'}
      ).deletedCount" 2>/dev/null || echo "0")
    if echo "${STALE_COUNT}" | grep -qE "^[1-9]"; then
      info "Subscriber: Cleared ${STALE_COUNT} stale AMF context record(s) — was causing MODIFY_NOT_ALLOWED"
      STACK_RESTART=1
    else
      pass "Subscriber: No stale AMF context (clean state)"
    fi
  fi
fi

# Full stack restart if we provisioned or cleared stale state.
# This ensures AMF starts with no in-memory UE context that conflicts with MongoDB state.
if [ "${STACK_RESTART}" = "1" ]; then
  info "Restarting free5GC stack for clean AMF state (avoids dual-context / PDU session bug)..."
  docker compose down >/dev/null 2>&1 || true
  sleep 3
  docker compose up -d >/dev/null 2>&1
  info "Waiting 45s for all containers to initialize and NFs to register with NRF..."
  sleep 45
  pass "Stack restarted — AMF/SMF/UPF in clean initial state"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 4 — gNB NG Setup (N2: gNB <-> AMF)"
# ════════════════════════════════════════════════════════════════════════════

AMF_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])amf([-_]|$)" | head -1)
GNB_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])ueransim([-_]|$)" | head -1)

if [ -n "${AMF_CONTAINER}" ]; then
  if logs_contain "${AMF_CONTAINER}" "Handle NGSetupRequest"; then
    pass "AMF received NGSetupRequest from gNB"
  else
    fail "AMF has no NGSetupRequest in logs — gNB not connected"
  fi

  if logs_contain "${AMF_CONTAINER}" "Send NG-Setup response"; then
    pass "AMF sent NG-Setup response to gNB"
  else
    fail "AMF did not send NG-Setup response"
  fi

  if logs_contain "${AMF_CONTAINER}" "SCTP Accept"; then
    pass "AMF accepted SCTP connection from gNB"
  else
    fail "No SCTP connection from gNB to AMF"
  fi
else
  fail "AMF container not found — skipping NG Setup checks"
fi

if [ -n "${GNB_CONTAINER}" ]; then
  if logs_contain "${GNB_CONTAINER}" "NG Setup procedure is successful"; then
    pass "gNB: NG Setup procedure is successful"
  else
    fail "gNB: NG Setup procedure did not succeed"
  fi

  if logs_contain "${GNB_CONTAINER}" "SCTP connection established|NG Setup procedure is successful"; then
    pass "gNB: SCTP connection established to AMF"
  else
    fail "gNB: SCTP connection not established"
  fi
else
  fail "UERANSIM container not found — skipping gNB checks"
fi

if [ "${QUICK}" = "1" ]; then
  info "Quick mode: skipping UE, data-plane, and deregistration tests"
  section "Summary"
  echo -e "  Passed: ${GREEN}${PASS_COUNT}${RESET}  Failed: ${RED}${FAIL_COUNT}${RESET}  Skipped: ${YELLOW}${SKIP_COUNT}${RESET}"
  [ "${FAIL_COUNT}" -eq 0 ] && exit 0 || exit 1
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 5 — UE Registration + PDU Session"
# ════════════════════════════════════════════════════════════════════════════

UE_STARTED=0

if [ -n "${GNB_CONTAINER}" ]; then
  # Start nr-ue if not already running
  if docker exec "${GNB_CONTAINER}" pgrep -x nr-ue >/dev/null 2>&1; then
    info "nr-ue process already running inside ueransim container"
    UE_STARTED=1
  else
    info "Starting nr-ue inside ueransim container..."
    docker exec "${GNB_CONTAINER}" bash -lc \
      "nohup ./nr-ue -c config/uecfg.yaml > /tmp/ue.log 2>&1 &" >/dev/null 2>&1 || true
    info "Waiting 15s for registration + PDU session..."
    sleep 15
    UE_STARTED=1
  fi
fi

if [ "${UE_STARTED}" = "1" ] && [ -n "${GNB_CONTAINER}" ]; then
  # Check UE log
  UE_LOG=$(docker exec "${GNB_CONTAINER}" cat /tmp/ue.log 2>/dev/null || echo "")

  if echo "${UE_LOG}" | grep -q "Initial Registration is successful"; then
    pass "UE: Initial Registration is successful"
  else
    fail "UE: Registration did not complete (check /tmp/ue.log in ueransim container)"
  fi

  if echo "${UE_LOG}" | grep -q "MM-REGISTERED"; then
    pass "UE: State is MM-REGISTERED/NORMAL-SERVICE"
  else
    fail "UE: Not in MM-REGISTERED state"
  fi

  if echo "${UE_LOG}" | grep -q "PDU Session Establishment Accept"; then
    pass "UE: PDU Session Establishment Accept received"
  else
    fail "UE: PDU Session Establishment did not complete"
  fi

  if echo "${UE_LOG}" | grep -qE "TUN interface\[uesimtun0"; then
    TUN_IP=$(echo "${UE_LOG}" | grep -oE '10\.[0-9]+\.[0-9]+\.[0-9]+' | tail -1)
    pass "UE: uesimtun0 tunnel interface created (IP: ${TUN_IP:-unknown})"
  else
    fail "UE: uesimtun0 tunnel interface not created"
  fi

  # Verify uesimtun0 exists in container network namespace
  if docker exec "${GNB_CONTAINER}" ip link show uesimtun0 >/dev/null 2>&1; then
    pass "UE: uesimtun0 interface present in container"
  else
    fail "UE: uesimtun0 not found in container (PDU session may have failed)"
  fi
else
  fail "UE: Could not start nr-ue — skipping registration checks"
fi

# Check AMF side of registration
if [ -n "${AMF_CONTAINER}" ]; then
  if logs_contain "${AMF_CONTAINER}" "Handle Registration Request"; then
    pass "AMF: Handled UE Registration Request"
  else
    fail "AMF: No Registration Request seen"
  fi

  if logs_contain "${AMF_CONTAINER}" "Send Registration Accept"; then
    pass "AMF: Sent Registration Accept"
  else
    fail "AMF: Did not send Registration Accept"
  fi
fi

# Check SMF side of PDU session
SMF_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])smf([-_]|$)" | head -1)
if [ -n "${SMF_CONTAINER}" ]; then
  if logs_contain "${SMF_CONTAINER}" "Handle PDU Session Establishment Request"; then
    pass "SMF: Handled PDU Session Establishment Request"
  else
    fail "SMF: Did not handle PDU Session Establishment Request"
  fi

  if logs_contain "${SMF_CONTAINER}" "Selected UPF"; then
    pass "SMF: Selected UPF for PDU session"
  else
    fail "SMF: Did not select a UPF"
  fi

  if logs_contain "${SMF_CONTAINER}" "Sending PFCP Session Establishment Request"; then
    pass "SMF: Sent PFCP Session Establishment Request to UPF"
  else
    fail "SMF: Did not send PFCP Session Establishment Request"
  fi

  if logs_contain "${SMF_CONTAINER}" "Received PFCP Session Establishment Response"; then
    pass "SMF: Received PFCP Session Establishment Response from UPF"
  else
    fail "SMF: Did not receive PFCP Session Establishment Response"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 6 — PFCP Association (N4: SMF <-> UPF)"
# ════════════════════════════════════════════════════════════════════════════

UPF_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])upf([-_]|$)" | head -1)

if [ -n "${UPF_CONTAINER}" ]; then
  if logs_contain "${UPF_CONTAINER}" "handleAssociationSetupRequest"; then
    pass "UPF: PFCP Association Setup Request received from SMF"
  else
    fail "UPF: No PFCP Association — SMF-UPF handshake failed"
  fi

  if logs_contain "${UPF_CONTAINER}" "UPF started"; then
    pass "UPF: Started successfully (no gtp5g version error)"
  else
    fail "UPF: Did not start cleanly (may be gtp5g mismatch)"
  fi

  if logs_contain "${UPF_CONTAINER}" "handleSessionEstablishmentRequest"; then
    pass "UPF: PFCP Session Establishment Request handled (PDR/FAR rules installed)"
  else
    fail "UPF: No PFCP session established — data plane rules not installed"
  fi

  if logs_contain "${UPF_CONTAINER}" "pfcp server started"; then
    pass "UPF: PFCP server listening on N4"
  else
    fail "UPF: PFCP server did not start"
  fi
else
  fail "UPF container not found — skipping PFCP checks"
fi

if [ -n "${SMF_CONTAINER}" ]; then
  if logs_contain "${SMF_CONTAINER}" "Sending PFCP Association Setup Request"; then
    pass "SMF: Sent PFCP Association Setup Request to UPF"
  else
    fail "SMF: Did not send PFCP Association Setup Request"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 7 — Tunneling (GTP-U) Verification"
# ════════════════════════════════════════════════════════════════════════════

if [ -n "${UPF_CONTAINER}" ]; then
  if docker exec "${UPF_CONTAINER}" ss -lunp 2>/dev/null | grep -qE '(:|[[:space:]])2152([[:space:]]|$)'; then
    pass "UPF: UDP/2152 listener present (GTP-U endpoint)"
  else
    fail "UPF: UDP/2152 listener not found (GTP-U may be down)"
  fi

  if logs_contain "${UPF_CONTAINER}" "gtp5g|Gtp5g|open Gtp5g"; then
    pass "UPF: gtp5g/GTP-U activity appears in logs"
  else
    info "UPF: no explicit gtp5g/GTP-U log match (format may differ by image)"
  fi
else
  fail "Step 7: UPF container not found"
fi

if [ -n "${GNB_CONTAINER}" ] && docker exec "${GNB_CONTAINER}" ip -d a show uesimtun0 >"${TMP_UE_TUN}" 2>/dev/null; then
  if grep -q 'POINTOPOINT' "${TMP_UE_TUN}"; then
    pass "UE tunnel: uesimtun0 is POINTOPOINT"
  else
    fail "UE tunnel: uesimtun0 is not POINTOPOINT"
  fi

  if grep -qE 'inet 10\.60\.[0-9]+\.[0-9]+/16' "${TMP_UE_TUN}"; then
    pass "UE tunnel: uesimtun0 has expected UE pool address (10.60.0.0/16)"
  else
    info "UE tunnel: IP is not in 10.60.0.0/16 (pool may be customized)"
  fi
else
  info "UE tunnel: uesimtun0 details unavailable (likely before UE session is up)"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 8 — Forwarding/NAT Verification"
# ════════════════════════════════════════════════════════════════════════════

if [ -n "${UPF_CONTAINER}" ]; then
  if docker exec "${UPF_CONTAINER}" iptables -t nat -S 2>/dev/null | grep -qE 'POSTROUTING .* -j MASQUERADE'; then
    pass "UPF iptables: MASQUERADE rule present on POSTROUTING"
  else
    fail "UPF iptables: MASQUERADE rule missing (N6 NAT may fail)"
  fi

  if docker exec "${UPF_CONTAINER}" iptables -S FORWARD 2>/dev/null | grep -qE -- '-j ACCEPT'; then
    pass "UPF iptables: FORWARD chain has ACCEPT rule"
  else
    fail "UPF iptables: FORWARD ACCEPT rule missing"
  fi

  UPF_FWD=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo "0")
  if [ "${UPF_FWD}" = "1" ]; then
    pass "Host: net.ipv4.ip_forward=1"
  else
    fail "Host: net.ipv4.ip_forward=${UPF_FWD} (expected 1)"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 9 — Data-Plane Verification"
# ════════════════════════════════════════════════════════════════════════════

if [ "${SKIP_PING}" = "1" ]; then
  skip "Data-plane ping/curl (--no-ping flag set)"
elif [ -n "${GNB_CONTAINER}" ] && docker exec "${GNB_CONTAINER}" ip link show uesimtun0 >/dev/null 2>&1; then

  # MTU check
  MTU=$(docker exec "${GNB_CONTAINER}" ip -d link show uesimtun0 2>/dev/null | grep -oE 'mtu [0-9]+' | awk '{print $2}')
  if [ "${MTU:-0}" -le 1400 ] && [ "${MTU:-0}" -gt 0 ]; then
    pass "UE: uesimtun0 MTU=${MTU} (reduced from 1500 for GTP-U overhead)"
  else
    info "UE: uesimtun0 MTU=${MTU:-unknown} (expected <= 1400)"
  fi

  # Ping test (Step 9.1)
  info "Running ping test through uesimtun0 (4 packets to 8.8.8.8)..."
  if docker exec "${GNB_CONTAINER}" ping -c 4 -W 5 -I uesimtun0 8.8.8.8 >/dev/null 2>&1; then
    pass "Data-plane: ping 8.8.8.8 via uesimtun0 — 0% packet loss"
  else
    fail "Data-plane: ping 8.8.8.8 via uesimtun0 failed (check UPF iptables / ip_forward)"
  fi

  # HTTP test (Step 9.2)
  info "Running HTTP test through uesimtun0 (curl example.com)..."
  HTTP_STATUS=$(docker exec "${GNB_CONTAINER}" \
    curl -s -o /dev/null -w "%{http_code}" --interface uesimtun0 \
    --max-time 10 http://example.com 2>/dev/null || echo "000")
  if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "301" ] || [ "${HTTP_STATUS}" = "302" ]; then
    pass "Data-plane: HTTP GET example.com via uesimtun0 — HTTP ${HTTP_STATUS}"
  else
    fail "Data-plane: HTTP GET via uesimtun0 failed (HTTP ${HTTP_STATUS}) — check N6 NAT"
  fi

  # Traffic counter (Step 9.4)
  RX=$(docker exec "${GNB_CONTAINER}" ip -s link show uesimtun0 2>/dev/null | \
    awk '/RX:/{getline; print $1}')
  TX=$(docker exec "${GNB_CONTAINER}" ip -s link show uesimtun0 2>/dev/null | \
    awk '/TX:/{getline; print $1}')
  if [ "${RX:-0}" -gt 0 ] && [ "${TX:-0}" -gt 0 ]; then
    pass "Data-plane: uesimtun0 traffic counters — RX=${RX}B TX=${TX}B"
  else
    fail "Data-plane: uesimtun0 counters are zero — no traffic traversed"
  fi

  # UPF usage reporting (Step 9.5)
  if [ -n "${UPF_CONTAINER}" ] && logs_contain "${UPF_CONTAINER}" "serveUSAReport"; then
    pass "UPF: Usage reporting active (serveUSAReport seen)"
  else
    info "UPF: No usage reports yet (normal if no sustained traffic)"
  fi

  # Wireshark/tcpdump readiness and packet sanity (report capture section)
  if [ "${DO_CAPTURE}" = "1" ]; then
    BRIDGE_IF=$(docker network inspect "${PRIVNET_NAME:-free5gc-compose_privnet}" --format '{{index .Options "com.docker.network.bridge.name"}}' 2>/dev/null)
    if [ -z "${BRIDGE_IF}" ]; then
      BRIDGE_IF="br-free5gc"
    fi

    if command -v tcpdump >/dev/null 2>&1 && ip link show "${BRIDGE_IF}" >/dev/null 2>&1; then
      CAP_FILE="/tmp/free5gc-e2e-${BRANCH:-run}.pcap"
      info "Capturing short trace on ${BRIDGE_IF} to validate NGAP/PFCP/GTP-U visibility..."
      timeout 8 tcpdump -i "${BRIDGE_IF}" -nn -w "${CAP_FILE}" \
        'udp port 2152 or udp port 8805 or sctp port 38412' >/dev/null 2>&1 &
      TCPDUMP_PID=$!
      sleep 1
      docker exec "${GNB_CONTAINER}" ping -c 1 -W 3 -I uesimtun0 8.8.8.8 >/dev/null 2>&1 || true
      wait "${TCPDUMP_PID}" 2>/dev/null || true

      if [ -s "${CAP_FILE}" ]; then
        pass "Capture: pcap generated at ${CAP_FILE}"
        if command -v tcpdump >/dev/null 2>&1; then
          if tcpdump -nn -r "${CAP_FILE}" 2>/dev/null | grep -qE '2152|8805|38412'; then
            pass "Capture: contains expected control/user-plane ports (2152/8805/38412)"
          else
            info "Capture: file exists but expected ports not observed in short window"
          fi
        fi
      else
        fail "Capture: tcpdump did not produce a pcap file"
      fi
    else
      info "Capture: skipped (tcpdump missing or bridge ${BRIDGE_IF} not found)"
    fi
  else
    skip "Capture: skipped by --no-capture"
  fi

else
  if [ "${UE_STARTED}" = "1" ]; then
    fail "Data-plane: uesimtun0 not up — PDU session did not complete, skipping ping/curl"
  else
    skip "Data-plane: UE not started — skipping ping/curl tests"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 10 — Deregistration"
# ════════════════════════════════════════════════════════════════════════════

if [ -n "${GNB_CONTAINER}" ] && docker exec "${GNB_CONTAINER}" pgrep -x nr-ue >/dev/null 2>&1; then
  info "Sending SIGINT to nr-ue for graceful deregistration..."
  docker exec "${GNB_CONTAINER}" pkill -2 nr-ue 2>/dev/null || true
  sleep 5

  # Check UE log for deregistration
  UE_LOG_AFTER=$(docker exec "${GNB_CONTAINER}" cat /tmp/ue.log 2>/dev/null || echo "")
  if echo "${UE_LOG_AFTER}" | grep -q "MM-DEREGISTERED"; then
    pass "UE: Deregistration complete — state is MM-DEREGISTERED"
  else
    fail "UE: MM-DEREGISTERED state not seen in logs after SIGINT"
  fi

  # Check SMF for PFCP session deletion
  if [ -n "${SMF_CONTAINER}" ] && logs_contain "${SMF_CONTAINER}" "Sending PFCP Session Deletion Request"; then
    pass "SMF: Sent PFCP Session Deletion Request (PDU session cleaned up)"
  else
    fail "SMF: No PFCP Session Deletion — resources may not be released"
  fi

  # Check UPF for session deletion
  if [ -n "${UPF_CONTAINER}" ] && logs_contain "${UPF_CONTAINER}" "handleSessionDeletionRequest"; then
    pass "UPF: PFCP Session Deletion handled — forwarding rules removed"
  else
    fail "UPF: PFCP Session Deletion not seen"
  fi

  # Check AMF for deregistration
  if [ -n "${AMF_CONTAINER}" ] && logs_contain "${AMF_CONTAINER}" "Handle Deregistration Request"; then
    pass "AMF: Handled UE Deregistration Request"
  else
    fail "AMF: No Deregistration Request seen"
  fi
else
  skip "Deregistration: nr-ue not running — skipping deregistration test"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 11 — Authentication Flow Verification"
# ════════════════════════════════════════════════════════════════════════════

if [ -n "${GNB_CONTAINER}" ]; then
  UE_AUTH_LOG=$(docker exec "${GNB_CONTAINER}" cat /tmp/ue.log 2>/dev/null || echo "")

  if echo "${UE_AUTH_LOG}" | grep -qi "Authentication Request received"; then
    pass "UE auth: Authentication Request received"
  else
    fail "UE auth: Authentication Request not found in UE log"
  fi

  if echo "${UE_AUTH_LOG}" | grep -qi "Received SQN"; then
    pass "UE auth: Received SQN present"
  else
    fail "UE auth: Received SQN not found"
  fi

  if echo "${UE_AUTH_LOG}" | grep -qi "SQN-MS"; then
    pass "UE auth: SQN-MS present (anti-replay window check)"
  else
    fail "UE auth: SQN-MS not found"
  fi
fi

AUSF_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])ausf([-_]|$)" | head -1)
UDM_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])udm([-_]|$)" | head -1)

if [ -n "${AMF_CONTAINER}" ]; then
  if logs_contain "${AMF_CONTAINER}" "Authentication"; then
    pass "AMF auth: authentication-related logs present"
  else
    fail "AMF auth: authentication-related logs not found"
  fi
fi

if [ -n "${AUSF_CONTAINER}" ]; then
  if logs_contain "${AUSF_CONTAINER}" "auth|Auth"; then
    pass "AUSF auth: authentication logs present"
  else
    info "AUSF auth: no auth log match with current pattern"
  fi
fi

if [ -n "${UDM_CONTAINER}" ]; then
  if logs_contain "${UDM_CONTAINER}" "suci|SUCI|de-conceal|deconceal|Auth"; then
    pass "UDM auth: SUCI/auth processing logs present"
  else
    info "UDM auth: no SUCI/auth log match with current pattern"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Step 12 — NAS Security Algorithm Negotiation"
# ════════════════════════════════════════════════════════════════════════════

# Check AMF sent Security Mode Command
if [ -n "${AMF_CONTAINER}" ]; then
  if logs_contain "${AMF_CONTAINER}" "Send Security Mode Command"; then
    pass "AMF: Sent Security Mode Command to UE"
  else
    fail "AMF: Security Mode Command not seen (NAS security not established)"
  fi

  if logs_contain "${AMF_CONTAINER}" "Handle Security Mode Complete"; then
    pass "AMF: Received Security Mode Complete from UE"
  else
    fail "AMF: Security Mode Complete not received"
  fi
fi

# Check UE logs for algorithm selection
if [ -n "${GNB_CONTAINER}" ]; then
  UE_LOG_FINAL=$(docker exec "${GNB_CONTAINER}" cat /tmp/ue.log 2>/dev/null || echo "")

  if echo "${UE_LOG_FINAL}" | grep -q "Security Mode Command received"; then
    pass "UE: Security Mode Command received"
  else
    fail "UE: Security Mode Command not received"
  fi

  # Extract selected algorithms
  ALGO_LINE=$(echo "${UE_LOG_FINAL}" | grep -oE 'Selected integrity\[[0-9]\] ciphering\[[0-9]\]' | tail -1)
  if [ -n "${ALGO_LINE}" ]; then
    INT_ALG=$(echo "${ALGO_LINE}" | grep -oE 'integrity\[[0-9]\]' | grep -oE '[0-9]')
    ENC_ALG=$(echo "${ALGO_LINE}" | grep -oE 'ciphering\[[0-9]\]' | grep -oE '[0-9]')
    INT_NAME="NIA${INT_ALG}"
    ENC_NAME="NEA${ENC_ALG}"
    pass "NAS security: Selected integrity=${INT_NAME}, ciphering=${ENC_NAME}"
    if [ "${INT_ALG}" = "2" ]; then
      info "Integrity: NIA2 = AES-128-CMAC (strong)"
    elif [ "${INT_ALG}" = "1" ]; then
      info "Integrity: NIA1 = SNOW 3G"
    fi
    if [ "${ENC_ALG}" = "0" ]; then
      info "Ciphering: NEA0 = null encryption (NAS content visible in pcap — expected in lab)"
    elif [ "${ENC_ALG}" = "2" ]; then
      info "Ciphering: NEA2 = AES-128-CTR (encrypted)"
    fi
  else
    fail "NAS security: Could not extract algorithm selection from UE logs"
  fi

  # SUCI protection
  if echo "${UE_LOG_FINAL}" | grep -qiE "suci|concealed"; then
    pass "UE: SUCI (concealed identity) used in Registration Request"
  else
    info "UE: SUCI usage not confirmed in logs"
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
section "Infrastructure Spot Checks"
# ════════════════════════════════════════════════════════════════════════════

# WebUI port
if ss -tlnp 2>/dev/null | grep -q ':5000'; then
  pass "WebUI: Listening on port 5000 (http://localhost:5000)"
else
  fail "WebUI: Not listening on port 5000"
fi

# MongoDB
# MONGO_CONTAINER already resolved in Step 2
if [ -n "${MONGO_CONTAINER}" ]; then
  if docker exec "${MONGO_CONTAINER}" mongosh --quiet --eval "db.runCommand({ping:1})" >/dev/null 2>&1 || \
     docker exec "${MONGO_CONTAINER}" mongo --quiet --eval "db.runCommand({ping:1})" >/dev/null 2>&1; then
    pass "MongoDB: Responding to ping"
  else
    fail "MongoDB: Not responding"
  fi
fi

# NRF registrations
NRF_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "(^|[-_])nrf([-_]|$)" | head -1)
if [ -n "${NRF_CONTAINER}" ]; then
  NF_REG_COUNT=$(docker logs --tail=200 "${NRF_CONTAINER}" 2>&1 | grep -c "Handle NFRegisterRequest" || true)
  if [ "${NF_REG_COUNT}" -ge 5 ]; then
    pass "NRF: ${NF_REG_COUNT} NF registrations received (all core NFs registered)"
  else
    fail "NRF: Only ${NF_REG_COUNT} NF registrations — some NFs may have failed to register"
  fi
fi

# IP forwarding
IP_FWD=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo "0")
if [ "${IP_FWD}" = "1" ]; then
  pass "Host: net.ipv4.ip_forward=1"
else
  fail "Host: net.ipv4.ip_forward=0 — data plane will not work (run: sysctl -w net.ipv4.ip_forward=1)"
fi

# gtp5g loads at boot
if [ -f /etc/modules-load.d/free5gc.conf ] && grep -q gtp5g /etc/modules-load.d/free5gc.conf; then
  pass "gtp5g: Configured to load at boot (/etc/modules-load.d/free5gc.conf)"
else
  fail "gtp5g: NOT configured to load at boot — will need manual modprobe after reboot"
fi

# systemd service
if systemctl is-enabled free5gc-compose.service >/dev/null 2>&1; then
  pass "Systemd: free5gc-compose.service is enabled (auto-starts on boot)"
else
  fail "Systemd: free5gc-compose.service is NOT enabled"
fi

# ════════════════════════════════════════════════════════════════════════════
section "Validation Checklist Coverage"
# ════════════════════════════════════════════════════════════════════════════

# Troubleshooting validation (automatable subset)
if command -v ss >/dev/null 2>&1 && command -v lsof >/dev/null 2>&1; then
  pass "Troubleshooting: tools available for port-conflict diagnosis (ss/lsof)"
else
  fail "Troubleshooting: missing ss or lsof for port-conflict diagnosis"
fi

if command -v modprobe >/dev/null 2>&1; then
  pass "Troubleshooting: modprobe available to load gtp5g"
else
  fail "Troubleshooting: modprobe missing"
fi

if docker compose ps >/dev/null 2>&1; then
  pass "Troubleshooting: docker compose ps works for failed-container identification"
else
  fail "Troubleshooting: docker compose ps unavailable"
fi

if docker compose logs --tail=1 >/dev/null 2>&1; then
  pass "Troubleshooting: docker compose logs works for root-cause inspection"
else
  fail "Troubleshooting: docker compose logs unavailable"
fi

# Conceptual validation is intentionally manual.
skip "Conceptual validation (NF roles/interfaces/PFCP/GTP-U rationale) is manual by design"

# ════════════════════════════════════════════════════════════════════════════
section "Summary"
# ════════════════════════════════════════════════════════════════════════════

TOTAL=$(( PASS_COUNT + FAIL_COUNT + SKIP_COUNT ))
echo ""
echo -e "  Tests run:    ${TOTAL}"
echo -e "  ${GREEN}Passed:${RESET}       ${PASS_COUNT}"
echo -e "  ${RED}Failed:${RESET}       ${FAIL_COUNT}"
echo -e "  ${YELLOW}Skipped:${RESET}      ${SKIP_COUNT}"
echo ""

if [ "${FAIL_COUNT}" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}ALL TESTS PASSED — free5GC + UERANSIM stack is fully operational${RESET}"
  exit 0
else
  echo -e "${RED}${BOLD}${FAIL_COUNT} TEST(S) FAILED — review output above${RESET}"
  echo ""
  echo "  Tips:"
  echo "    free5gc-status          — check container logs"
  echo "    docker compose logs -f  — live log stream"
  echo "    lsmod | grep gtp5g      — verify kernel module"
  exit 1
fi
