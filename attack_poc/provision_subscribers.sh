#!/bin/bash
# ============================================================================
# provision_subscribers.sh — Register UE1 and UE2 via free5gc WebUI REST API
# ============================================================================
set -euo pipefail

WEBUI_URL="${WEBUI_URL:-http://localhost:5050}"
PLMN="20893"
KEY="8baf473f2f8fd09487cccbd7097c6862"
OPC="8e27b6af0e692e750f32667a3b14605d"
SQN="000000000020"
AMF="8000"

echo "[*] Provisioning UE1 and UE2 via WebUI API at ${WEBUI_URL}..."

# ─── Login to get JWT token ────────────────────────────────────────────────
echo "[*] Logging in to WebUI..."
login_resp=$(curl -s -X POST "${WEBUI_URL}/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"free5gc"}')

TOKEN=$(echo "$login_resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "FATAL: Failed to get JWT token from WebUI. Response: $login_resp"
  exit 1
fi
echo "    JWT token obtained."

# ─── Delete existing subscribers (ignore errors) ──────────────────────────
curl -s -o /dev/null -X DELETE "${WEBUI_URL}/api/subscriber/imsi-208930000000001/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" || true
curl -s -o /dev/null -X DELETE "${WEBUI_URL}/api/subscriber/imsi-208930000000002/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" || true
sleep 1

# ─── Subscriber payload ───────────────────────────────────────────────────
sub_create() {
  local ue_id="$1"
  local msisdn="$2"
  cat << EOF
{
  "plmnID": "${PLMN}",
  "ueId": "${ue_id}",
  "AuthenticationSubscription": {
    "authenticationManagementField": "${AMF}",
    "authenticationMethod": "5G_AKA",
    "milenage": {
      "op": { "encryptionAlgorithm": 0, "encryptionKey": 0, "opValue": "" }
    },
    "opc": {
      "encryptionAlgorithm": 0, "encryptionKey": 0,
      "opcValue": "${OPC}"
    },
    "permanentKey": {
      "encryptionAlgorithm": 0, "encryptionKey": 0,
      "permanentKeyValue": "${KEY}"
    },
    "sequenceNumber": "${SQN}"
  },
  "AccessAndMobilitySubscriptionData": {
    "gpsis": [ "msisdn-${msisdn}" ],
    "nssai": {
      "defaultSingleNssais": [
        { "sst": 1, "sd": "010203", "isDefault": true },
        { "sst": 1, "sd": "112233", "isDefault": true }
      ],
      "singleNssais": []
    },
    "subscribedUeAmbr": { "downlink": "2 Gbps", "uplink": "1 Gbps" }
  },
  "SessionManagementSubscriptionData": [
    {
      "singleNssai": { "sst": 1, "sd": "010203" },
      "dnnConfigurations": {
        "internet": {
          "sscModes": { "defaultSscMode": "SSC_MODE_1", "allowedSscModes": [ "SSC_MODE_2", "SSC_MODE_3" ] },
          "pduSessionTypes": { "defaultSessionType": "IPV4", "allowedSessionTypes": [ "IPV4" ] },
          "sessionAmbr": { "uplink": "200 Mbps", "downlink": "100 Mbps" },
          "5gQosProfile": { "5qi": 9, "arp": { "priorityLevel": 8 }, "priorityLevel": 8 }
        }
      }
    },
    {
      "singleNssai": { "sst": 1, "sd": "112233" },
      "dnnConfigurations": {
        "internet": {
          "sscModes": { "defaultSscMode": "SSC_MODE_1", "allowedSscModes": [ "SSC_MODE_2", "SSC_MODE_3" ] },
          "pduSessionTypes": { "defaultSessionType": "IPV4", "allowedSessionTypes": [ "IPV4" ] },
          "sessionAmbr": { "uplink": "200 Mbps", "downlink": "100 Mbps" },
          "5gQosProfile": { "5qi": 9, "arp": { "priorityLevel": 8 }, "priorityLevel": 8 }
        }
      }
    }
  ],
  "SmfSelectionSubscriptionData": {
    "subscribedSnssaiInfos": {
      "01010203": { "dnnInfos": [ { "dnn": "internet" } ] },
      "01112233": { "dnnInfos": [ { "dnn": "internet" } ] }
    }
  },
  "AmPolicyData": { "subscCats": [ "free5gc" ] },
  "SmPolicyData": {
    "smPolicySnssaiData": {
      "01010203": {
        "snssai": { "sst": 1, "sd": "010203" },
        "smPolicyDnnData": { "internet": { "dnn": "internet" } }
      },
      "01112233": {
        "snssai": { "sst": 1, "sd": "112233" },
        "smPolicyDnnData": { "internet": { "dnn": "internet" } }
      }
    }
  }
}
EOF
}

# ─── Create UE1 ───────────────────────────────────────────────────────────
resp=$(curl -s -w "\n%{http_code}" -X POST "${WEBUI_URL}/api/subscriber/imsi-208930000000001/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" \
  -d "$(sub_create "imsi-208930000000001" "0900000001")")
code=$(echo "$resp" | tail -n1)
if [ "$code" = "201" ] || [ "$code" = "200" ]; then
  echo "[OK] UE1 (imsi-208930000000001) provisioned — S-NSSAI SST=1 SD=010203"
else
  echo "FATAL: UE1 provision failed (HTTP $code). Response: $(echo "$resp" | head -n -1)"
  exit 1
fi

# ─── Create UE2 ───────────────────────────────────────────────────────────
resp=$(curl -s -w "\n%{http_code}" -X POST "${WEBUI_URL}/api/subscriber/imsi-208930000000002/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" \
  -d "$(sub_create "imsi-208930000000002" "0900000002")")
code=$(echo "$resp" | tail -n1)
if [ "$code" = "201" ] || [ "$code" = "200" ]; then
  echo "[OK] UE2 (imsi-208930000000002) provisioned — S-NSSAI SST=1 SD=112233"
else
  echo "FATAL: UE2 provision failed (HTTP $code). Response: $(echo "$resp" | head -n -1)"
  exit 1
fi

echo ""
echo "[OK] Both subscribers provisioned successfully."
