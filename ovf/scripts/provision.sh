#!/bin/bash
# Main Packer provision script: OS, Docker, gtp5g, repo, images, systemd, status/self-test.
# Runs on the VM. Scripts are uploaded to /tmp/free5gc-ovf-scripts by Packer file provisioner.
set -euo pipefail

SCRIPT_DIR="/tmp/free5gc-ovf-scripts"
LOCAL_REPO_DIR="/tmp/free5gc-compose"
REPO_URL="${REPO_URL:-https://github.com/Arjitg450/free5gc-compose.git}"
TARGET_DIR="/opt/free5gc-compose"
BRANCH="${BRANCH:-bootcamp}"

export DEBIAN_FRONTEND=noninteractive

echo "=== Provision: OS packages ==="
apt-get update -qq
apt-get install -y -qq \
  curl git jq make gcc net-tools iproute2 python3 python3-pip \
  ca-certificates gnupg lsb-release

echo "=== Provision: Disable unattended-upgrades for reproducibility ==="
apt-get install -y -qq unattended-upgrades 2>/dev/null || true
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
  sed -i 's/^APT::Periodic::Unattended-Upgrade "1";/APT::Periodic::Unattended-Upgrade "0";/' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || true
  echo 'APT::Periodic::Unattended-Upgrade "0";' > /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || true
fi

echo "=== Provision: Docker Engine (pinned) ==="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
  usermod -aG docker ubuntu 2>/dev/null || true
fi
apt-get install -y -qq docker-compose-plugin 2>/dev/null || true
docker --version
docker compose version

echo "=== Provision: gtp5g kernel module ==="
chmod +x "${SCRIPT_DIR}/install-gtp5g.sh"
"${SCRIPT_DIR}/install-gtp5g.sh"

echo "=== Provision: sysctl for forwarding ==="
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-free5gc.conf
sysctl -p /etc/sysctl.d/99-free5gc.conf 2>/dev/null || true

echo "=== Provision: Clone repo and pull images ==="
chmod +x "${SCRIPT_DIR}/clone-and-pull.sh"
REPO_URL="${REPO_URL}" TARGET_DIR="${TARGET_DIR}" LOCAL_REPO_DIR="${LOCAL_REPO_DIR}" PULL_IMAGES=0 "${SCRIPT_DIR}/clone-and-pull.sh" "${BRANCH}"

echo "=== Provision: Install systemd unit ==="
cp "${TARGET_DIR}/ovf/systemd/free5gc-compose.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/free5gc-compose.service
# Ensure start script is executable
chmod +x "${TARGET_DIR}/ovf/scripts/start-free5gc.sh"
systemctl daemon-reload
systemctl enable free5gc-compose.service

echo "=== Provision: Install free5gc-status, self-test.sh, and e2e-test.sh ==="
cp "${TARGET_DIR}/ovf/free5gc-status" /usr/local/bin/
cp "${TARGET_DIR}/ovf/self-test.sh" /usr/local/bin/
cp "${SCRIPT_DIR}/e2e-test.sh" /usr/local/bin/
chmod 755 /usr/local/bin/free5gc-status /usr/local/bin/self-test.sh /usr/local/bin/e2e-test.sh

echo "=== Provision: Install branch-switch.sh into repo for user convenience ==="
chmod +x "${TARGET_DIR}/ovf/scripts/branch-switch.sh"

echo "=== Provision: Pull prebuilt container images ==="
cd "${TARGET_DIR}"
docker compose pull

echo "=== Provision: Start compose stack ==="
COMPOSE_DIR="${TARGET_DIR}" "${TARGET_DIR}/ovf/scripts/start-free5gc.sh"
sleep 45
/usr/local/bin/self-test.sh

WEBUI_URL="http://localhost:5000"
IMSI="imsi-208930000000001"
PLMN="20893"

echo "=== Provision: Seed default subscriber ==="
TOKEN=$(curl -sf -X POST "${WEBUI_URL}/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"free5gc"}' | \
  grep -oE '"access_token":"[^"]*"' | cut -d'"' -f4)

if [ -z "${TOKEN}" ]; then
  echo "WebUI login failed during provisioning" >&2
  exit 1
fi

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
      "sequenceNumber": "000000000020",
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
            "allowedSscModes": ["SSC_MODE_1", "SSC_MODE_2", "SSC_MODE_3"]
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
  }')

if [ "${HTTP_CODE}" != "201" ] && [ "${HTTP_CODE}" != "200" ]; then
  echo "Subscriber provisioning failed with HTTP ${HTTP_CODE}" >&2
  exit 1
fi

echo "=== Provision: Patch subscriber SM policy data in MongoDB ==="
docker exec mongodb mongo --quiet free5gc --eval '
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
' >/dev/null

echo "=== Provision: Restart stack with seeded subscriber ==="
cd "${TARGET_DIR}"
docker compose down >/dev/null
docker compose up -d >/dev/null
sleep 45

echo "=== Provision: Install curl inside persisted ueransim container ==="
docker exec ueransim bash -lc "apt-get update >/dev/null && apt-get install -y curl >/dev/null"
echo "=== Provision: Stop stack but preserve prepared containers ==="
docker compose stop >/dev/null
echo "=== Provision: Environment is ready for manual report walkthrough ==="

echo "=== Provision: Clean up ==="
rm -rf "${SCRIPT_DIR}"
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "=== Provision: Done. First boot will start free5gc-compose.service ==="
